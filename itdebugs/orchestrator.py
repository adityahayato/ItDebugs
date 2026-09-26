"""
itdebugs/orchestrator.py
========================
Central investigation orchestrator for ItDebugs.

The orchestrator coordinates the six specialized agents in sequence,
provides visible progress output, and assembles the final
:class:`InvestigationReport` from the completed context.

Workflow
--------
Bug Report
    |
    v
[1] Repository Analyst  -- scan filesystem
    |
    v
[2] Test Analyst        -- run tests, find failures
    |
    v
[3] Code Analyst        -- identify relevant code locations
    |
    v
[4] Evidence Agent      -- aggregate all evidence
    |
    v
[5] Root Cause Agent    -- hypothesise root cause
    |
    v
[6] Verification Agent  -- verify consistency
    |
    v
Final InvestigationReport

Parallel execution readiness
-----------------------------
The pipeline is sequential today.  Steps 3 (Code Analyst) and parts of
step 2 (Test Analyst) are logically independent after step 1 completes.
The orchestrator passes the SAME InvestigationContext to all agents, so
parallelisation requires only:
  1. Creating a read-only snapshot of the context before dispatching
     independent agents.
  2. Merging their outputs back (lists are extended, singletons use the
     last non-None value).

Relationship to legacy Investigator
-------------------------------------
The legacy ``itdebugs.engine.investigator.Investigator`` class remains
unchanged.  The CLI selects between them via --mode (default: orchestrated).
Both produce the same ``InvestigationReport`` format.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from itdebugs.agents.context import InvestigationContext
from itdebugs.agents.repo_analyst import RepositoryAnalyst
from itdebugs.agents.test_analyst import TestAnalyst
from itdebugs.agents.code_analyst import CodeAnalyst
from itdebugs.agents.evidence_agent import EvidenceAgent
from itdebugs.agents.root_cause_agent import RootCauseAgent
from itdebugs.agents.verification_agent import VerificationAgent
from itdebugs.engine.reporter import InvestigationReport, RootCauseHypothesis


_BANNER_WIDTH = 60


def _banner(text: str) -> str:
    """Format a visible section header for terminal output."""
    bar = "-" * _BANNER_WIDTH
    return f"\n{bar}\n  {text}\n{bar}"


class Orchestrator:
    """
    Coordinates all ItDebugs agents and assembles the final report.

    Parameters
    ----------
    repo_path:
        Path to the repository root to investigate.
    bug_description:
        Natural-language description of the reported bug.
    test_timeout:
        Wall-clock seconds before the pytest subprocess is killed.
    verbose:
        When True, each agent's step-by-step progress is printed to stderr.
    """

    def __init__(
        self,
        repo_path: str,
        bug_description: str,
        test_timeout: int = 60,
        verbose: bool = False,
    ) -> None:
        self.repo_path = str(Path(repo_path).resolve())
        self.bug_description = bug_description
        self.test_timeout = test_timeout
        self.verbose = verbose

    def _log(self, msg: str) -> None:
        print(msg, file=sys.stderr)

    def _step(self, label: str) -> None:
        """Print a visible agent-step banner to stderr."""
        self._log(_banner(label))

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> InvestigationReport:
        """
        Execute the full agent pipeline and return the investigation report.
        Never raises — errors from individual agents are captured in the
        context and surfaced in the report's investigation_notes.
        """
        self._log(f"\n{'=' * _BANNER_WIDTH}")
        self._log("  ItDebugs - Orchestrated Investigation")
        self._log(f"{'=' * _BANNER_WIDTH}")
        self._log(f"  Repository : {self.repo_path}")
        self._log(f"  Bug report : {self.bug_description}")
        self._log(f"{'=' * _BANNER_WIDTH}")

        # Build the shared context
        ctx = InvestigationContext(
            repo_path=self.repo_path,
            bug_description=self.bug_description,
            test_timeout=self.test_timeout,
        )

        # Instantiate agents — all share verbose flag
        agents = [
            RepositoryAnalyst(verbose=self.verbose),
            TestAnalyst(verbose=self.verbose),
            CodeAnalyst(verbose=self.verbose),
            EvidenceAgent(verbose=self.verbose),
            RootCauseAgent(verbose=self.verbose),
            VerificationAgent(verbose=self.verbose),
        ]

        # ── Sequential pipeline ───────────────────────────────────────────
        for agent in agents:
            self._step(f"Agent: {agent.name}")
            agent.run(ctx)
            # Surface any errors immediately
            if ctx.errors:
                latest_errors = [e for e in ctx.errors if f"[{agent.name}]" in e]
                for err in latest_errors:
                    self._log(f"  WARNING: {err}")

        self._step("Building Final Report")

        # ── Assemble the InvestigationReport ─────────────────────────────
        report = self._build_report(ctx)
        ctx.report = report

        self._log(f"\n{'=' * _BANNER_WIDTH}")
        self._log("  ItDebugs - Investigation Complete")
        self._log(f"{'=' * _BANNER_WIDTH}\n")

        return report

    # ------------------------------------------------------------------
    # Report assembly
    # ------------------------------------------------------------------

    def _build_report(self, ctx: InvestigationContext) -> InvestigationReport:
        """Convert the populated context into the canonical InvestigationReport."""

        # Collect all agent notes + errors for investigation_notes
        notes: List[str] = list(ctx.agent_notes)
        if ctx.errors:
            notes.extend([f"ERROR: {e}" for e in ctx.errors])

        # Add verification summary if available
        if ctx.verification:
            v = ctx.verification
            notes.append(
                f"Verification: {'CONSISTENT' if v.consistent else 'INCONSISTENT'} — "
                f"{v.confidence_assessment}"
            )
            if v.gaps:
                notes.append(f"Verification gaps: {'; '.join(v.gaps[:3])}")

        # Suggested next steps from root cause (or fallback)
        if ctx.root_cause:
            next_steps = [
                f"Inspect `{ctx.root_cause.file}` at line {ctx.root_cause.line_range}.",
                "Verify the string literal in the comparison matches the canonical "
                "status values used in the rest of the codebase.",
                "Write a minimal failing test that reproduces the bug in isolation.",
                "Apply the one-line fix and re-run the full test suite.",
                "Review any similar comparisons in the same class.",
            ]
        else:
            next_steps = [
                "Manually inspect the relevant source files.",
                "Focus on methods referenced by the failing tests.",
                "Check all string comparisons for typos or mismatched literals.",
            ]

        report = InvestigationReport(
            repo_path=self.repo_path,
            bug_description=self.bug_description,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            # Repository
            relevant_files=ctx.relevant_files,
            test_files=(
                [f.relative_path for f in ctx.repo_structure.test_files]
                if ctx.repo_structure else []
            ),
            directory_tree=(
                ctx.repo_structure.directory_tree if ctx.repo_structure else ""
            ),
            # Test results
            tests_total=ctx.test_run.total if ctx.test_run else 0,
            tests_passed=ctx.test_run.passed if ctx.test_run else 0,
            tests_failed=ctx.test_run.failed if ctx.test_run else 0,
            failing_test_ids=[t.node_id for t in ctx.failing_tests],
            failing_test_details=[
                f"{t.node_id}\n{t.failure_message}"
                for t in ctx.failing_tests
                if t.failure_message
            ],
            raw_test_output=ctx.test_run.raw_output if ctx.test_run else "",
            # Analysis
            evidence=ctx.evidence,
            root_cause=ctx.root_cause,
            # Outcome
            suggested_next_steps=next_steps,
            investigation_notes=notes,
            investigation_successful=not bool(ctx.errors) or ctx.root_cause is not None,
            error_message="; ".join(ctx.errors) if ctx.errors else "",
        )

        return report
