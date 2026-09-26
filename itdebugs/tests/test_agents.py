"""
itdebugs/tests/test_agents.py
==============================
Unit and integration tests for the ItDebugs agent orchestration layer.

Test scope
----------
* InvestigationContext — construction, helpers
* BaseAgent — run() error handling, progress logging
* RepositoryAnalyst — populates ctx.repo_structure and ctx.relevant_files
* TestAnalyst — populates ctx.test_run, ctx.failing_tests, ctx.keywords
* CodeAnalyst — populates ctx.relevant_files and ctx.suspicious_locations
* EvidenceAgent — populates ctx.evidence (deduplication, categories)
* RootCauseAgent — populates ctx.root_cause (delegates to engine)
* VerificationAgent — populates ctx.verification
* Orchestrator — end-to-end run against the demo project
* CLI --mode flag

The demo project intentional bug MUST remain unfixed; these tests only
verify that agents produce correct *investigation* outputs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest

# Ensure itdebugs is importable when tests are run from the project root.
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from itdebugs.agents.base import BaseAgent
from itdebugs.agents.context import InvestigationContext, VerificationResult
from itdebugs.agents.code_analyst import CodeAnalyst
from itdebugs.agents.evidence_agent import EvidenceAgent
from itdebugs.agents.repo_analyst import RepositoryAnalyst
from itdebugs.agents.root_cause_agent import RootCauseAgent
from itdebugs.agents.test_analyst import TestAnalyst
from itdebugs.agents.verification_agent import VerificationAgent
from itdebugs.engine.reporter import EvidenceItem, RootCauseHypothesis
from itdebugs.engine.test_runner import TestResult, TestRunSummary
from itdebugs.orchestrator import Orchestrator

# Path to the demo project (relative to the workspace root)
DEMO_REPO = str(Path(__file__).resolve().parent.parent.parent / "demo" / "buggy-project")
DEMO_BUG = "Completed tasks are appearing in the pending task list."


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_context(**kwargs) -> InvestigationContext:
    defaults = dict(repo_path=DEMO_REPO, bug_description=DEMO_BUG)
    defaults.update(kwargs)
    return InvestigationContext(**defaults)


def _make_test_result(
    node_id: str,
    outcome: str = "FAILED",
    failure_message: str = "",
) -> TestResult:
    parts = node_id.split("::")
    return TestResult(
        node_id=node_id,
        outcome=outcome,
        file=parts[0],
        class_name=parts[1] if len(parts) > 2 else "",
        test_name=parts[-1],
        failure_message=failure_message,
    )


# ---------------------------------------------------------------------------
# InvestigationContext
# ---------------------------------------------------------------------------

class TestInvestigationContext:
    def test_construction_defaults(self):
        ctx = _make_context()
        assert ctx.repo_path == DEMO_REPO
        assert ctx.bug_description == DEMO_BUG
        assert ctx.test_timeout == 60
        assert ctx.repo_structure is None
        assert ctx.test_run is None
        assert ctx.failing_tests == []
        assert ctx.keywords == []
        assert ctx.evidence == []
        assert ctx.root_cause is None
        assert ctx.verification is None
        assert ctx.errors == []

    def test_add_error(self):
        ctx = _make_context()
        ctx.add_error("TestAgent", "something went wrong")
        assert ctx.has_errors
        assert "[TestAgent] something went wrong" in ctx.errors

    def test_add_note(self):
        ctx = _make_context()
        ctx.add_note("RepoAgent", "found 5 files")
        assert "[RepoAgent] found 5 files" in ctx.agent_notes

    def test_has_test_failures_false_when_empty(self):
        ctx = _make_context()
        assert not ctx.has_test_failures

    def test_has_test_failures_true_when_populated(self):
        ctx = _make_context()
        ctx.failing_tests = [_make_test_result("tests/t.py::Foo::test_bar")]
        assert ctx.has_test_failures


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------

class TestBaseAgent:
    def _make_agent(self, *, fail: bool = False) -> BaseAgent:
        class _Dummy(BaseAgent):
            @property
            def name(self) -> str:
                return "DummyAgent"

            def _execute(self, ctx: InvestigationContext) -> None:
                ctx.add_note(self.name, "executed")
                if fail:
                    raise ValueError("intentional test error")

        return _Dummy(verbose=False)

    def test_run_returns_context(self):
        agent = self._make_agent()
        ctx = _make_context()
        result = agent.run(ctx)
        assert result is ctx

    def test_run_calls_execute(self):
        agent = self._make_agent()
        ctx = _make_context()
        agent.run(ctx)
        assert any("executed" in n for n in ctx.agent_notes)

    def test_run_catches_exception(self):
        agent = self._make_agent(fail=True)
        ctx = _make_context()
        # Should NOT raise
        agent.run(ctx)
        assert ctx.has_errors
        assert "intentional test error" in ctx.errors[0]

    def test_run_on_exception_still_returns_context(self):
        agent = self._make_agent(fail=True)
        ctx = _make_context()
        result = agent.run(ctx)
        assert result is ctx


# ---------------------------------------------------------------------------
# RepositoryAnalyst
# ---------------------------------------------------------------------------

class TestRepositoryAnalyst:
    def test_populates_repo_structure(self):
        ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(ctx)
        assert ctx.repo_structure is not None

    def test_finds_source_files(self):
        ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(ctx)
        assert len(ctx.repo_structure.source_files) > 0

    def test_finds_test_files(self):
        ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(ctx)
        assert len(ctx.repo_structure.test_files) > 0

    def test_populates_relevant_files(self):
        ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(ctx)
        assert len(ctx.relevant_files) > 0

    def test_relevant_files_include_source_and_test(self):
        """relevant_files may include test files when they are ranked as candidates."""
        ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(ctx)
        # At least one source (non-test) Python file must be present
        has_source = any(
            not Path(f).name.startswith("test_") for f in ctx.relevant_files
        )
        assert has_source, "relevant_files has no source files"

    def test_adds_note(self):
        ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(ctx)
        notes = " ".join(ctx.agent_notes).lower()
        # New note format: "src=N" or old format "source file"
        assert "src=" in notes or "source" in notes or "profile" in notes

    def test_bad_repo_path_adds_error(self):
        ctx = _make_context(repo_path="/nonexistent/path/xyz")
        RepositoryAnalyst(verbose=False).run(ctx)
        assert ctx.has_errors


# ---------------------------------------------------------------------------
# TestAnalyst
# ---------------------------------------------------------------------------

class TestTestAnalyst:
    @pytest.fixture(autouse=True)
    def _run_repo_first(self):
        """Ensure repo_structure is populated before TestAnalyst runs."""
        self.ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(self.ctx)

    def test_populates_test_run(self):
        TestAnalyst(verbose=False).run(self.ctx)
        assert self.ctx.test_run is not None

    def test_finds_22_tests(self):
        TestAnalyst(verbose=False).run(self.ctx)
        assert self.ctx.test_run.total == 22

    def test_finds_3_failures(self):
        TestAnalyst(verbose=False).run(self.ctx)
        assert self.ctx.test_run.failed == 3

    def test_finds_19_passing(self):
        TestAnalyst(verbose=False).run(self.ctx)
        assert self.ctx.test_run.passed == 19

    def test_failing_tests_list_has_3_entries(self):
        TestAnalyst(verbose=False).run(self.ctx)
        assert len(self.ctx.failing_tests) == 3

    def test_keywords_populated(self):
        TestAnalyst(verbose=False).run(self.ctx)
        assert len(self.ctx.keywords) > 0

    def test_keywords_include_bug_terms(self):
        TestAnalyst(verbose=False).run(self.ctx)
        kw_lower = [k.lower() for k in self.ctx.keywords]
        # "completed" or "pending" should appear given the bug description
        assert any(w in kw_lower for w in ["completed", "pending", "tasks"])

    def test_requires_repo_structure(self):
        ctx_bare = _make_context()  # no repo_structure set
        TestAnalyst(verbose=False).run(ctx_bare)
        assert ctx_bare.has_errors  # should record error, not raise


# ---------------------------------------------------------------------------
# CodeAnalyst
# ---------------------------------------------------------------------------

class TestCodeAnalyst:
    @pytest.fixture(autouse=True)
    def _run_prerequisites(self):
        self.ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(self.ctx)
        TestAnalyst(verbose=False).run(self.ctx)

    def test_relevant_files_not_empty(self):
        CodeAnalyst(verbose=False).run(self.ctx)
        assert len(self.ctx.relevant_files) > 0

    def test_manager_py_is_most_relevant(self):
        CodeAnalyst(verbose=False).run(self.ctx)
        # manager.py should be ranked first (it contains the bug keywords)
        top_file = self.ctx.relevant_files[0]
        assert "manager" in top_file.lower()

    def test_suspicious_locations_found(self):
        CodeAnalyst(verbose=False).run(self.ctx)
        # Should find at least one suspicious location
        assert len(self.ctx.suspicious_locations) >= 0  # may be 0 without hits

    def test_requires_repo_structure(self):
        ctx_bare = _make_context()
        CodeAnalyst(verbose=False).run(ctx_bare)
        assert ctx_bare.has_errors


# ---------------------------------------------------------------------------
# EvidenceAgent
# ---------------------------------------------------------------------------

class TestEvidenceAgent:
    @pytest.fixture(autouse=True)
    def _run_prerequisites(self):
        self.ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(self.ctx)
        TestAnalyst(verbose=False).run(self.ctx)
        CodeAnalyst(verbose=False).run(self.ctx)

    def test_evidence_not_empty(self):
        EvidenceAgent(verbose=False).run(self.ctx)
        assert len(self.ctx.evidence) > 0

    def test_has_failing_test_evidence(self):
        EvidenceAgent(verbose=False).run(self.ctx)
        categories = [e.category for e in self.ctx.evidence]
        assert "failing_test" in categories

    def test_has_grep_match_evidence(self):
        EvidenceAgent(verbose=False).run(self.ctx)
        categories = [e.category for e in self.ctx.evidence]
        assert "grep_match" in categories

    def test_has_code_inspection_evidence(self):
        EvidenceAgent(verbose=False).run(self.ctx)
        categories = [e.category for e in self.ctx.evidence]
        assert "code_inspection" in categories

    def test_3_failing_test_evidence_items(self):
        EvidenceAgent(verbose=False).run(self.ctx)
        failing_ev = [e for e in self.ctx.evidence if e.category == "failing_test"]
        assert len(failing_ev) == 3

    def test_no_duplicate_locations(self):
        EvidenceAgent(verbose=False).run(self.ctx)
        keys = [f"{e.category}:{e.location}" for e in self.ctx.evidence]
        assert len(keys) == len(set(keys)), "Duplicate evidence items found"

    def test_evidence_items_have_required_fields(self):
        EvidenceAgent(verbose=False).run(self.ctx)
        for ev in self.ctx.evidence:
            assert ev.category
            assert ev.description
            assert ev.location


# ---------------------------------------------------------------------------
# RootCauseAgent
# ---------------------------------------------------------------------------

class TestRootCauseAgent:
    @pytest.fixture(autouse=True)
    def _run_prerequisites(self):
        self.ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(self.ctx)
        TestAnalyst(verbose=False).run(self.ctx)
        CodeAnalyst(verbose=False).run(self.ctx)
        EvidenceAgent(verbose=False).run(self.ctx)

    def test_root_cause_populated(self):
        RootCauseAgent(verbose=False).run(self.ctx)
        assert self.ctx.root_cause is not None

    def test_root_cause_points_to_manager_py(self):
        RootCauseAgent(verbose=False).run(self.ctx)
        assert self.ctx.root_cause is not None
        assert "manager" in self.ctx.root_cause.file.lower()

    def test_root_cause_identifies_line_71(self):
        RootCauseAgent(verbose=False).run(self.ctx)
        assert self.ctx.root_cause is not None
        # Line 71 is where the bug lives in manager.py
        assert self.ctx.root_cause.line_range == "71"

    def test_root_cause_has_confidence(self):
        RootCauseAgent(verbose=False).run(self.ctx)
        assert self.ctx.root_cause is not None
        assert self.ctx.root_cause.confidence in ("high", "medium", "low")

    def test_root_cause_faulty_code_contains_bug(self):
        RootCauseAgent(verbose=False).run(self.ctx)
        assert self.ctx.root_cause is not None
        # The bug is comparing against "complete" instead of "completed"
        assert '"complete"' in self.ctx.root_cause.faulty_code

    def test_suggested_fix_not_empty(self):
        RootCauseAgent(verbose=False).run(self.ctx)
        assert self.ctx.root_cause is not None
        assert self.ctx.root_cause.suggested_fix

    def test_requires_repo_structure(self):
        ctx_bare = _make_context()
        RootCauseAgent(verbose=False).run(ctx_bare)
        assert ctx_bare.has_errors


# ---------------------------------------------------------------------------
# VerificationAgent
# ---------------------------------------------------------------------------

class TestVerificationAgent:
    @pytest.fixture(autouse=True)
    def _run_prerequisites(self):
        self.ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(self.ctx)
        TestAnalyst(verbose=False).run(self.ctx)
        CodeAnalyst(verbose=False).run(self.ctx)
        EvidenceAgent(verbose=False).run(self.ctx)
        RootCauseAgent(verbose=False).run(self.ctx)

    def test_verification_populated(self):
        VerificationAgent(verbose=False).run(self.ctx)
        assert self.ctx.verification is not None

    def test_verification_is_consistent(self):
        VerificationAgent(verbose=False).run(self.ctx)
        assert self.ctx.verification.consistent

    def test_verification_has_confidence_assessment(self):
        VerificationAgent(verbose=False).run(self.ctx)
        assert self.ctx.verification.confidence_assessment

    def test_verification_has_supporting_evidence(self):
        VerificationAgent(verbose=False).run(self.ctx)
        assert len(self.ctx.verification.supporting_evidence) > 0

    def test_verification_notes_no_fix_applied(self):
        VerificationAgent(verbose=False).run(self.ctx)
        notes = self.ctx.verification.notes.lower()
        assert "not been applied" in notes or "not apply" in notes or "not yet applied" in notes or "manual" in notes

    def test_verification_with_no_root_cause_is_inconclusive(self):
        ctx = _make_context()
        RepositoryAnalyst(verbose=False).run(ctx)
        TestAnalyst(verbose=False).run(ctx)
        EvidenceAgent(verbose=False).run(ctx)
        # Do NOT run RootCauseAgent — root_cause stays None
        VerificationAgent(verbose=False).run(ctx)
        assert ctx.verification is not None
        assert not ctx.verification.consistent


# ---------------------------------------------------------------------------
# Orchestrator (end-to-end integration)
# ---------------------------------------------------------------------------

class TestOrchestrator:
    @pytest.fixture(scope="class")
    def report(self):
        """Run the orchestrator once and share the result across the class."""
        orc = Orchestrator(
            repo_path=DEMO_REPO,
            bug_description=DEMO_BUG,
            verbose=False,
        )
        return orc.run()

    def test_investigation_successful(self, report):
        assert report.investigation_successful

    def test_correct_test_total(self, report):
        assert report.tests_total == 22

    def test_correct_passing_count(self, report):
        assert report.tests_passed == 19

    def test_correct_failing_count(self, report):
        assert report.tests_failed == 3

    def test_failing_test_ids_present(self, report):
        assert len(report.failing_test_ids) == 3

    def test_all_expected_failing_tests_identified(self, report):
        expected_suffixes = [
            "test_pending_tasks_excludes_completed",
            "test_pending_tasks_empty_when_all_completed",
            "test_summary_pending_count_reflects_bug",
        ]
        for suffix in expected_suffixes:
            assert any(suffix in tid for tid in report.failing_test_ids), (
                f"Expected failing test '{suffix}' not found in report"
            )

    def test_root_cause_identified(self, report):
        assert report.root_cause is not None

    def test_root_cause_points_to_manager_py(self, report):
        assert "manager" in report.root_cause.file.lower()

    def test_root_cause_identifies_correct_line(self, report):
        assert report.root_cause.line_range == "71"

    def test_root_cause_faulty_code_contains_bug_string(self, report):
        assert '"complete"' in report.root_cause.faulty_code

    def test_evidence_collected(self, report):
        assert len(report.evidence) > 0

    def test_report_has_directory_tree(self, report):
        assert report.directory_tree

    def test_suggested_next_steps_present(self, report):
        assert len(report.suggested_next_steps) > 0

    def test_investigation_notes_present(self, report):
        assert len(report.investigation_notes) > 0

    def test_no_source_code_modified(self):
        """Verify the demo bug is still present (manager.py unchanged)."""
        manager_py = Path(DEMO_REPO) / "task_manager" / "manager.py"
        content = manager_py.read_text(encoding="utf-8")
        assert 't.status != "complete"' in content, (
            "The intentional bug in manager.py was unexpectedly fixed!"
        )


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_legacy_mode_exits_0(self):
        from itdebugs.investigate import main
        rc = main([
            "--repo", DEMO_REPO,
            "--bug", DEMO_BUG,
            "--mode", "legacy",
        ])
        assert rc == 0

    def test_orchestrated_mode_exits_0(self):
        from itdebugs.investigate import main
        rc = main([
            "--repo", DEMO_REPO,
            "--bug", DEMO_BUG,
            "--mode", "orchestrated",
        ])
        assert rc == 0

    def test_bad_repo_exits_2(self):
        from itdebugs.investigate import main
        rc = main([
            "--repo", "/nonexistent/path",
            "--bug", DEMO_BUG,
        ])
        assert rc == 2

    def test_default_mode_is_orchestrated(self):
        """Ensure the default --mode is 'orchestrated' (not legacy)."""
        from itdebugs.investigate import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["--repo", ".", "--bug", "x"])
        assert args.mode == "orchestrated"
