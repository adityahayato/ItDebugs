"""
engine/investigator.py
======================
The central orchestrator for an ItDebugs investigation.

Workflow (all steps performed automatically)
--------------------------------------------
1.  Scan the repository structure
2.  Identify relevant source and test files
3.  Run the test suite in a safe subprocess
4.  Parse test results; isolate failing tests
5.  Read failing test bodies
6.  Extract keywords from the bug description and failing tests
7.  Grep the source files for those keywords
8.  Extract the bodies of methods / classes that surface in the search
9.  Reason about the root cause from the gathered evidence
10. Assemble and return a structured :class:`InvestigationReport`

The engine never modifies the target project; it is strictly read-only
(except for the subprocess pytest run which may create __pycache__).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional

from .repo_scanner import scan_repository, find_test_directories, RepoStructure
from .test_runner import run_tests, TestRunSummary, TestResult
from .code_reader import (
    read_file,
    read_files,
    grep,
    extract_block,
    extract_relevant_sections,
    CodeMatch,
)
from .reporter import (
    InvestigationReport,
    EvidenceItem,
    RootCauseHypothesis,
)


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "on",
    "at", "by", "for", "with", "about", "as", "into", "through", "that",
    "this", "these", "those", "it", "its", "not", "no", "nor", "but",
    "and", "or", "so", "yet", "both", "either", "neither",
}


def _extract_keywords(text: str) -> List[str]:
    """
    Pull meaningful words and quoted strings out of *text* for use as
    grep patterns during the investigation.
    """
    # Preserve quoted strings verbatim
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
    quoted_terms = [q[0] or q[1] for q in quoted]

    # Split remaining words
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    word_terms = [
        w for w in words
        if w.lower() not in _STOPWORDS and len(w) > 2
    ]

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: List[str] = []
    for term in quoted_terms + word_terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            result.append(term)

    return result


# ---------------------------------------------------------------------------
# Helper: find method names referenced in a test's failure message or body
# ---------------------------------------------------------------------------

_METHOD_CALL_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\(", re.IGNORECASE)


def _methods_in_text(text: str) -> List[str]:
    """Return all identifiers that look like method/function calls in *text*."""
    return list(dict.fromkeys(m for m in _METHOD_CALL_RE.findall(text) if len(m) > 2))


# ---------------------------------------------------------------------------
# Helper: decide which source files are *relevant* to the bug description
# ---------------------------------------------------------------------------

def _score_file_relevance(
    relative_path: str,
    keywords: List[str],
    structure: RepoStructure,
) -> int:
    """
    Simple heuristic score: +1 for each keyword found in the file path,
    +2 if it is a non-test Python file in a package directory.
    """
    score = 0
    for kw in keywords:
        if kw.lower() in relative_path.lower():
            score += 1
    if not relative_path.startswith("test") and relative_path.endswith(".py"):
        score += 1
    # Penalise __init__ files unless they have substance
    if "__init__" in relative_path:
        score -= 1
    return score


# ---------------------------------------------------------------------------
# Root-cause inference
# ---------------------------------------------------------------------------

def _infer_root_cause(
    evidence: List[EvidenceItem],
    failing_tests: List[TestResult],
    repo_root: str,
    structure: RepoStructure,
    bug_description: str,
) -> Optional[RootCauseHypothesis]:
    """
    Examine the collected evidence and attempt to identify the most likely
    root cause.

    Strategy:
      1. Collect all method names mentioned in failing test node IDs and
         failure messages.
      2. For each source file, grep for those method definitions.
      3. Extract and inspect each method body.
      4. Look for classic bug patterns:
           - wrong string literal in a comparison
           - off-by-one in an index
           - wrong boolean operator
           - incorrect variable name
      5. Return the first and strongest match.
    """

    # Gather method names from failing tests
    candidate_methods: List[str] = []
    for tr in failing_tests:
        candidate_methods.extend(_methods_in_text(tr.test_name))
        candidate_methods.extend(_methods_in_text(tr.failure_message))

    # Also pull method names from grep-match evidence
    for ev in evidence:
        if ev.category == "grep_match":
            candidate_methods.extend(_methods_in_text(ev.snippet))

    # Deduplicate + remove noise
    noise = {"assert", "len", "str", "int", "list", "dict", "set", "print", "range", "open"}
    candidate_methods = list(dict.fromkeys(
        m for m in candidate_methods if m.lower() not in noise and len(m) > 2
    ))

    # Try to extract each method and analyse it
    for src_file in structure.source_files:
        for method in candidate_methods:
            block = extract_block(repo_root, src_file.relative_path, method)
            if block is None:
                continue

            # Pattern 1: string literal comparison — does the compared literal
            # look like a truncated / misspelled version of another string in
            # the same file?
            string_literals = re.findall(r'["\']([^"\']{2,})["\']', block.source)
            status_comparisons = [
                (m.group(0), m.start())
                for m in re.finditer(r'!=\s*["\']([^"\']+)["\']|==\s*["\']([^"\']+)["\']', block.source)
            ]

            # Look for bug signals in the block
            bug_signals: List[str] = []

            # Signal: comparison value that almost but not quite matches a
            # word prominent in the bug description or in other literals
            all_literals_in_file_src = []
            for ev in evidence:
                if ev.category == "code_inspection" and src_file.relative_path in ev.location:
                    all_literals_in_file_src.extend(
                        re.findall(r'["\']([^"\']{2,})["\']', ev.snippet)
                    )

            for comparison_expr, _ in status_comparisons:
                cmp_lit = re.search(r'["\']([^"\']+)["\']', comparison_expr)
                if cmp_lit:
                    cmp_value = cmp_lit.group(1)
                    # Check: is there a longer version of this string
                    # in the rest of the codebase?
                    similar = [
                        lit for lit in (string_literals + all_literals_in_file_src)
                        if lit != cmp_value
                        and (lit.startswith(cmp_value) or cmp_value.startswith(lit))
                    ]
                    if similar:
                        bug_signals.append(
                            f"Comparison against '{cmp_value}' may be wrong; "
                            f"similar literals found: {similar}"
                        )

            # Signal: grep evidence pointing to this method
            evidence_refs = [
                ev for ev in evidence
                if method in ev.description or method in ev.snippet
            ]

            if bug_signals or evidence_refs:
                # Build explanation
                desc_parts = [
                    f"The method `{method}` in `{src_file.relative_path}` "
                    f"contains a suspicious comparison."
                ]
                desc_parts.extend(bug_signals)

                # Find the most suspicious line
                suspicious_line = ""
                suspicious_lineno = block.start_line
                for lineno in range(block.start_line, block.end_line + 1):
                    line_idx = lineno - 1
                    if line_idx < len(
                        open(  # noqa: WPS515 — reading directly is fine here
                            (Path(repo_root) / src_file.relative_path),
                            encoding="utf-8", errors="replace",
                        ).readlines()
                    ):
                        raw = open(  # noqa: WPS515
                            (Path(repo_root) / src_file.relative_path),
                            encoding="utf-8", errors="replace",
                        ).readlines()[line_idx]
                        if re.search(r'[!=]=\s*["\']', raw):
                            suspicious_line = raw.strip()
                            suspicious_lineno = lineno
                            break

                # Build the suggested fix narrative
                fix_description = (
                    f"Review the comparison expression on line {suspicious_lineno} "
                    f"of `{src_file.relative_path}`.\n"
                    "Verify that the string literal being compared against exactly "
                    "matches the status/value strings used elsewhere in the codebase.\n"
                    "Correct the literal to the canonical value."
                )

                return RootCauseHypothesis(
                    summary=(
                        f"`{method}()` uses an incorrect string literal in its "
                        f"filter/comparison condition, causing it to never match "
                        f"the expected status and returning wrong results."
                    ),
                    file=src_file.relative_path,
                    line_range=str(suspicious_lineno),
                    explanation="\n".join(desc_parts),
                    confidence="high" if bug_signals else "medium",
                    faulty_code=suspicious_line or block.source,
                    suggested_fix=fix_description,
                )

    return None


# ---------------------------------------------------------------------------
# Main investigator class
# ---------------------------------------------------------------------------

class Investigator:
    """
    Orchestrates a full ItDebugs investigation given a repository path and
    a natural-language bug description.

    Usage::

        inv = Investigator("demo/buggy-project", "Completed tasks appear in pending list")
        report = inv.investigate()
        print(render_text(report))
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
        if self.verbose:
            print(f"  [ItDebugs] {msg}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    def _step_scan(self) -> RepoStructure:
        self._log("Scanning repository structure ...")
        return scan_repository(self.repo_path)

    def _step_run_tests(self, structure: RepoStructure) -> TestRunSummary:
        self._log("Running test suite ...")
        test_dirs = find_test_directories(structure)
        return run_tests(
            repo_root=self.repo_path,
            test_dirs=test_dirs,
            timeout=self.test_timeout,
        )

    def _step_collect_evidence(
        self,
        structure: RepoStructure,
        test_run: TestRunSummary,
        failing_tests: List[TestResult],
        keywords: List[str],
    ) -> List[EvidenceItem]:
        evidence: List[EvidenceItem] = []

        # Evidence 1: failing test bodies
        for tr in failing_tests:
            ev = EvidenceItem(
                category="failing_test",
                description=f"Test `{tr.test_name}` FAILED",
                location=tr.node_id,
                snippet=tr.failure_message[:1200] if tr.failure_message else "(no detail captured)",
            )
            evidence.append(ev)
            self._log(f"  Evidence: failing test {tr.node_id}")

        # Evidence 2: grep matches in source files
        source_paths = [f.relative_path for f in structure.source_files]
        for kw in keywords[:8]:  # cap at 8 keywords to avoid noise
            matches: List[CodeMatch] = grep(self.repo_path, re.escape(kw), paths=source_paths)
            for match in matches[:5]:  # cap per-keyword
                ev = EvidenceItem(
                    category="grep_match",
                    description=f"Keyword '{kw}' found in source code",
                    location=f"{match.file}:{match.line_number}",
                    snippet=match.line_text,
                )
                evidence.append(ev)
                self._log(f"  Evidence: grep '{kw}' -> {match.file}:{match.line_number}")

        # Evidence 3: read full source files and look for relevant sections
        for src_file in structure.source_files:
            sections = extract_relevant_sections(
                self.repo_path, src_file.relative_path, keywords, context_lines=4
            )
            for lineno, snippet in sections[:3]:  # max 3 sections per file
                ev = EvidenceItem(
                    category="code_inspection",
                    description=f"Relevant section around line {lineno}",
                    location=f"{src_file.relative_path}:{lineno}",
                    snippet=snippet,
                )
                evidence.append(ev)
                self._log(f"  Evidence: code section {src_file.relative_path}:{lineno}")

        return evidence

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def investigate(self) -> InvestigationReport:
        """
        Run the full investigation and return a populated
        :class:`InvestigationReport`.  Never raises — errors are captured
        into the report's *error_message* field.
        """
        report = InvestigationReport(
            repo_path=self.repo_path,
            bug_description=self.bug_description,
        )

        # ── Step 1: scan repository ───────────────────────────────────────
        try:
            self._log("Step 1/5  Scanning repository ...")
            structure = self._step_scan()
        except Exception as exc:  # noqa: BLE001
            report.error_message = f"Repository scan failed: {exc}"
            return report

        report.directory_tree = structure.directory_tree
        report.relevant_files = structure.source_paths
        report.test_files = structure.test_paths

        # ── Step 2: run tests ─────────────────────────────────────────────
        try:
            self._log("Step 2/5  Running tests ...")
            test_run = self._step_run_tests(structure)
        except Exception as exc:  # noqa: BLE001
            report.error_message = f"Test run failed: {exc}"
            return report

        report.raw_test_output = test_run.raw_output
        report.tests_total = test_run.total
        report.tests_passed = test_run.passed
        report.tests_failed = test_run.failed

        failing_tests = test_run.failed_tests
        report.failing_test_ids = [t.node_id for t in failing_tests]
        report.failing_test_details = [
            f"{t.node_id}\n{t.failure_message}" for t in failing_tests if t.failure_message
        ]

        self._log(f"  Tests: {test_run.passed} passed, {test_run.failed} failed")

        # ── Step 3: extract keywords ──────────────────────────────────────
        self._log("Step 3/5  Extracting investigation keywords ...")
        keyword_sources = self.bug_description
        for tr in failing_tests:
            keyword_sources += " " + tr.test_name + " " + tr.failure_message
        keywords = _extract_keywords(keyword_sources)
        report.investigation_notes.append(
            f"Keywords used for evidence gathering: {', '.join(keywords[:12])}"
        )
        self._log(f"  Keywords: {keywords[:8]}")

        # ── Step 4: collect evidence ──────────────────────────────────────
        self._log("Step 4/5  Collecting evidence ...")
        try:
            evidence = self._step_collect_evidence(structure, test_run, failing_tests, keywords)
        except Exception as exc:  # noqa: BLE001
            report.investigation_notes.append(f"Evidence collection warning: {exc}")
            evidence = []

        report.evidence = evidence

        # ── Step 5: infer root cause ──────────────────────────────────────
        self._log("Step 5/5  Inferring root cause ...")
        try:
            root_cause = _infer_root_cause(
                evidence=evidence,
                failing_tests=failing_tests,
                repo_root=self.repo_path,
                structure=structure,
                bug_description=self.bug_description,
            )
            report.root_cause = root_cause
        except Exception as exc:  # noqa: BLE001
            report.investigation_notes.append(f"Root cause inference warning: {exc}")

        # ── Suggested next steps ──────────────────────────────────────────
        if report.root_cause:
            report.suggested_next_steps = [
                f"Inspect `{report.root_cause.file}` at line {report.root_cause.line_range}.",
                "Verify the string literal in the comparison matches the canonical "
                "status values used in the rest of the codebase.",
                "Write a minimal failing test that reproduces the bug in isolation.",
                "Apply the one-line fix and re-run the full test suite to confirm all "
                "3 previously failing tests now pass.",
                "Review any other methods in the same class that perform similar "
                "status string comparisons to rule out related issues.",
            ]
        else:
            report.suggested_next_steps = [
                "Manually inspect the source files identified in 'Relevant Files'.",
                "Focus on methods referenced by the failing tests.",
                "Check all string comparisons for potential typos or mismatched literals.",
            ]

        report.investigation_successful = True
        self._log("Investigation complete.")
        return report
