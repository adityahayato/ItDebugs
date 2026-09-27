"""
Multi-bug investigation support for ItDebugs.

Runs the target repository test suite once, discovers all failing tests,
groups related failures, and sends each group through the existing
multi-agent investigation pipeline.

The existing single-bug orchestrator remains unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from itdebugs.engine.reporter import InvestigationReport, render_text
from itdebugs.engine.test_runner import TestResult, TestRunSummary, run_tests
from itdebugs.orchestrator import Orchestrator


@dataclass
class BugGroup:
    """A group of related failing tests."""

    group_id: int
    key: str
    failures: list[TestResult] = field(default_factory=list)

    @property
    def test_count(self) -> int:
        return len(self.failures)

    def build_description(self) -> str:
        """Create a useful investigation prompt from the failures."""

        lines = [
            "Investigate the following related test failures.",
            "",
            f"Failure group: {self.key}",
            "",
            "Failing tests:",
        ]

        for failure in self.failures:
            lines.append(f"- {failure.node_id}")

            if failure.failure_message:
                message = failure.failure_message.strip()
                if len(message) > 1200:
                    message = message[:1200] + "..."
                lines.append(f"  Failure: {message}")

        lines.extend(
            [
                "",
                "Determine the common root cause of these failures.",
                "Inspect the relevant source code and identify the exact "
                "faulty location.",
            ]
        )

        return "\n".join(lines)


@dataclass
class MultiBugReport:
    """Final result of a multi-bug investigation."""

    repo_path: str
    test_run: TestRunSummary
    groups: list[BugGroup] = field(default_factory=list)
    reports: list[InvestigationReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def investigation_successful(self) -> bool:
        """True when the discovery phase and investigations completed."""

        return not self.test_run.collection_error and not self.test_run.timed_out

    @property
    def bug_count(self) -> int:
        return len(self.groups)


def group_failures(
    failures: list[TestResult],
) -> list[BugGroup]:
    """
    Group failures into investigation units.

    Version 1 groups failures by test file. This is deliberately conservative:
    failures from the same test module are investigated together, while
    failures from different modules become separate investigations.
    """

    buckets: dict[str, list[TestResult]] = {}

    for failure in failures:
        key = failure.file or "unknown-test-file"
        buckets.setdefault(key, []).append(failure)

    groups: list[BugGroup] = []

    for index, (key, items) in enumerate(buckets.items(), start=1):
        groups.append(
            BugGroup(
                group_id=index,
                key=key,
                failures=items,
            )
        )

    return groups


def investigate_repository(
    repo_path: str | Path,
    *,
    timeout: int = 60,
    verbose: bool = False,
) -> MultiBugReport:
    """
    Discover and investigate all failing test groups in a repository.
    """

    repo = Path(repo_path).resolve()

    print("\n" + "=" * 64)
    print(" ItDebugs - Multi-Bug Investigation")
    print("=" * 64)
    print(f" Repository : {repo}")
    print()

    # ------------------------------------------------------------
    # Phase 1: discover all failures with ONE test run
    # ------------------------------------------------------------

    print("[1/3] Running complete test suite...")

    test_run = run_tests(
        repo,
        timeout=timeout,
    )

    print(
        f"      Tests: {test_run.total} total | "
        f"{test_run.passed} passed | "
        f"{test_run.failed} failed | "
        f"{test_run.errors} errors"
    )

    if test_run.timed_out:
        print("      ERROR: test suite timed out.")
        return MultiBugReport(
            repo_path=str(repo),
            test_run=test_run,
        )

    if test_run.collection_error:
        print("      ERROR: pytest collection failed.")
        return MultiBugReport(
            repo_path=str(repo),
            test_run=test_run,
        )

    failures = test_run.failed_tests

    # ------------------------------------------------------------
    # No failures
    # ------------------------------------------------------------

    if not failures:
        print()
        print("No failing tests discovered.")
        print("Repository appears healthy according to the test suite.")

        return MultiBugReport(
            repo_path=str(repo),
            test_run=test_run,
        )

    # ------------------------------------------------------------
    # Phase 2: group failures
    # ------------------------------------------------------------

    print()
    print("[2/3] Grouping related failures...")

    groups = group_failures(failures)

    for group in groups:
        print(
            f"      Bug #{group.group_id}: "
            f"{group.test_count} failure(s) "
            f"from {group.key}"
        )

        if verbose:
            for failure in group.failures:
                print(f"         - {failure.node_id}")

    # ------------------------------------------------------------
    # Phase 3: investigate each group
    # ------------------------------------------------------------

    print()
    print("[3/3] Investigating discovered bug groups...")

    reports: list[InvestigationReport] = []
    errors: list[str] = []

    for group in groups:
        print()
        print("-" * 64)
        print(
            f" Bug #{group.group_id}: "
            f"{group.test_count} failing test(s)"
        )
        print("-" * 64)

        description = group.build_description()

        try:
            orchestrator = Orchestrator(
                repo_path=str(repo),
                bug_description=description,
                test_timeout=timeout,
                verbose=verbose,
            )

            report = orchestrator.run()
            reports.append(report)

            if report.investigation_successful:
                print(
                    f"      ✓ Investigation #{group.group_id} completed"
                )
            else:
                print(
                    f"      ! Investigation #{group.group_id} "
                    "completed with issues"
                )

        except Exception as exc:  # noqa: BLE001
            message = (
                f"Bug #{group.group_id} investigation failed: {exc}"
            )
            errors.append(message)
            print(f"      ✗ {message}")

    return MultiBugReport(
        repo_path=str(repo),
        test_run=test_run,
        groups=groups,
        reports=reports,
        errors=errors,
    )


def render_multi_bug_report(result: MultiBugReport) -> str:
    """Render a readable final multi-bug report."""

    lines: list[str] = []

    lines.append("")
    lines.append("=" * 72)
    lines.append("ITDEBUGS - MULTI-BUG INVESTIGATION REPORT")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"Repository: {result.repo_path}")
    lines.append("")
    lines.append(
        f"Test suite: {result.test_run.total} total | "
        f"{result.test_run.passed} passed | "
        f"{result.test_run.failed} failed | "
        f"{result.test_run.errors} errors"
    )
    lines.append("")
    lines.append(f"Discovered bug groups: {result.bug_count}")
    lines.append("")

    if not result.groups:
        lines.append("No failing test groups were discovered.")
        return "\n".join(lines)

    for index, (group, report) in enumerate(
        zip(result.groups, result.reports),
        start=1,
    ):
        lines.append("")
        lines.append("#" * 72)
        lines.append(
            f"BUG #{index} - {group.test_count} related failure(s)"
        )
        lines.append("#" * 72)
        lines.append("")
        lines.append(f"Failure group: {group.key}")
        lines.append("")
        lines.append("Failing tests:")

        for failure in group.failures:
            lines.append(f"  - {failure.node_id}")

        lines.append("")
        lines.append("Investigation:")
        lines.append("")

        try:
            lines.append(render_text(report))
        except Exception as exc:  # noqa: BLE001
            lines.append(
                f"[Unable to render investigation report: {exc}]"
            )

    if result.errors:
        lines.append("")
        lines.append("=" * 72)
        lines.append("INVESTIGATION ERRORS")
        lines.append("=" * 72)

        for error in result.errors:
            lines.append(f"- {error}")

    lines.append("")
    lines.append("=" * 72)
    lines.append("END OF MULTI-BUG REPORT")
    lines.append("=" * 72)

    return "\n".join(lines)