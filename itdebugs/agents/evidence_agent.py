"""
agents/evidence_agent.py
========================

Evidence Agent.

Collects and prioritizes the most useful evidence for debugging.

Evidence priority:

1. Failing tests
2. Suspicious source locations
3. Grep matches
4. General relevant code sections

Evidence is bounded so downstream LLM reasoning receives a focused context.
"""

from __future__ import annotations

import re
from pathlib import Path

from itdebugs.agents.base import BaseAgent
from itdebugs.agents.context import InvestigationContext
from itdebugs.engine.code_reader import grep, extract_relevant_sections
from itdebugs.engine.reporter import EvidenceItem


class EvidenceAgent(BaseAgent):
    """Collect and prioritize debugging evidence."""

    MAX_EVIDENCE = 12

    @property
    def name(self) -> str:
        return "Evidence Agent"

    def _execute(self, ctx: InvestigationContext) -> None:
        evidence: list[EvidenceItem] = []
        seen: set[tuple[str, str, str]] = set()

        def _add(ev: EvidenceItem) -> None:
            key = (
                ev.category,
                ev.location,
                ev.snippet.strip(),
            )

            if key in seen:
                return

            if len(evidence) >= self.MAX_EVIDENCE:
                return

            seen.add(key)
            evidence.append(ev)

        # ---------------------------------------------------------
        # 1. FAILING TESTS
        # ---------------------------------------------------------

        for tr in ctx.failing_tests:
            _add(
                EvidenceItem(
                    category="failing_test",
                    description=f"Test '{tr.test_name}' FAILED",
                    location=tr.node_id,
                    snippet=(
                        tr.failure_message[:1500]
                        if tr.failure_message
                        else "(no detail)"
                    ),
                )
            )

            self._log(
                f"[{self.name}] Failing test: {tr.node_id}"
            )

        # ---------------------------------------------------------
        # 2. SUSPICIOUS SOURCE LOCATIONS
        # ---------------------------------------------------------

        # Keep this bounded so grep evidence always gets a chance.
        for location in ctx.suspicious_locations[:6]:
            if len(evidence) >= self.MAX_EVIDENCE:
                break

            parts = location.rsplit(":", 1)

            if len(parts) != 2:
                continue

            src_file, line_text = parts

            try:
                line_number = int(line_text)
            except ValueError:
                continue

            full_path = Path(ctx.repo_path) / src_file

            try:
                lines = full_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            except (OSError, UnicodeDecodeError):
                continue

            if not (1 <= line_number <= len(lines)):
                continue

            start = max(0, line_number - 2)
            end = min(len(lines), line_number + 2)

            snippet_lines = []

            for index in range(start, end):
                snippet_lines.append(
                    f"{index + 1}: {lines[index]}"
                )

            snippet = "\n".join(snippet_lines)

            _add(
                EvidenceItem(
                    category="code_inspection",
                    description=(
                        "Suspicious source location "
                        f"around line {line_number}"
                    ),
                    location=f"{src_file}:{line_number}",
                    snippet=snippet,
                )
            )

            self._log(
                f"[{self.name}] Suspicious location: "
                f"{src_file}:{line_number}"
            )

        # ---------------------------------------------------------
        # 3. GREP MATCHES
        # ---------------------------------------------------------

        if len(evidence) < self.MAX_EVIDENCE:
            source_paths = ctx.relevant_files or (
                [
                    f.relative_path
                    for f in ctx.repo_structure.source_files
                ]
                if ctx.repo_structure
                else []
            )

            grep_added = 0

            for keyword in ctx.keywords[:8]:
                if len(evidence) >= self.MAX_EVIDENCE:
                    break

                if not keyword.strip():
                    continue

                try:
                    matches = grep(
                        ctx.repo_path,
                        re.escape(keyword),
                        paths=source_paths or None,
                    )
                except Exception:
                    matches = []

                # If the relevant-file search finds nothing,
                # broaden the search to all Python files.
                if not matches:
                    try:
                        matches = grep(
                            ctx.repo_path,
                            re.escape(keyword),
                            paths=None,
                        )
                    except Exception:
                        matches = []

                for match in matches[:3]:
                    if len(evidence) >= self.MAX_EVIDENCE:
                        break

                    before = len(evidence)

                    _add(
                        EvidenceItem(
                            category="grep_match",
                            description=(
                                f"Keyword '{keyword}' found in source"
                            ),
                            location=(
                                f"{match.file}:"
                                f"{match.line_number}"
                            ),
                            snippet=match.line_text,
                        )
                    )

                    if len(evidence) > before:
                        grep_added += 1

            self._log(
                f"[{self.name}] Added {grep_added} grep evidence item(s)"
            )

        # ---------------------------------------------------------
        # 4. GENERAL RELEVANT CODE
        # ---------------------------------------------------------

        if len(evidence) < self.MAX_EVIDENCE:
            source_paths = ctx.relevant_files or (
                [
                    f.relative_path
                    for f in ctx.repo_structure.source_files
                ]
                if ctx.repo_structure
                else []
            )

            for src_file in source_paths[:5]:
                if len(evidence) >= self.MAX_EVIDENCE:
                    break

                try:
                    sections = extract_relevant_sections(
                        ctx.repo_path,
                        src_file,
                        ctx.keywords[:6],
                        context_lines=4,
                    )
                except Exception:
                    continue

                for lineno, snippet in sections[:2]:
                    if len(evidence) >= self.MAX_EVIDENCE:
                        break

                    _add(
                        EvidenceItem(
                            category="code_inspection",
                            description=(
                                "Relevant section around "
                                f"line {lineno}"
                            ),
                            location=f"{src_file}:{lineno}",
                            snippet=snippet,
                        )
                    )

        # ---------------------------------------------------------
        # STORE RESULTS
        # ---------------------------------------------------------

        ctx.evidence = evidence

        failing_count = sum(
            1
            for item in evidence
            if item.category == "failing_test"
        )

        grep_count = sum(
            1
            for item in evidence
            if item.category == "grep_match"
        )

        code_count = sum(
            1
            for item in evidence
            if item.category == "code_inspection"
        )

        ctx.add_note(
            self.name,
            (
                f"Collected {len(evidence)} prioritized evidence item(s) "
                f"({failing_count} failing tests, "
                f"{grep_count} grep matches, "
                f"{code_count} code sections)."
            ),
        )

        self._log(
            f"[{self.name}] {len(evidence)} prioritized "
            "evidence items"
        )