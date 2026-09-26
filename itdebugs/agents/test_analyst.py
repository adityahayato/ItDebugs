"""
agents/test_analyst.py
======================
Test Analyst agent.

Responsibility
--------------
Run the project's test suite in a safe subprocess, parse the results, and
identify which tests are failing.  Also extracts keywords from the bug
description and failure messages for use by the Code Analyst.

Reuses
------
``itdebugs.engine.test_runner.run_tests``
``itdebugs.engine.repo_scanner.find_test_directories``
``itdebugs.engine.investigator._extract_keywords``

Requires
--------
ctx.repo_structure  (set by RepositoryAnalyst)

Populates
---------
ctx.test_run        :  TestRunSummary
ctx.failing_tests   :  List[TestResult]
ctx.keywords        :  List[str]  (for downstream grep/search)
"""

from __future__ import annotations

import re
from typing import List, Set

from itdebugs.agents.base import BaseAgent
from itdebugs.agents.context import InvestigationContext
from itdebugs.engine.repo_scanner import find_test_directories
from itdebugs.engine.test_runner import run_tests

# ── Keyword extraction (same logic as the legacy Investigator) ──────────────

_STOPWORDS: Set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "on",
    "at", "by", "for", "with", "about", "as", "into", "through", "that",
    "this", "these", "those", "it", "its", "not", "no", "nor", "but",
    "and", "or", "so", "yet", "both", "either", "neither",
}


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful terms from free text (shared utility)."""
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
    quoted_terms = [q[0] or q[1] for q in quoted]
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    word_terms = [w for w in words if w.lower() not in _STOPWORDS and len(w) > 2]
    seen: Set[str] = set()
    result: List[str] = []
    for term in quoted_terms + word_terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            result.append(term)
    return result


class TestAnalyst(BaseAgent):
    """
    Runs the test suite and identifies failing tests.

    The test suite is always executed in a subprocess so a crashing or
    hanging test cannot destabilise the investigator process.

    Future LLM enhancement
    ----------------------
    An LLM-powered version could:
      - Classify each failure by type (assertion error, exception, timeout)
      - Cluster related failures to detect a single underlying cause
      - Suggest additional targeted tests to isolate the defect
    """

    @property
    def name(self) -> str:
        return "Test Analyst"

    def _execute(self, ctx: InvestigationContext) -> None:
        if ctx.repo_structure is None:
            raise RuntimeError("repo_structure not set; run RepositoryAnalyst first")

        test_dirs = find_test_directories(ctx.repo_structure)
        self._log(f"[{self.name}] Running tests in: {test_dirs or ['(auto-discover)']}")

        test_run = run_tests(
            repo_root=ctx.repo_path,
            test_dirs=test_dirs,
            timeout=ctx.test_timeout,
        )
        ctx.test_run = test_run
        ctx.failing_tests = test_run.failed_tests

        self._log(
            f"[{self.name}] {test_run.passed} passed, "
            f"{test_run.failed} failed, "
            f"{test_run.total} total"
        )

        # Build keyword list from bug description + failure evidence
        keyword_source = ctx.bug_description
        for tr in ctx.failing_tests:
            keyword_source += " " + tr.test_name + " " + tr.failure_message
        ctx.keywords = _extract_keywords(keyword_source)

        ctx.add_note(
            self.name,
            f"Tests: {test_run.total} total, {test_run.passed} passed, "
            f"{test_run.failed} failed. "
            f"Keywords extracted: {', '.join(ctx.keywords[:10])}",
        )

        if test_run.timed_out:
            ctx.add_error(self.name, "Test run timed out — results may be incomplete.")
        if test_run.collection_error:
            ctx.add_error(self.name, "pytest collection error — check test file syntax.")
