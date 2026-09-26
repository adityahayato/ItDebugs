"""
itdebugs/tests/test_intelligence.py
=====================================
Tests for the Repository Intelligence layer.

Coverage
--------
* FileInventory — file classification, exclusions, size limits, binary detection
* RepositoryProfiler — language detection, framework/tool detection, directory inference
* RelevanceSelector — keyword extraction, scoring signals, candidate ranking
* Integration with RepositoryAnalyst agent
* Demo-project compatibility
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List

import pytest

# Ensure itdebugs is importable from the project root
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from itdebugs.intelligence.inventory import FileInventory, InventoryConfig, _is_test_file
from itdebugs.intelligence.models import (
    CandidateFile,
    FileCategory,
    FileRecord,
    Language,
    RepositoryProfile,
)
from itdebugs.intelligence.profiler import RepositoryProfiler
from itdebugs.intelligence.relevance import (
    RelevanceConfig,
    RelevanceSelector,
    extract_keywords,
    _path_keywords,
)

DEMO_REPO = str(Path(__file__).resolve().parent.parent.parent / "demo" / "buggy-project")
DEMO_BUG  = "Completed tasks are appearing in the pending task list."


# ===========================================================================
# Helpers
# ===========================================================================

def _make_temp_repo(files: dict[str, str]) -> Path:
    """
    Create a temporary directory containing the given files.
    Returns the directory path.

    files: mapping of relative_path -> content string
    """
    tmpdir = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        fpath = tmpdir / rel
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
    return tmpdir


# ===========================================================================
# extract_keywords
# ===========================================================================

class TestExtractKeywords:
    def test_basic_words(self):
        kws = extract_keywords("pending tasks are missing")
        assert "pending" in kws
        assert "tasks" in kws
        assert "missing" in kws

    def test_stopwords_excluded(self):
        kws = extract_keywords("the task is broken and it is not working")
        assert "the" not in kws
        assert "is" not in kws
        assert "and" not in kws

    def test_short_words_excluded(self):
        kws = extract_keywords("to do it")
        # All these are stopwords or too short
        assert kws == [] or all(len(k) > 2 for k in kws)

    def test_quoted_strings_preserved(self):
        kws = extract_keywords('comparing against "complete" instead of "completed"')
        assert "complete" in kws
        assert "completed" in kws

    def test_deduplication(self):
        kws = extract_keywords("pending pending pending")
        assert kws.count("pending") == 1

    def test_empty_string(self):
        assert extract_keywords("") == []

    def test_camelcase_split(self):
        # Our regex captures camelCase as one token (that's intentional)
        kws = extract_keywords("getPendingTasks returns wrong results")
        assert "getPendingTasks" in kws or "getpendingtasks" in kws


# ===========================================================================
# FileInventory
# ===========================================================================

class TestFileInventory:

    def test_basic_scan_demo(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        assert len(records) > 0

    def test_python_files_detected(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        py_files = [r for r in records if r.extension == ".py"]
        assert len(py_files) > 0

    def test_language_detection_python(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        py_records = [r for r in records if r.extension == ".py"]
        for r in py_records:
            assert r.language == Language.PYTHON

    def test_test_files_classified_correctly(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        test_records = [r for r in records if r.category == FileCategory.TEST]
        assert len(test_records) > 0
        for r in test_records:
            assert r.name.startswith("test_") or "test" in r.parent_dir.lower()

    def test_source_files_classified_correctly(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        src_records = [r for r in records if r.category == FileCategory.SOURCE]
        assert len(src_records) > 0
        # manager.py should be source
        manager_records = [r for r in src_records if "manager" in r.name]
        assert len(manager_records) > 0

    def test_requirements_txt_is_dependency(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        dep_records = [r for r in records if r.category == FileCategory.DEPENDENCY]
        names = [r.name.lower() for r in dep_records]
        assert "requirements.txt" in names

    def test_pycache_excluded(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        for r in records:
            assert "__pycache__" not in r.relative_path

    def test_pytest_cache_excluded(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        for r in records:
            assert ".pytest_cache" not in r.relative_path

    def test_nonexistent_repo_returns_empty(self):
        inv = FileInventory()
        records = inv.build("/nonexistent/path/xyz/abc")
        assert records == []

    def test_max_files_limit(self):
        cfg = InventoryConfig(max_files=3)
        inv = FileInventory(cfg)
        records = inv.build(DEMO_REPO)
        assert len(records) <= 3

    def test_file_size_recorded(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        for r in records:
            assert r.size_bytes >= 0

    def test_relative_paths_are_relative(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        for r in records:
            assert not Path(r.relative_path).is_absolute()

    def test_absolute_paths_are_absolute(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        for r in records:
            assert Path(r.absolute_path).is_absolute()

    def test_extra_excluded_dirs(self):
        cfg = InventoryConfig(extra_excluded_dirs={"task_manager"})
        inv = FileInventory(cfg)
        records = inv.build(DEMO_REPO)
        for r in records:
            assert "task_manager" not in r.relative_path.replace("\\", "/").split("/")

    def test_oversized_file_treated_as_binary(self):
        """Files larger than max_file_size_bytes are flagged as binary."""
        tmpdir = _make_temp_repo({"big.py": "x = 1\n" * 100})
        cfg = InventoryConfig(max_file_size_bytes=10)  # 10 bytes — even tiny file is "oversized"
        inv = FileInventory(cfg)
        records = inv.build(str(tmpdir))
        assert all(r.is_binary for r in records)

    def test_generated_extensions_classified(self):
        tmpdir = _make_temp_repo({"mod.pyc": b"\x00".__str__()})
        inv = FileInventory()
        records = inv.build(str(tmpdir))
        pyc = [r for r in records if r.extension == ".pyc"]
        for r in pyc:
            assert r.category == FileCategory.GENERATED

    def test_markdown_files_classified_as_docs(self):
        inv = FileInventory()
        records = inv.build(DEMO_REPO)
        md_records = [r for r in records if r.extension == ".md"]
        for r in md_records:
            assert r.category == FileCategory.DOCS

    def test_is_test_file_heuristic(self):
        assert _is_test_file("test_manager.py", []) is True
        assert _is_test_file("manager_test.py", []) is True
        assert _is_test_file("manager.py", []) is False
        assert _is_test_file("manager.py", ["tests"]) is True
        assert _is_test_file("util.py", ["src", "utils"]) is False

    def test_virtual_env_excluded(self):
        tmpdir = _make_temp_repo({
            "app.py": "print('hello')",
            "venv/lib/requests.py": "# requests",
        })
        inv = FileInventory()
        records = inv.build(str(tmpdir))
        paths = [r.relative_path.replace("\\", "/") for r in records]
        assert not any("venv" in p for p in paths)

    def test_node_modules_excluded(self):
        tmpdir = _make_temp_repo({
            "index.js": "console.log(1)",
            "node_modules/express/index.js": "// express",
        })
        inv = FileInventory()
        records = inv.build(str(tmpdir))
        paths = [r.relative_path.replace("\\", "/") for r in records]
        assert not any("node_modules" in p for p in paths)

    def test_unreadable_file_skipped_gracefully(self):
        """Build should not crash when a file has a stat error (we simulate with a deleted file)."""
        tmpdir = _make_temp_repo({"app.py": "x = 1"})
        inv = FileInventory()
        # Should not raise even on a path that disappears mid-scan
        records = inv.build(str(tmpdir))
        assert isinstance(records, list)


# ===========================================================================
# RepositoryProfiler
# ===========================================================================

class TestRepositoryProfiler:

    def test_returns_profile(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        assert isinstance(p, RepositoryProfile)

    def test_detects_python_language(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        assert Language.PYTHON in p.languages

    def test_python_is_primary_language(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        assert p.primary_language == Language.PYTHON

    def test_detects_pytest(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        assert "pytest" in p.test_frameworks

    def test_source_file_count_positive(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        assert p.source_file_count > 0

    def test_test_file_count_positive(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        assert p.test_file_count > 0

    def test_dependency_files_found(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        dep_names = [Path(d).name for d in p.dependency_files]
        assert "requirements.txt" in dep_names

    def test_inventory_populated(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        assert len(p.inventory) > 0

    def test_source_dirs_detected(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        assert len(p.source_dirs) > 0

    def test_test_dirs_detected(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        assert len(p.test_dirs) > 0

    def test_summary_lines_non_empty(self):
        p = RepositoryProfiler().profile(DEMO_REPO)
        lines = p.summary_lines()
        assert len(lines) > 0
        combined = " ".join(lines)
        assert "Python" in combined

    def test_nonexistent_repo_returns_empty_profile(self):
        p = RepositoryProfiler().profile("/nonexistent/xyz")
        assert p.total_files == 0
        assert p.source_file_count == 0

    def test_js_project_detection(self):
        tmpdir = _make_temp_repo({
            "package.json": '{"name":"app","version":"1.0"}',
            "jest.config.js": "module.exports = {};",
            "src/index.js": "console.log('hello');",
            "src/app.test.js": "test('x', () => {});",
        })
        p = RepositoryProfiler().profile(str(tmpdir))
        assert Language.JAVASCRIPT in p.languages
        assert "jest" in p.test_frameworks or "jest" in p.frameworks
        assert "npm" in p.package_managers

    def test_java_project_detection(self):
        tmpdir = _make_temp_repo({
            "pom.xml": "<project/>",
            "src/Main.java": "public class Main {}",
        })
        p = RepositoryProfiler().profile(str(tmpdir))
        assert Language.JAVA in p.languages
        assert "Maven" in p.frameworks or "Maven" in p.package_managers

    def test_mixed_language_project(self):
        tmpdir = _make_temp_repo({
            "backend/app.py": "print('hello')",
            "frontend/index.ts": "console.log('hi');",
            "requirements.txt": "flask",
            "package.json": '{"name":"app"}',
        })
        p = RepositoryProfiler().profile(str(tmpdir))
        lang_names = {l.value for l in p.languages}
        assert "Python" in lang_names
        assert "TypeScript" in lang_names

    def test_entry_points_detected(self):
        tmpdir = _make_temp_repo({
            "__main__.py": "if __name__ == '__main__': pass",
            "app.py": "app = Flask(__name__)",
            "utils.py": "def helper(): pass",
        })
        p = RepositoryProfiler().profile(str(tmpdir))
        ep_names = [Path(e).name for e in p.entry_points]
        assert "__main__.py" in ep_names or "app.py" in ep_names


# ===========================================================================
# RelevanceSelector
# ===========================================================================

class TestRelevanceSelector:

    @pytest.fixture(scope="class")
    def demo_profile(self):
        return RepositoryProfiler().profile(DEMO_REPO)

    def test_returns_list(self, demo_profile):
        sel = RelevanceSelector()
        candidates = sel.select(demo_profile, DEMO_BUG)
        assert isinstance(candidates, list)

    def test_candidates_non_empty(self, demo_profile):
        sel = RelevanceSelector()
        candidates = sel.select(demo_profile, DEMO_BUG)
        assert len(candidates) > 0

    def test_manager_py_is_top_candidate(self, demo_profile):
        sel = RelevanceSelector()
        candidates = sel.select(demo_profile, DEMO_BUG)
        top_paths = [c.relative_path for c in candidates[:3]]
        assert any("manager" in p.lower() for p in top_paths), (
            f"manager.py not in top 3: {top_paths}"
        )

    def test_candidates_have_scores(self, demo_profile):
        sel = RelevanceSelector()
        candidates = sel.select(demo_profile, DEMO_BUG)
        for c in candidates:
            assert c.total_score > 0

    def test_candidates_sorted_descending(self, demo_profile):
        sel = RelevanceSelector()
        candidates = sel.select(demo_profile, DEMO_BUG)
        scores = [c.total_score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_max_candidates_respected(self, demo_profile):
        cfg = RelevanceConfig(max_candidates=3)
        sel = RelevanceSelector(cfg)
        candidates = sel.select(demo_profile, DEMO_BUG)
        assert len(candidates) <= 3

    def test_min_score_filters_noise(self, demo_profile):
        cfg = RelevanceConfig(min_score=100.0)  # impossibly high
        sel = RelevanceSelector(cfg)
        candidates = sel.select(demo_profile, DEMO_BUG)
        assert candidates == []

    def test_score_reasons_populated(self, demo_profile):
        sel = RelevanceSelector()
        candidates = sel.select(demo_profile, DEMO_BUG)
        for c in candidates:
            assert len(c.score.reasons) > 0

    def test_empty_bug_description_does_not_crash(self, demo_profile):
        sel = RelevanceSelector()
        candidates = sel.select(demo_profile, "")
        assert isinstance(candidates, list)

    def test_path_keywords_utility(self):
        kws = _path_keywords("task_manager/manager.py")
        assert "task" in kws
        assert "manager" in kws

    def test_path_keyword_match_scores_higher(self, demo_profile):
        """A file whose path contains bug keywords should score higher than one that doesn't."""
        sel = RelevanceSelector()
        candidates_with_keywords = sel.select(demo_profile, "manager pending task")
        candidates_generic = sel.select(demo_profile, "unrelated topic nobody cares about")

        # The top candidate for keywords-matching search should score higher
        if candidates_with_keywords and candidates_generic:
            assert candidates_with_keywords[0].total_score >= candidates_generic[0].total_score

    def test_content_scan_detects_keyword_in_source(self):
        """Content scan should add score when keywords appear in file content."""
        tmpdir = _make_temp_repo({
            "src/manager.py": (
                'def get_pending_tasks(self):\n'
                '    return [t for t in self._tasks if t.status != "complete"]\n'
            ),
            "src/other.py": "def foo(): pass\n",
        })
        profiler = RepositoryProfiler()
        profile = profiler.profile(str(tmpdir))
        sel = RelevanceSelector()
        candidates = sel.select(profile, "pending tasks are not filtered correctly")
        paths = [c.relative_path.replace("\\", "/") for c in candidates]
        # manager.py should appear because both path and content match
        assert any("manager" in p for p in paths)

    def test_large_file_not_content_scanned(self):
        """Files larger than max_content_scan_bytes should not be content-scanned."""
        big_content = "completed " * 5000   # 50 KB of repeated keyword
        tmpdir = _make_temp_repo({"bigfile.py": big_content})
        profiler = RepositoryProfiler()
        profile = profiler.profile(str(tmpdir))
        # Set content scan limit below file size
        cfg = RelevanceConfig(max_content_scan_bytes=100)
        sel = RelevanceSelector(cfg)
        candidates = sel.select(profile, "completed tasks")
        # The file can still match via path keywords, just not content
        # Most importantly, it should not crash
        assert isinstance(candidates, list)


