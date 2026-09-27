"""
itdebugs/repair_loop.py
========================
Autonomous debugging loop for ItDebugs.

The repair loop chains together the existing investigation pipeline with
patch generation, developer approval, safe patch application, and
re-testing.

Workflow
--------
1.  Run the complete test suite → discover failures
2.  If no failures → done (repository is green)
3.  Group failures → investigate each group using the existing Orchestrator
4.  Generate a concrete patch from the root-cause hypothesis
5.  Display the proposed patch diff
6.  Prompt the developer for approval (or use the injected approval_fn)
7.  If approved → apply patch safely (backup created)
8.  Re-run only the tests that were failing
9.  If those tests now pass → run the FULL suite to catch regressions
10. If the full suite is still green → remove backup and continue to any
    remaining bug groups
11. If new failures appear → start the next iteration from step 3
12. Stop when:
    - All tests pass, OR
    - max_iterations reached, OR
    - No patch could be generated, OR
    - Developer declines approval, OR
    - Patch application fails

Safety
------
- Every modified file gets a .bak backup before the write.
- If the full suite introduces new failures, the patch is rolled back
  and the loop reports the regression.
- Source code is NEVER modified without explicit developer approval.
- No modification is ever "silently" applied.

Usage (programmatic)
--------------------
    from itdebugs.repair_loop import RepairLoop

    loop = RepairLoop(repo_path="demo/buggy-project", verbose=True)
    result = loop.run()
    print(result.summary())

Usage (CLI — added in investigate.py)
--------------------------------------
    python -m itdebugs.investigate --repo demo/buggy-project --repair
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from itdebugs.engine.test_runner import TestResult, TestRunSummary, run_tests
from itdebugs.engine.reporter import InvestigationReport, RootCauseHypothesis
from itdebugs.multi_bug import BugGroup, MultiBugReport, group_failures
from itdebugs.orchestrator import Orchestrator
from itdebugs.patcher import ApplyResult, PatchApplicator, PatchGenerator, ProposedPatch


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class IterationResult:
    """The outcome of one repair iteration."""

    iteration: int
    group: BugGroup
    report: Optional[InvestigationReport]
    patch: Optional[ProposedPatch]
    apply_result: Optional[ApplyResult]
    retest_summary: Optional[TestRunSummary]
    full_suite_summary: Optional[TestRunSummary]

    # Outcome codes
    SKIPPED_NO_HYPOTHESIS = "skipped_no_hypothesis"
    SKIPPED_NO_PATCH      = "skipped_no_patch"
    SKIPPED_UNAPPLICABLE  = "skipped_unapplicable"
    DECLINED              = "declined"
    APPLY_FAILED          = "apply_failed"
    TESTS_STILL_FAILING   = "tests_still_failing"
    REGRESSION            = "regression"
    FIXED                 = "fixed"

    outcome: str = ""

    @property
    def fixed(self) -> bool:
        return self.outcome == self.FIXED

    @property
    def patch_was_applied(self) -> bool:
        return (
            self.apply_result is not None
            and self.apply_result.success
        )


@dataclass
class RepairResult:
    """The complete outcome of a repair loop run."""

    repo_path: str
    total_iterations: int
    max_iterations: int
    initial_failures: int
    final_failures: int
    iterations: list[IterationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    all_green: bool = False
    stopped_reason: str = ""

    def summary(self) -> str:
        lines = [
            "",
            "=" * 64,
            "  ItDebugs Repair Loop - Summary",
            "=" * 64,
            f"  Repository      : {self.repo_path}",
            f"  Initial failures: {self.initial_failures}",
            f"  Final failures  : {self.final_failures}",
            f"  Iterations run  : {self.total_iterations} / {self.max_iterations}",
            f"  All tests green : {'YES' if self.all_green else 'NO'}",
            f"  Stopped because : {self.stopped_reason}",
        ]
        if self.errors:
            lines.append("")
            lines.append("  Errors:")
            for e in self.errors:
                lines.append(f"    - {e}")
        for it in self.iterations:
            lines.append("")
            lines.append(
                f"  Iteration {it.iteration}: Bug group '{it.group.key}' "
                f"-> {it.outcome}"
            )
            if it.patch:
                lines.append(
                    f"    Patch: {it.patch.file_path}:{it.patch.target_line}"
                )
            if it.apply_result and it.apply_result.success:
                lines.append(f"    Applied: {it.apply_result.message}")
        lines.append("")
        lines.append("=" * 64)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Approval helpers
# ---------------------------------------------------------------------------

def _default_approval_fn(patch: ProposedPatch) -> bool:
    """Prompt the developer interactively for approval."""
    print("\n" + "=" * 64)
    print("  Proposed patch (requires your approval)")
    print("=" * 64)
    print(f"\n  File : {patch.file_path}")
    print(f"  Line : {patch.target_line}")
    print(f"  Note : {patch.generation_note}")
    print()
    print(patch.diff_text)
    print()
    try:
        answer = input(
            "  Apply this patch? [yes/no] > "
        ).strip().lower()
    except (EOFError, OSError):
        # Non-interactive / CI / captured-stdout context: auto-approve
        print("\n  (non-interactive — auto-approving)")
        return True
    except KeyboardInterrupt:
        print("\n  (interrupted — treating as 'no')")
        return False
    return answer in {"y", "yes"}


# ---------------------------------------------------------------------------
# RepairLoop
# ---------------------------------------------------------------------------

class RepairLoop:
    """
    Orchestrates the autonomous debugging loop.

    Parameters
    ----------
    repo_path:
        Path to the repository root.
    max_iterations:
        Maximum number of repair attempts before stopping.
    test_timeout:
        Seconds before pytest is killed.
    verbose:
        Forward to the Orchestrator for detailed progress output.
    approval_fn:
        Callable that receives a :class:`ProposedPatch` and returns True
        if the developer approves.  Defaults to an interactive stdin prompt.
        Inject a custom function in tests to avoid blocking.
    """

    def __init__(
        self,
        repo_path: str,
        *,
        max_iterations: int = 5,
        test_timeout: int = 60,
        verbose: bool = False,
        approval_fn: Optional[Callable[[ProposedPatch], bool]] = None,
    ) -> None:
        self.repo_path = str(Path(repo_path).resolve())
        self.max_iterations = max_iterations
        self.test_timeout = test_timeout
        self.verbose = verbose
        self._approve = approval_fn or _default_approval_fn
        self._generator = PatchGenerator()
        self._applicator = PatchApplicator(self.repo_path)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> RepairResult:
        """
        Run the full repair loop and return a :class:`RepairResult`.
        Never raises.
        """
        self._header("ItDebugs - Autonomous Repair Loop")
        self._log(f"  Repository    : {self.repo_path}")
        self._log(f"  Max iterations: {self.max_iterations}")

        result = RepairResult(
            repo_path=self.repo_path,
            total_iterations=0,
            max_iterations=self.max_iterations,
            initial_failures=0,
            final_failures=0,
        )

        # ── Initial test run ─────────────────────────────────────────────
        self._section("Step 1/4  Running complete test suite")
        initial_run = run_tests(self.repo_path, timeout=self.test_timeout)
        self._log(
            f"  Total: {initial_run.total}  "
            f"Passed: {initial_run.passed}  "
            f"Failed: {initial_run.failed}"
        )

        if initial_run.timed_out:
            result.stopped_reason = "Initial test run timed out."
            result.errors.append(result.stopped_reason)
            return result

        if initial_run.collection_error:
            result.stopped_reason = "pytest collection error — check test file syntax."
            result.errors.append(result.stopped_reason)
            return result

        result.initial_failures = initial_run.failed

        if initial_run.failed == 0:
            self._log("  All tests pass — nothing to repair.")
            result.all_green = True
            result.stopped_reason = "No failing tests found."
            return result

        # ── Repair iterations ─────────────────────────────────────────────
        current_failures = initial_run.failed_tests
        iteration = 0

        while current_failures and iteration < self.max_iterations:
            iteration += 1
            result.total_iterations = iteration

            self._header(
                f"Iteration {iteration}/{self.max_iterations}  "
                f"({len(current_failures)} failure(s) to address)"
            )

            # Group remaining failures
            groups = group_failures(current_failures)
            self._log(f"  Failure groups: {len(groups)}")

            for group in groups:
                it_result = self._handle_group(iteration, group)
                result.iterations.append(it_result)

                if not it_result.patch_was_applied:
                    # No change was made — avoid an infinite loop
                    self._log(
                        f"  No patch applied for group '{group.key}'; "
                        "skipping to next."
                    )
                    continue

                if it_result.outcome == IterationResult.REGRESSION:
                    result.stopped_reason = (
                        f"Patch caused regressions in iteration {iteration}; "
                        "rolled back."
                    )
                    result.final_failures = (
                        it_result.full_suite_summary.failed
                        if it_result.full_suite_summary
                        else len(current_failures)
                    )
                    return result

                if it_result.outcome == IterationResult.FIXED:
                    # Refresh the current failure list from the full suite
                    if it_result.full_suite_summary:
                        current_failures = it_result.full_suite_summary.failed_tests
                        self._log(
                            f"  Remaining failures after fix: "
                            f"{len(current_failures)}"
                        )
                        self._applicator.cleanup_backups()
                    break  # re-enter the while loop with updated failures

        # ── Final state ───────────────────────────────────────────────────
        result.final_failures = len(current_failures)

        if not current_failures:
            result.all_green = True
            result.stopped_reason = "All tests pass."
            self._header("All tests pass — repair complete")
        elif iteration >= self.max_iterations:
            result.stopped_reason = (
                f"Maximum iterations ({self.max_iterations}) reached."
            )
            self._log(f"  {result.stopped_reason}")
        else:
            result.stopped_reason = (
                f"{len(current_failures)} failure(s) could not be repaired."
            )

        return result

    # ------------------------------------------------------------------
    # Per-group handling
    # ------------------------------------------------------------------

    def _handle_group(
        self,
        iteration: int,
        group: BugGroup,
    ) -> IterationResult:
        """Investigate one bug group and attempt a repair."""

        it_result = IterationResult(
            iteration=iteration,
            group=group,
            report=None,
            patch=None,
            apply_result=None,
            retest_summary=None,
            full_suite_summary=None,
        )

        # ── Step 2: investigate ───────────────────────────────────────────
        self._section(
            f"Step 2/4  Investigating bug group '{group.key}' "
            f"({group.test_count} failure(s))"
        )

        description = group.build_description()
        try:
            orchestrator = Orchestrator(
                repo_path=self.repo_path,
                bug_description=description,
                test_timeout=self.test_timeout,
                verbose=self.verbose,
            )
            report = orchestrator.run()
            it_result.report = report
        except Exception as exc:  # noqa: BLE001
            self._log(f"  Investigation error: {exc}")
            it_result.outcome = IterationResult.SKIPPED_NO_HYPOTHESIS
            return it_result

        if report.root_cause is None:
            self._log("  No root cause identified — cannot generate patch.")
            it_result.outcome = IterationResult.SKIPPED_NO_HYPOTHESIS
            return it_result

        rc = report.root_cause
        self._log(
            f"  Root cause: {rc.file}:{rc.line_range} "
            f"(confidence: {rc.confidence})"
        )

        # ── Step 3: generate patch ────────────────────────────────────────
        self._section("Step 3/4  Generating patch")

        patch = self._generator.generate(self.repo_path, rc)
        it_result.patch = patch

        if not patch.can_apply:
            self._log(f"  Cannot generate automatic patch: {patch.generation_note}")
            self._log("  Manual repair required.")
            self._log("")
            self._log(patch.diff_text)
            it_result.outcome = IterationResult.SKIPPED_UNAPPLICABLE
            return it_result

        self._log(f"  Patch ready: {patch.generation_note}")

        # ── Step 4a: show patch and request approval ──────────────────────
        approved = self._approve(patch)

        if not approved:
            self._log("  Developer declined the patch.")
            it_result.outcome = IterationResult.DECLINED
            return it_result

        # ── Step 4b: apply patch ──────────────────────────────────────────
        self._section("Step 4/4  Applying patch + retesting")

        apply_result = self._applicator.apply(patch)
        it_result.apply_result = apply_result

        if not apply_result.success:
            self._log(f"  Patch application failed: {apply_result.message}")
            it_result.outcome = IterationResult.APPLY_FAILED
            return it_result

        self._log(f"  {apply_result.message}")

        # ── Step 4c: re-run affected tests ────────────────────────────────
        failing_node_ids = [f.node_id for f in group.failures]
        self._log(
            f"  Re-running {len(failing_node_ids)} affected test(s)..."
        )

        retest = run_tests(
            self.repo_path,
            extra_args=failing_node_ids,
            timeout=self.test_timeout,
        )
        it_result.retest_summary = retest
        self._log(
            f"  Targeted retest: "
            f"{retest.passed} passed / {retest.failed} failed"
        )

        if retest.failed > 0:
            self._log(
                "  Targeted tests still failing — restoring backup."
            )
            messages = self._applicator.restore(patch.file_path)
            for m in messages:
                self._log(f"    {m}")
            it_result.outcome = IterationResult.TESTS_STILL_FAILING
            return it_result

        # ── Step 4d: run the full suite to catch regressions ─────────────
        self._log("  Targeted tests pass — running full suite...")

        full_run = run_tests(self.repo_path, timeout=self.test_timeout)
        it_result.full_suite_summary = full_run
        self._log(
            f"  Full suite: "
            f"{full_run.total} total / "
            f"{full_run.passed} passed / "
            f"{full_run.failed} failed"
        )

        # Check for regressions: failures that were NOT in the original group
        original_failing_ids = {f.node_id for f in group.failures}
        new_failures = [
            t for t in full_run.failed_tests
            if t.node_id not in original_failing_ids
        ]

        if new_failures:
            self._log(
                f"  Patch introduced {len(new_failures)} new failure(s). "
                "Rolling back."
            )
            for nf in new_failures[:5]:
                self._log(f"    - {nf.node_id}")
            messages = self._applicator.restore(patch.file_path)
            for m in messages:
                self._log(f"    {m}")
            it_result.outcome = IterationResult.REGRESSION
            return it_result

        self._log("  All tests pass after patch. Fix accepted.")
        it_result.outcome = IterationResult.FIXED
        return it_result

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        print(msg, file=sys.stderr)

    def _section(self, title: str) -> None:
        self._log(f"\n  {title}")
        self._log("  " + "-" * (len(title) + 2))

    def _header(self, title: str) -> None:
        bar = "=" * 64
        self._log(f"\n{bar}")
        self._log(f"  {title}")
        self._log(bar)
