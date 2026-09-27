"""
engine/test_runner.py
=====================
Safely executes the project's pytest suite in a subprocess, captures all
output, and parses it into structured :class:`TestResult` / :class:`TestRunSummary`
objects for the investigation engine.

Design constraints
------------------
* Never imports or executes the target project's code in-process — always uses
  a subprocess so a crashing test cannot bring down the investigator.
* Works without pytest-json-report or any extra pytest plugin; parses the
  standard --tb=short -v output.
* Enforces a configurable wall-clock timeout so a hanging test suite cannot
  stall the investigation indefinitely.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    """Outcome of a single test item."""
    node_id: str           # e.g. "tests/test_task_manager.py::TestFoo::test_bar"
    outcome: str           # "PASSED" | "FAILED" | "ERROR" | "SKIPPED" | "XFAIL" | "XPASS"
    file: str              # relative file path portion of node_id
    class_name: str        # class name if present, else ""
    test_name: str         # bare function name
    failure_message: str   # captured failure / error text, "" if passed

    @property
    def failed(self) -> bool:
        return self.outcome in ("FAILED", "ERROR")

    @property
    def passed(self) -> bool:
        return self.outcome == "PASSED"


@dataclass
class TestRunSummary:
    """Aggregated results of a single pytest run."""
    repo_root: str
    test_dirs: List[str]
    return_code: int
    raw_output: str
    results: List[TestResult] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    collection_error: bool = False
    timed_out: bool = False

    @property
    def has_failures(self) -> bool:
        return self.failed > 0 or self.errors > 0

    @property
    def failed_tests(self) -> List[TestResult]:
        return [r for r in self.results if r.failed]

    @property
    def passed_tests(self) -> List[TestResult]:
        return [r for r in self.results if r.passed]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

# Matches verbose lines like:
#   tests/test_foo.py::ClassName::test_method PASSED   [ 50%]
#   tests/test_foo.py::test_function FAILED    [100%]
_RESULT_LINE_RE = re.compile(
    r"^(?P<node_id>\S+::[\w\[\]<>, .-]+)\s+"
    r"(?P<outcome>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)"
    r"\s",
    re.MULTILINE,
)

# Individual count patterns applied independently on the summary line.
# e.g. "3 failed, 19 passed in 0.07s"
_COUNT_RE = {
    "failed":  re.compile(r"(\d+)\s+failed"),
    "passed":  re.compile(r"(\d+)\s+passed"),
    "errors":  re.compile(r"(\d+)\s+error"),
    "skipped": re.compile(r"(\d+)\s+skipped"),
}

# Failure blocks between "FAILURES" and the next section divider
_FAILURE_BLOCK_RE = re.compile(
    r"_{5,}\s+(?P<node_id>\S+)\s+_{5,}\n(?P<body>.*?)(?=\n_{5,}|\Z)",
    re.DOTALL,
)


def _parse_node_id(node_id: str) -> tuple[str, str, str]:
    """Split node_id into (file, class_name, test_name)."""
    parts = node_id.split("::")
    file_part = parts[0] if parts else node_id
    if len(parts) == 3:
        return file_part, parts[1], parts[2]
    if len(parts) == 2:
        return file_part, "", parts[1]
    return file_part, "", node_id


def _extract_failure_messages(output: str) -> Dict[str, str]:
    """
    Parse the FAILURES section of pytest's -v output and return a mapping
    from test node_id → failure body text.
    """
    messages: Dict[str, str] = {}
    for match in _FAILURE_BLOCK_RE.finditer(output):
        node_id = match.group("node_id").strip()
        body = match.group("body").strip()
        # node_id in the FAILURES section uses spaces as separators on some
        # platforms; normalise to "::"
        normalised = node_id.replace(" ", "::")
        messages[normalised] = body
    return messages


def _parse_output(output: str, repo_root: str) -> List[TestResult]:
    """Parse verbose pytest stdout into a list of :class:`TestResult` objects."""
    failure_msgs = _extract_failure_messages(output)

    results: List[TestResult] = []
    for m in _RESULT_LINE_RE.finditer(output):
        node_id = m.group("node_id").strip()
        outcome = m.group("outcome").strip()
        file_part, class_name, test_name = _parse_node_id(node_id)

        # Look up failure message — try exact node_id first, then by test name
        failure_msg = (
            failure_msgs.get(node_id)
            or failure_msgs.get(f"{file_part}::{class_name}::{test_name}")
            or failure_msgs.get(f"{class_name}.{test_name}")
            or ""
        )

        results.append(TestResult(
            node_id=node_id,
            outcome=outcome,
            file=file_part,
            class_name=class_name,
            test_name=test_name,
            failure_message=failure_msg,
        ))

    return results


def _parse_summary_line(output: str) -> tuple[int, int, int, int]:
    """Extract (failed, passed, errors, skipped) totals from the summary line."""
    for line in reversed(output.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            def _get(key: str) -> int:
                m = _COUNT_RE[key].search(line)
                return int(m.group(1)) if m else 0
            return _get("failed"), _get("passed"), _get("errors"), _get("skipped")
    return 0, 0, 0, 0


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_tests(
    repo_root: str | Path,
    test_dirs: Optional[List[str]] = None,
    timeout: int = 60,
    extra_args: Optional[List[str]] = None,
) -> TestRunSummary:
    """
    Run pytest on *repo_root* (optionally restricted to *test_dirs*) in a
    subprocess with a *timeout* second wall-clock limit.

    Parameters
    ----------
    repo_root:
        Absolute or relative path to the repository root.  pytest is invoked
        with this as the working directory.
    test_dirs:
        List of directory paths relative to *repo_root* to pass to pytest.
        If None or empty, pytest auto-discovers tests.
    timeout:
        Maximum seconds to wait before killing the subprocess.
    extra_args:
        Additional arguments forwarded verbatim to pytest (e.g. ["-x"]).

    Returns
    -------
    TestRunSummary
        Always returns a summary — even on collection errors or timeouts.
    """
    root = Path(repo_root).resolve()
    dirs = test_dirs or []

    cmd = [
        sys.executable, "-m", "pytest",
        "--tb=short",    # concise failure tracebacks
        "-v",            # verbose — one line per test
        "--no-header",   # suppress the pytest header line
        "-p", "no:cacheprovider",  # don't write .pytest_cache in target repo
    ] + (extra_args or []) + dirs

    summary = TestRunSummary(
        repo_root=str(root),
        test_dirs=dirs,
        return_code=-1,
        raw_output="",
    )

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else "")
        summary.return_code = proc.returncode
        summary.raw_output = output

    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\n[ItDebugs] Test run timed out after {} seconds.".format(timeout)
        summary.raw_output = output
        summary.timed_out = True
        return summary

    except Exception as exc:  # noqa: BLE001
        summary.raw_output = f"[ItDebugs] Failed to launch pytest: {exc}"
        return summary

    # Detect collection errors
    if "no tests ran" in output.lower() or "collected 0 items" in output.lower():
        if proc.returncode != 0:
            summary.collection_error = True

    summary.results = _parse_output(output, str(root))
    failed, passed, errors, skipped = _parse_summary_line(output)
    summary.failed = failed
    summary.passed = passed
    summary.errors = errors
    summary.skipped = skipped
    summary.total = failed + passed + errors + skipped

    return summary