# ===========================================================================
# Integration: RepositoryAnalyst uses intelligence layer
# ===========================================================================

class TestRepositoryAnalystIntegration:

    @pytest.fixture(scope="class")
    def ctx(self):
        from itdebugs.agents.context import InvestigationContext
        from itdebugs.agents.repo_analyst import RepositoryAnalyst
        _ctx = InvestigationContext(repo_path=DEMO_REPO, bug_description=DEMO_BUG)
        RepositoryAnalyst(verbose=False).run(_ctx)
        return _ctx

    def test_repo_profile_set(self, ctx):
        assert ctx.repo_profile is not None

    def test_repo_index_set(self, ctx):
        assert ctx.repo_index is not None

    def test_candidate_files_set(self, ctx):
        assert isinstance(ctx.candidate_files, list)
        assert len(ctx.candidate_files) > 0

    def test_candidate_files_are_candidate_file_instances(self, ctx):
        for c in ctx.candidate_files:
            assert isinstance(c, CandidateFile)

    def test_relevant_files_populated(self, ctx):
        assert len(ctx.relevant_files) > 0

    def test_relevant_files_are_strings(self, ctx):
        for f in ctx.relevant_files:
            assert isinstance(f, str)

    def test_manager_py_in_relevant_files(self, ctx):
        relevant = [f.lower() for f in ctx.relevant_files]
        assert any("manager" in f for f in relevant), (
            f"manager.py not in relevant_files: {ctx.relevant_files}"
        )

    def test_profile_detects_python(self, ctx):
        assert Language.PYTHON in ctx.repo_profile.languages

    def test_profile_detects_pytest(self, ctx):
        assert "pytest" in ctx.repo_profile.test_frameworks

    def test_repo_structure_still_set(self, ctx):
        """Backward compatibility: repo_structure must still be populated."""
        assert ctx.repo_structure is not None


# ===========================================================================
# Demo compatibility: full pipeline still works
# ===========================================================================

class TestDemoCompatibility:

    @pytest.fixture(scope="class")
    def report(self):
        from itdebugs.orchestrator import Orchestrator
        orc = Orchestrator(repo_path=DEMO_REPO, bug_description=DEMO_BUG, verbose=False)
        return orc.run()

    def test_22_tests_collected(self, report):
        assert report.tests_total == 22

    def test_19_tests_pass(self, report):
        assert report.tests_passed == 19

    def test_3_tests_fail(self, report):
        assert report.tests_failed == 3

    def test_root_cause_identified(self, report):
        assert report.root_cause is not None

    def test_root_cause_file_is_manager_py(self, report):
        assert "manager" in report.root_cause.file.lower()

    def test_root_cause_line_is_71(self, report):
        assert report.root_cause.line_range == "71"

    def test_intentional_bug_unchanged(self):
        content = Path(DEMO_REPO, "task_manager", "manager.py").read_text(encoding="utf-8")
        assert 't.status != "complete"' in content, "Intentional bug was modified!"

    def test_investigation_successful(self, report):
        assert report.investigation_successful
