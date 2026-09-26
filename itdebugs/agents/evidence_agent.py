"""
agents/evidence_agent.py
========================
Evidence Agent.

Responsibility
--------------
Combine evidence produced by the Repository Analyst, Test Analyst, and Code
Analyst into a single ordered list of structured :class:`EvidenceItem` objects.

Evidence is sourced from:
  1. Failing test details (failure messages, assertion outputs)
  2. Grep matches of bug-description keywords in source files
  3. Relevant code sections around suspicious locations
  4. Repository-level observations (config, README hints)

Reuses
------
``itdebugs.engine.code_reader.grep``
``itdebugs.engine.code_reader.extract_relevant_sections``
``itdebugs.engine.reporter.EvidenceItem``

Requires
--------
ctx.repo_structure        (set by RepositoryAnalyst)
ctx.failing_tests         (set by TestAnalyst)
ctx.keywords              (set by TestAnalyst)
ctx.relevant_files        (set by CodeAnalyst)
ctx.suspicious_locations  (set by CodeAnalyst)

Populates
---------
ctx.evidence  :  List[EvidenceItem]
"""

from __future__ import annotations

import re
from typing import List

from itdebugs.agents.base import BaseAgent
from itdebugs.agents.context import InvestigationContext
from itdebugs.engine.code_reader import grep, extract_relevant_sections
from itdebugs.engine.reporter import EvidenceItem


class EvidenceAgent(BaseAgent):
    """
    Aggregates evidence from all prior analysis phases.

    Deduplicates evidence by location so the root-cause agent receives a
    clean, non-redundant picture.

    Future LLM enhancement
    ----------------------
    An LLM-powered version could:
      - Rank evidence by relevance to the specific bug description
      - Identify contradictions automatically
      - Generate a natural-language evidence summary
    """

    @property
    def name(self) -> str:
        return "Evidence Agent"

    def _execute(self, ctx: InvestigationContext) -> None:
        evidence: List[EvidenceItem] = []
        seen_locations: set[str] = set()

        def _add(ev: EvidenceItem) -> None:
            key = f"{ev.category}:{ev.location}"
            if key not in seen_locations:
                seen_locations.add(key)
                evidence.append(ev)

        # ── Evidence category 1: failing test details ─────────────────────
        for tr in ctx.failing_tests:
            _add(EvidenceItem(
                category="failing_test",
                description=f"Test '{tr.test_name}' FAILED",
                location=tr.node_id,
                snippet=tr.failure_message[:1500] if tr.failure_message else "(no detail)",
            ))
            self._log(f"[{self.name}] Failing test: {tr.node_id}")

        # ── Evidence category 2: grep matches in source files ─────────────
        source_paths = ctx.relevant_files or (
            [f.relative_path for f in ctx.repo_structure.source_files]
            if ctx.repo_structure else []
        )
        for kw in ctx.keywords[:8]:
            try:
                matches = grep(ctx.repo_path, re.escape(kw), paths=source_paths)
            except Exception:
                continue
            for match in matches[:5]:
                _add(EvidenceItem(
                    category="grep_match",
                    description=f"Keyword '{kw}' found in source",
                    location=f"{match.file}:{match.line_number}",
                    snippet=match.line_text,
                ))

        # ── Evidence category 3: code sections around suspicious locations ─
        for location in ctx.suspicious_locations[:10]:
            parts = location.rsplit(":", 1)
            if len(parts) != 2:
                continue
            src_file, lineno_str = parts
            try:
                lineno = int(lineno_str)
            except ValueError:
                continue
            sections = extract_relevant_sections(
                ctx.repo_path, src_file, ctx.keywords[:6], context_lines=4
            )
            for sec_lineno, snippet in sections[:3]:
                _add(EvidenceItem(
                    category="code_inspection",
                    description=f"Suspicious code section around line {sec_lineno}",
                    location=f"{src_file}:{sec_lineno}",
                    snippet=snippet,
                ))
                self._log(f"[{self.name}] Code section: {src_file}:{sec_lineno}")

        # ── Evidence category 4: general code inspection of relevant files ─
        for src_file in source_paths[:5]:
            sections = extract_relevant_sections(
                ctx.repo_path, src_file, ctx.keywords[:6], context_lines=4
            )
            for lineno, snippet in sections[:2]:
                _add(EvidenceItem(
                    category="code_inspection",
                    description=f"Relevant section around line {lineno}",
                    location=f"{src_file}:{lineno}",
                    snippet=snippet,
                ))

        ctx.evidence = evidence
        ctx.add_note(
            self.name,
            f"Collected {len(evidence)} evidence item(s) "
            f"({sum(1 for e in evidence if e.category == 'failing_test')} failing tests, "
            f"{sum(1 for e in evidence if e.category == 'grep_match')} grep matches, "
            f"{sum(1 for e in evidence if e.category == 'code_inspection')} code sections).",
        )
        self._log(f"[{self.name}] {len(evidence)} total evidence items")
