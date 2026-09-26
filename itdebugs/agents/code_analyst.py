"""
agents/code_analyst.py
======================
Code Analyst agent.

Responsibility
--------------
Inspect source files that are relevant to the bug and the failing tests.
Identify suspicious code locations by:
  1. Grepping source files for keywords derived from the bug description
     and failure messages.
  2. Extracting the bodies of methods referenced in failing tests.
  3. Looking for common bug patterns (wrong string literal in a comparison,
     mismatched value names, etc.).

Reuses
------
``itdebugs.engine.code_reader.grep``
``itdebugs.engine.code_reader.extract_block``
``itdebugs.engine.code_reader.extract_relevant_sections``

Requires
--------
ctx.repo_structure  (set by RepositoryAnalyst)
ctx.failing_tests   (set by TestAnalyst)
ctx.keywords        (set by TestAnalyst)

Populates
---------
ctx.relevant_files        :  refined list of source paths most relevant to the bug
ctx.suspicious_locations  :  list of "file:line" strings flagged as potentially faulty
"""

from __future__ import annotations

import re
from typing import List

from itdebugs.agents.base import BaseAgent
from itdebugs.agents.context import InvestigationContext
from itdebugs.engine.code_reader import grep, extract_block, extract_relevant_sections

_METHOD_CALL_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\(", re.IGNORECASE)
_NOISE_NAMES = {"assert", "len", "str", "int", "list", "dict", "set", "print", "range", "open"}


def _methods_in_text(text: str) -> List[str]:
    return list(dict.fromkeys(
        m for m in _METHOD_CALL_RE.findall(text)
        if len(m) > 2 and m.lower() not in _NOISE_NAMES
    ))


class CodeAnalyst(BaseAgent):
    """
    Inspects source code for locations relevant to the reported bug.

    The analyst uses a keyword-grep pass followed by a method-body
    extraction pass, then scores files by relevance.

    Future LLM enhancement
    ----------------------
    An LLM-powered version could:
      - Understand the semantic intent of a method from its docstring
      - Spot logic errors that don't match simple regex patterns
      - Suggest explanations in natural language
    """

    @property
    def name(self) -> str:
        return "Code Analyst"

    def _execute(self, ctx: InvestigationContext) -> None:
        if ctx.repo_structure is None:
            raise RuntimeError("repo_structure not set; run RepositoryAnalyst first")

        structure = ctx.repo_structure
        source_paths = [f.relative_path for f in structure.source_files]
        keywords = ctx.keywords[:10]  # cap to avoid noise

        # ── Pass 1: collect file hit counts via grep ─────────────────────
        file_hit_counts: dict[str, int] = {p: 0 for p in source_paths}
        for kw in keywords:
            try:
                matches = grep(ctx.repo_path, re.escape(kw), paths=source_paths)
            except Exception:
                continue
            for match in matches:
                if match.file in file_hit_counts:
                    file_hit_counts[match.file] += 1

        # Sort by relevance score; penalise __init__ files
        def _score(path: str) -> int:
            score = file_hit_counts.get(path, 0)
            if "__init__" in path:
                score -= 2
            return score

        ranked = sorted(source_paths, key=_score, reverse=True)
        # Keep files with at least one keyword hit (or all if none matched)
        relevant = [p for p in ranked if file_hit_counts.get(p, 0) > 0] or ranked
        ctx.relevant_files = relevant

        self._log(
            f"[{self.name}] Relevant files ranked: "
            f"{[p.split('/')[-1].split(chr(92))[-1] for p in relevant[:5]]}"
        )

        # ── Pass 2: find suspicious lines via method extraction ───────────
        candidate_methods: List[str] = []
        for tr in ctx.failing_tests:
            candidate_methods.extend(_methods_in_text(tr.test_name))
            candidate_methods.extend(_methods_in_text(tr.failure_message))
        candidate_methods = list(dict.fromkeys(candidate_methods))

        suspicious: List[str] = []
        for src_path in relevant:
            for method in candidate_methods:
                block = extract_block(ctx.repo_path, src_path, method)
                if block is None:
                    continue
                # Look for comparison against a string literal
                comparisons = re.finditer(
                    r'[!=]=\s*["\']([^"\']+)["\']', block.source
                )
                for comp in comparisons:
                    # Find the exact line number within the block
                    cmp_val = comp.group(1)
                    # Scan within the block lines for the comparison
                    for lineno in range(block.start_line, block.end_line + 1):
                        sections = extract_relevant_sections(
                            ctx.repo_path, src_path, [cmp_val], context_lines=0
                        )
                        for sec_lineno, _ in sections:
                            loc = f"{src_path}:{sec_lineno}"
                            if loc not in suspicious:
                                suspicious.append(loc)
                        break  # only need first hit per comparison

        ctx.suspicious_locations = suspicious
        ctx.add_note(
            self.name,
            f"Identified {len(relevant)} relevant file(s). "
            f"Flagged {len(suspicious)} suspicious location(s): {suspicious[:5]}",
        )
        self._log(
            f"[{self.name}] {len(relevant)} relevant file(s), "
            f"{len(suspicious)} suspicious location(s)"
        )
