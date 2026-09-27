"""
engine/reporter.py
==================
Assembles the structured investigation report produced by the ItDebugs engine.

The report is represented as a plain Python dataclass (:class:`InvestigationReport`)
so downstream code (CLI, future API, future frontend) can consume it in any
format they need.

A :func:`render_text` helper renders it to a human-readable Markdown-style
text report for immediate CLI output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# ---------------------------------------------------------------------------
# Report building-blocks
# ---------------------------------------------------------------------------

@dataclass
class EvidenceItem:
    """A single piece of evidence discovered during the investigation."""
    category: str       # e.g. "failing_test", "code_inspection", "grep_match"
    description: str
    location: str       # file path (+ line ref if available)
    snippet: str        # relevant code or output excerpt


@dataclass
class RootCauseHypothesis:
    """The engine's best hypothesis about what is causing the bug."""
    summary: str                    # one-sentence description
    file: str                       # file that contains the fault
    line_range: str                 # e.g. "71" or "68-72"
    explanation: str                # detailed reasoning
    confidence: str                 # "high" | "medium" | "low"
    faulty_code: str                # the problematic snippet
    suggested_fix: str              # description of what to change (NOT applied yet)


@dataclass
class InvestigationReport:
    """
    The complete output of a single ItDebugs investigation run.
    """
    # Input context
    repo_path: str
    bug_description: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # Discovery phase
    relevant_files: List[str] = field(default_factory=list)
    test_files: List[str] = field(default_factory=list)
    directory_tree: str = ""

    # Test execution
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    failing_test_ids: List[str] = field(default_factory=list)
    failing_test_details: List[str] = field(default_factory=list)   # human-readable summaries
    raw_test_output: str = ""

    # Analysis
    evidence: List[EvidenceItem] = field(default_factory=list)
    root_cause: Optional[RootCauseHypothesis] = None

    # Outcome
    suggested_next_steps: List[str] = field(default_factory=list)
    investigation_notes: List[str] = field(default_factory=list)

    # Status flags
    investigation_successful: bool = False
    error_message: str = ""


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

_SEP = "-" * 72
_THICK = "=" * 72


def _section(title: str) -> str:
    return f"\n{_SEP}\n  {title}\n{_SEP}\n"


def _bullet(items: List[str], indent: int = 2) -> str:
    pad = " " * indent
    return "\n".join(f"{pad}- {item}" for item in items) if items else f"{' ' * indent}(none)"


def render_text(report: InvestigationReport) -> str:
    """
    Render *report* as a human-readable text / Markdown-compatible string
    suitable for printing to a terminal or saving as a .md file.
    """
    lines: List[str] = []

    lines.append(_THICK)
    lines.append("  ItDebugs - Investigation Report")
    lines.append(_THICK)
    lines.append(f"  Generated : {report.timestamp}")
    lines.append(f"  Repository: {report.repo_path}")
    lines.append("")

    # Bug report
    lines.append(_section("BUG REPORT"))
    lines.append(f"  {report.bug_description}")
    lines.append("")

    if not report.investigation_successful and report.error_message:
        lines.append(_section("INVESTIGATION ERROR"))
        lines.append(f"  {report.error_message}")
        return "\n".join(lines)

    # Repository structure
    lines.append(_section("REPOSITORY STRUCTURE"))
    if report.directory_tree:
        for tree_line in report.directory_tree.splitlines():
            lines.append(f"  {tree_line}")
    lines.append("")

    lines.append("  Relevant source files:")
    lines.append(_bullet(report.relevant_files))
    lines.append("")
    lines.append("  Test files:")
    lines.append(_bullet(report.test_files))
    lines.append("")

    # Test execution results
    lines.append(_section("TEST EXECUTION RESULTS"))
    lines.append(f"  Total tests  : {report.tests_total}")
    lines.append(f"  Passed       : {report.tests_passed}")
    lines.append(f"  Failed/Error : {report.tests_failed}")
    lines.append("")

    if report.failing_test_ids:
        lines.append("  Failing tests:")
        for tid in report.failing_test_ids:
            lines.append(f"    FAIL: {tid}")
        lines.append("")

    if report.failing_test_details:
        lines.append("  Failure details:")
        for detail in report.failing_test_details:
            lines.append("")
            for dline in detail.splitlines():
                lines.append(f"    {dline}")
    lines.append("")

    # Evidence
    lines.append(_section("EVIDENCE DISCOVERED"))
    if report.evidence:
        for i, ev in enumerate(report.evidence, start=1):
            lines.append(f"  [{i}] {ev.category.upper()} — {ev.location}")
            lines.append(f"      {ev.description}")
            if ev.snippet:
                lines.append("")
                for sline in ev.snippet.splitlines():
                    lines.append(f"      {sline}")
            lines.append("")
    else:
        lines.append("  (no evidence collected)")
    lines.append("")

    # Root cause
    lines.append(_section("LIKELY ROOT CAUSE"))
    if report.root_cause:
        rc = report.root_cause
        lines.append(f"  Summary    : {rc.summary}")
        lines.append(f"  Location   : {rc.file}  (line {rc.line_range})")
        lines.append(f"  Confidence : {rc.confidence.upper()}")
        lines.append("")
        lines.append("  Explanation:")
        for eline in rc.explanation.splitlines():
            lines.append(f"    {eline}")
        lines.append("")
        lines.append("  Faulty code:")
        for cline in rc.faulty_code.splitlines():
            lines.append(f"    {cline}")
        lines.append("")
        lines.append("  Suggested fix (not yet applied):")
        for fline in rc.suggested_fix.splitlines():
            lines.append(f"    {fline}")
    else:
        lines.append("  (root cause could not be determined)")
    lines.append("")

    # Suggested next steps
    lines.append(_section("SUGGESTED NEXT STEPS"))
    for i, step in enumerate(report.suggested_next_steps, start=1):
        lines.append(f"  {i}. {step}")
    lines.append("")

    # Investigation notes
    if report.investigation_notes:
        lines.append(_section("INVESTIGATION NOTES"))
        for note in report.investigation_notes:
            lines.append(f"  - {note}")
        lines.append("")

    lines.append(_THICK)
    lines.append("  End of Report")
    lines.append(_THICK)

    return "\n".join(lines)
