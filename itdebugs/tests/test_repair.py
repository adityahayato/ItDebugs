"""
itdebugs/tests/test_repair.py
==============================
Tests for the ItDebugs repair loop (Milestone 4).

Coverage
--------
PatchGenerator
  - generates a diff for a known root cause
  - produces a correct one-line replacement
  - handles missing faulty_code gracefully
  - handles wrong line range gracefully
  - handles unreadable files gracefully

PatchApplicator
  - creates a backup before writing
  - applies a valid patch correctly
  - restores backup on demand
  - rejects an out-of-range line
  - rejects when the original line has changed
  - cleanup_backups removes .bak files

RepairLoop
  - run() returns RepairResult
  - run() sets all_green=True when no failures
  - run() applies the demo fix when approval_fn returns True
  - run() does NOT modify files when approval_fn returns False
  - run() rolls back when the patch does not fix the tests
  - run() stops at max_iterations
  - demo is fully green after a successful repair

CLI
  - --repair flag exits 0 when fix is accepted and tests pass
  - --repair flag exits 1 when approval is declined
  - --max-iterations is forwarded correctly

The demo intentional bug is restored to its original state after every
test that modifies it, even on failure (via fixture teardown).
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

import pytest

# Ensure the project root is importable
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from itdebugs.engine.reporter import RootCauseHypothesis
from itdebugs.engine.test_runner import run_tests
from itdebugs.patcher import ApplyResult, PatchApplicator, PatchGenerator, ProposedPatch
from itdebugs.repair_loop import IterationResult, RepairLoop, RepairResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEMO_REPO = str(Path(__file__).resolve().parent.parent.parent / "demo" / "buggy-project")
MANAGER_REL = str(Path("task_manager") / "manager.py")
MANAGER_ABS = Path(DEMO_REPO) / MANAGER_REL

# The exact buggy line (index 0-based = 70, 1-based = 71)
_BUGGY_LINE = 'return [t for t in self._tasks if t.status != "complete"]'
_FIXED_LINE  = 'return [t for t in self._tasks if t.status != "completed"]'

# Hypothesis that reflects the actual root cause found by the engine
_HYPOTHESIS = RootCauseHypothesis(
    summary='`get_pending_tasks()` uses "complete" instead of "completed"',
    file=MANAGER_REL,
    line_range="71",
    explanation='The filter compares against "complete" instead of "completed".',
    confidence="high",
    faulty_code=_BUGGY_LINE.strip(),
    suggested_fix=(
        'Change `!= "complete"` to `!= "completed"` on line 71 of '
        '`task_manager/manager.py`.'
    ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def demo_repo_copy(tmp_path: Path) -> Path:
    """
    Create a fresh copy of the demo repository in a temp directory.
    The original demo repository is never touched by tests using this fixture.
    """
    dest = tmp_path / "buggy-project"
    shutil.copytree(DEMO_REPO, dest)
    return dest


@pytest.fixture(autouse=True)
def ensure_demo_bug_intact():
    """
    Safety net: verify (and restore if necessary) the demo bug is present
    before and after every test in this module.
    """
    _assert_bug_present()
    yield
    # Restore if a test forgot to clean up
    content = MANAGER_ABS.read_text(encoding="utf-8")
    if _BUGGY_LINE.strip() not in content:
        _restore_demo_bug()


def _assert_bug_present():
    content = MANAGER_ABS.read_text(encoding="utf-8")
    assert _BUGGY_LINE.strip() in content, (
        "Demo bug has been modified before the test ran! "
        "This should never happen — check fixture teardown."
    )


def _restore_demo_bug():
    """Restore the buggy line in manager.py."""
    content = MANAGER_ABS.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    idx = 70  # 0-based = line 71
    eol = "\n"
    if lines[idx].endswith("\r\n"):
        eol = "\r\n"
    lines[idx] = _BUGGY_LINE + eol
    MANAGER_ABS.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# PatchGenerator
# ---------------------------------------------------------------------------

class TestPatchGenerator:

    def test_generates_patch_for_demo_hypothesis(self):
        gen = PatchGenerator()
        patch = gen.generate(DEMO_REPO, _HYPOTHESIS)
        assert patch is not None
        assert patch.file_path.endswith("manager.py")

    def test_patch_is_applicable(self):
        gen = PatchGenerator()
        patch = gen.generate(DEMO_REPO, _HYPOTHESIS)
        assert patch.can_apply, (
            f"Patch not applicable: {patch.generation_note}"
        )

    def test_patch_targets_line_71(self):
        gen = PatchGenerator()
        patch = gen.generate(DEMO_REPO, _HYPOTHESIS)
        assert patch.target_line == 71

    def test_patch_replaces_correct_string(self):
        gen = PatchGenerator()
        patch = gen.generate(DEMO_REPO, _HYPOTHESIS)
        assert '"complete"' in patch.original_line
        assert '"completed"' in patch.replacement_line

    def test_diff_text_contains_minus_line(self):
        gen = PatchGenerator()
        patch = gen.generate(DEMO_REPO, _HYPOTHESIS)
        assert any(l.startswith("-") for l in patch.diff_text.splitlines())

    def test_diff_text_contains_plus_line(self):
        gen = PatchGenerator()
        patch = gen.generate(DEMO_REPO, _HYPOTHESIS)
        assert any(l.startswith("+") for l in patch.diff_text.splitlines())

    def test_diff_shows_file_path(self):
        gen = PatchGenerator()
        patch = gen.generate(DEMO_REPO, _HYPOTHESIS)
        assert "manager.py" in patch.diff_text

    def test_unpatchable_for_nonexistent_file(self):
        hyp = RootCauseHypothesis(
            summary="test",
            file="nonexistent/file.py",
            line_range="5",
            explanation="x",
            confidence="low",
            faulty_code='x = "wrong"',
            suggested_fix='change "wrong" to "right"',
        )
        gen = PatchGenerator()
        patch = gen.generate(DEMO_REPO, hyp)
        assert not patch.can_apply

    def test_unpatchable_when_no_faulty_code(self):
        hyp = RootCauseHypothesis(
            summary="test",
            file=MANAGER_REL,
            line_range="71",
            explanation="x",
            confidence="low",
            faulty_code="",
            suggested_fix="",
        )
        gen = PatchGenerator()
        patch = gen.generate(DEMO_REPO, hyp)
        # Without faulty code, can_apply may be False
        # (acceptable — no crash is the key requirement)
        assert isinstance(patch.can_apply, bool)

    def test_invalid_line_range_does_not_crash(self):
        hyp = RootCauseHypothesis(
            summary="test",
            file=MANAGER_REL,
            line_range="not-a-number",
            explanation="x",
            confidence="low",
            faulty_code="some code",
            suggested_fix="fix it",
        )
        gen = PatchGenerator()
        patch = gen.generate(DEMO_REPO, hyp)
        assert isinstance(patch, ProposedPatch)

    def test_patch_on_temp_copy(self, demo_repo_copy):
        gen = PatchGenerator()
        hyp = RootCauseHypothesis(
            summary="test",
            file=MANAGER_REL,
            line_range="71",
            explanation="filter bug",
            confidence="high",
            faulty_code=_BUGGY_LINE.strip(),
            suggested_fix='Change != "complete" to != "completed".',
        )
        patch = gen.generate(str(demo_repo_copy), hyp)
        assert patch.can_apply
        assert patch.target_line == 71


# ---------------------------------------------------------------------------
# PatchApplicator
# ---------------------------------------------------------------------------

class TestPatchApplicator:

    def test_apply_creates_backup(self, demo_repo_copy):
        gen = PatchGenerator()
        hyp = _hypothesis_for(str(demo_repo_copy))
        patch = gen.generate(str(demo_repo_copy), hyp)
        assert patch.can_apply

        app = PatchApplicator(str(demo_repo_copy))
        result = app.apply(patch)
        assert result.success, result.message

        bak = Path(demo_repo_copy) / (MANAGER_REL + ".bak")
        assert bak.exists(), "Backup file was not created"

    def test_apply_writes_correct_line(self, demo_repo_copy):
        gen = PatchGenerator()
        hyp = _hypothesis_for(str(demo_repo_copy))
        patch = gen.generate(str(demo_repo_copy), hyp)
        assert patch.can_apply

        app = PatchApplicator(str(demo_repo_copy))
        result = app.apply(patch)
        assert result.success, result.message

        lines = (Path(demo_repo_copy) / MANAGER_REL).read_text(encoding="utf-8").splitlines()
        assert '"completed"' in lines[70]
        assert '"complete"' not in lines[70].replace('"completed"', '')

    def test_restore_reverts_change(self, demo_repo_copy):
        gen = PatchGenerator()
        hyp = _hypothesis_for(str(demo_repo_copy))
        patch = gen.generate(str(demo_repo_copy), hyp)
        app = PatchApplicator(str(demo_repo_copy))
        app.apply(patch)

        messages = app.restore(MANAGER_REL)
        assert any("Restored" in m for m in messages)

        # Line 71 should be back to buggy version
        lines = (Path(demo_repo_copy) / MANAGER_REL).read_text(encoding="utf-8").splitlines()
        assert '"complete"' in lines[70]
        assert '"completed"' not in lines[70]

    def test_unapplicable_patch_returns_failure(self, demo_repo_copy):
        patch = ProposedPatch(
            file_path=MANAGER_REL,
            target_line=71,
            original_line="",
            replacement_line="",
            diff_text="",
            hypothesis=_HYPOTHESIS,
            can_apply=False,
        )
        app = PatchApplicator(str(demo_repo_copy))
        result = app.apply(patch)
        assert not result.success

    def test_out_of_range_line_returns_failure(self, demo_repo_copy):
        gen = PatchGenerator()
        hyp = _hypothesis_for(str(demo_repo_copy))
        patch = gen.generate(str(demo_repo_copy), hyp)
        assert patch.can_apply

        # Tamper with the line number to be out of range
        bad_patch = ProposedPatch(
            file_path=patch.file_path,
            target_line=99999,
            original_line=patch.original_line,
            replacement_line=patch.replacement_line,
            diff_text=patch.diff_text,
            hypothesis=patch.hypothesis,
            can_apply=True,
        )
        app = PatchApplicator(str(demo_repo_copy))
        result = app.apply(bad_patch)
        assert not result.success
        assert "out of range" in result.message.lower()

    def test_changed_line_returns_failure(self, demo_repo_copy):
        gen = PatchGenerator()
        hyp = _hypothesis_for(str(demo_repo_copy))
        patch = gen.generate(str(demo_repo_copy), hyp)

        # Simulate someone having edited the file between investigation and patch
        file_path = Path(demo_repo_copy) / MANAGER_REL
        content = file_path.read_text(encoding="utf-8")
        modified = content.replace(
            '"complete"',
            '"already_different"',
        )
        file_path.write_text(modified, encoding="utf-8")

        app = PatchApplicator(str(demo_repo_copy))
        result = app.apply(patch)
        assert not result.success
        assert "changed" in result.message.lower() or "expected" in result.message.lower()

    def test_cleanup_backups_removes_bak_files(self, demo_repo_copy):
        gen = PatchGenerator()
        hyp = _hypothesis_for(str(demo_repo_copy))
        patch = gen.generate(str(demo_repo_copy), hyp)
        app = PatchApplicator(str(demo_repo_copy))
        result = app.apply(patch)
        assert result.success

        bak = Path(demo_repo_copy) / (MANAGER_REL + ".bak")
        assert bak.exists()

        app.cleanup_backups()
        assert not bak.exists()


# ---------------------------------------------------------------------------
# RepairLoop
# ---------------------------------------------------------------------------

class TestRepairLoop:

    def test_returns_repair_result(self, demo_repo_copy):
        loop = RepairLoop(
            repo_path=str(demo_repo_copy),
            approval_fn=lambda p: False,   # decline — no modification
        )
        result = loop.run()
        assert isinstance(result, RepairResult)

    def test_all_green_when_no_failures(self, tmp_path):
        """A repo with no tests / no failures should exit immediately as green."""
        # Create a trivially clean repo with one passing test
        (tmp_path / "test_ok.py").write_text(
            "def test_always_passes(): assert True\n"
        )
        loop = RepairLoop(
            repo_path=str(tmp_path),
            approval_fn=lambda p: True,
        )
        result = loop.run()
        assert result.all_green
        assert result.final_failures == 0

    def test_decline_does_not_modify_files(self, demo_repo_copy):
        loop = RepairLoop(
            repo_path=str(demo_repo_copy),
            approval_fn=lambda p: False,  # always decline
        )
        result = loop.run()

        # File must be unchanged
        content = (Path(demo_repo_copy) / MANAGER_REL).read_text(encoding="utf-8")
        assert _BUGGY_LINE.strip() in content

    def test_approved_repair_fixes_demo(self, demo_repo_copy):
        """Full happy-path: approve the patch and confirm all tests pass."""
        loop = RepairLoop(
            repo_path=str(demo_repo_copy),
            approval_fn=lambda p: True,  # always approve
            max_iterations=3,
        )
        result = loop.run()

        assert result.all_green, (
            f"Expected all_green=True but got {result.all_green}. "
            f"Iterations: {result.total_iterations}. "
            f"Final failures: {result.final_failures}. "
            f"Summary: {result.summary()}"
        )
        assert result.final_failures == 0

    def test_approved_repair_correct_final_count(self, demo_repo_copy):
        """After a successful repair the full suite shows 22 tests, 0 failing."""
        loop = RepairLoop(
            repo_path=str(demo_repo_copy),
            approval_fn=lambda p: True,
            max_iterations=3,
        )
        result = loop.run()

        # Verify by running the test suite directly on the (now-fixed) copy
        final_run = run_tests(str(demo_repo_copy), timeout=60)
        assert final_run.total == 22
        assert final_run.passed == 22
        assert final_run.failed == 0

    def test_iteration_result_outcome_is_fixed(self, demo_repo_copy):
        loop = RepairLoop(
            repo_path=str(demo_repo_copy),
            approval_fn=lambda p: True,
            max_iterations=3,
        )
        result = loop.run()
        fixed_iters = [
            it for it in result.iterations
            if it.outcome == IterationResult.FIXED
        ]
        assert len(fixed_iters) >= 1

    def test_max_iterations_respected(self, demo_repo_copy):
        """Setting max_iterations=0 means never attempt any repair."""
        loop = RepairLoop(
            repo_path=str(demo_repo_copy),
            approval_fn=lambda p: True,
            max_iterations=0,
        )
        result = loop.run()
        assert result.total_iterations == 0
        # Bug is still present
        content = (Path(demo_repo_copy) / MANAGER_REL).read_text(encoding="utf-8")
        assert _BUGGY_LINE.strip() in content

    def test_summary_contains_repo_path(self, demo_repo_copy):
        loop = RepairLoop(
            repo_path=str(demo_repo_copy),
            approval_fn=lambda p: False,
        )
        result = loop.run()
        assert str(demo_repo_copy) in result.summary()

    def test_initial_failure_count(self, demo_repo_copy):
        loop = RepairLoop(
            repo_path=str(demo_repo_copy),
            approval_fn=lambda p: False,
        )
        result = loop.run()
        assert result.initial_failures == 3

    def test_backup_removed_after_successful_repair(self, demo_repo_copy):
        loop = RepairLoop(
            repo_path=str(demo_repo_copy),
            approval_fn=lambda p: True,
            max_iterations=3,
        )
        loop.run()
        # No .bak file should remain after a clean repair
        bak = Path(demo_repo_copy) / (MANAGER_REL + ".bak")
        assert not bak.exists(), ".bak file was not cleaned up after repair"


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestCLIRepair:

    def test_repair_flag_exits_0_on_success(self, demo_repo_copy):
        """--repair should exit 0 when all tests pass after the fix."""
        from itdebugs.investigate import main
        rc = main([
            "--repo", str(demo_repo_copy),
            "--repair",
            "--max-iterations", "3",
        ])
        assert rc == 0

    def test_repair_flag_exits_1_when_declined(self, demo_repo_copy):
        """--repair should exit 1 (not all green) when developer declines."""
        # We test this by monkeypatching RepairLoop inside investigate
        import itdebugs.investigate as inv_mod
        import itdebugs.repair_loop as rl_mod

        original_init = rl_mod.RepairLoop.__init__

        def patched_init(self, *args, approval_fn=None, **kwargs):
            original_init(self, *args, approval_fn=lambda p: False, **kwargs)

        rl_mod.RepairLoop.__init__ = patched_init
        try:
            rc = inv_mod.main([
                "--repo", str(demo_repo_copy),
                "--repair",
                "--max-iterations", "1",
            ])
        finally:
            rl_mod.RepairLoop.__init__ = original_init

        assert rc == 1

    def test_max_iterations_default(self):
        from itdebugs.investigate import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["--repo", ".", "--repair"])
        assert args.max_iterations == 5

    def test_max_iterations_custom(self):
        from itdebugs.investigate import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "--repo", ".", "--repair", "--max-iterations", "7"
        ])
        assert args.max_iterations == 7


# ---------------------------------------------------------------------------
# Safety: demo bug is truly intact after all tests
# ---------------------------------------------------------------------------

def test_demo_bug_intact_after_all_tests():
    """Final sanity check that no test permanently modified the demo project."""
    content = MANAGER_ABS.read_text(encoding="utf-8")
    lines = content.splitlines()
    line71 = lines[70]
    assert '"complete"' in line71
    assert '"completed"' not in line71
    assert _BUGGY_LINE.strip() in content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hypothesis_for(repo_root: str) -> RootCauseHypothesis:
    """Return a RootCauseHypothesis pointing at the copy of manager.py."""
    return RootCauseHypothesis(
        summary='get_pending_tasks uses "complete" instead of "completed"',
        file=MANAGER_REL,
        line_range="71",
        explanation='Filter compares against "complete" not "completed".',
        confidence="high",
        faulty_code=_BUGGY_LINE.strip(),
        suggested_fix=(
            'Change != "complete" to != "completed" on line 71 '
            'of task_manager/manager.py.'
        ),
    )
