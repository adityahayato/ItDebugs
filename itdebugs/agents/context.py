"""
agents/context.py
=================
The shared investigation context object that flows through the agent pipeline.

Each agent reads from and writes to the context.  Using a single mutable
context object means:

  * Agents are decoupled — they depend on the context contract, not on each
    other's implementations.
  * The orchestrator can inspect intermediate state between any two agents.
  * Future parallel agents can be given read-only snapshots of the context
    and their results merged back by the orchestrator.

Only the Orchestrator constructs the InvestigationContext.  Agents receive
it as an argument to their ``run()`` method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Re-export engine types so agents only need one import
from itdebugs.engine.repo_scanner import RepoStructure
from itdebugs.engine.test_runner import TestRunSummary, TestResult
from itdebugs.engine.reporter import (
    EvidenceItem,
    RootCauseHypothesis,
    InvestigationReport,
)


@dataclass
class VerificationResult:
    """
    Output of the Verification Agent.

    Records whether the proposed root cause is consistent with the
    available evidence and test results, and whether any gaps remain.
    """
    consistent: bool                        # evidence supports root cause?
    confidence_assessment: str              # human-readable confidence judgement
    supporting_evidence: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class InvestigationContext:
    """
    Shared mutable context that travels through the agent pipeline.

    Fields are populated progressively as each agent runs:

    +-------------------+-----------------------------+
    | Field             | Set by                      |
    +===================+=============================+
    | repo_path         | Orchestrator (initial)      |
    | bug_description   | Orchestrator (initial)      |
    | test_timeout      | Orchestrator (initial)      |
    | repo_structure    | RepositoryAnalyst           |
    | test_run          | TestAnalyst                 |
    | failing_tests     | TestAnalyst                 |
    | keywords          | TestAnalyst                 |
    | relevant_files    | CodeAnalyst                 |
    | evidence          | EvidenceAgent               |
    | root_cause        | RootCauseAgent              |
    | verification      | VerificationAgent           |
    | report            | Orchestrator (final)        |
    | errors            | Any agent (on failure)      |
    +-------------------+-----------------------------+
    """

    # ── Input (set by Orchestrator before pipeline starts) ───────────────
    repo_path: str
    bug_description: str
    test_timeout: int = 60

    # ── Repository Analyst output ─────────────────────────────────────────
    repo_structure: Optional[RepoStructure] = None

    # ── Test Analyst output ───────────────────────────────────────────────
    test_run: Optional[TestRunSummary] = None
    failing_tests: List[TestResult] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

    # ── Code Analyst output ───────────────────────────────────────────────
    relevant_files: List[str] = field(default_factory=list)    # relative paths
    suspicious_locations: List[str] = field(default_factory=list)  # "file:line" strings

    # ── Evidence Agent output ─────────────────────────────────────────────
    evidence: List[EvidenceItem] = field(default_factory=list)

    # ── Root Cause Agent output ───────────────────────────────────────────
    root_cause: Optional[RootCauseHypothesis] = None

    # ── Verification Agent output ─────────────────────────────────────────
    verification: Optional[VerificationResult] = None

    # ── Final output (set by Orchestrator) ───────────────────────────────
    report: Optional[InvestigationReport] = None

    # ── Operational metadata ──────────────────────────────────────────────
    errors: List[str] = field(default_factory=list)
    agent_notes: List[str] = field(default_factory=list)  # informational messages

    # ── Convenience helpers ───────────────────────────────────────────────

    def add_error(self, agent_name: str, message: str) -> None:
        self.errors.append(f"[{agent_name}] {message}")

    def add_note(self, agent_name: str, message: str) -> None:
        self.agent_notes.append(f"[{agent_name}] {message}")

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def has_test_failures(self) -> bool:
        return bool(self.failing_tests)
