"""
itdebugs/intelligence/profiler.py
==================================
Repository Profiler.

Inspects a repository and produces a :class:`RepositoryProfile` describing
the technology stack, project structure, and key files.

Design principles
-----------------
* Uses ONLY file names and directory structure — does NOT read file contents
  during profiling.  Content scanning is delegated to the relevance layer.
* Respects the configurable exclusion list.
* Fails gracefully: permission errors, unreadable paths, and oversized trees
  are skipped with a note rather than crashing.
* Extensible: add new language / framework detectors by extending the
  mapping dictionaries at the bottom of this module.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set

from itdebugs.intelligence.models import (
    FileCategory,
    FileRecord,
    Language,
    RepositoryProfile,
)
from itdebugs.intelligence.inventory import FileInventory, InventoryConfig

# ---------------------------------------------------------------------------
# Language detection by file extension
# ---------------------------------------------------------------------------

_EXT_TO_LANGUAGE: Dict[str, Language] = {
    ".py":    Language.PYTHON,
    ".pyw":   Language.PYTHON,
    ".js":    Language.JAVASCRIPT,
    ".mjs":   Language.JAVASCRIPT,
    ".cjs":   Language.JAVASCRIPT,
    ".jsx":   Language.JAVASCRIPT,
    ".ts":    Language.TYPESCRIPT,
    ".tsx":   Language.TYPESCRIPT,
    ".java":  Language.JAVA,
    ".kt":    Language.KOTLIN,
    ".kts":   Language.KOTLIN,
    ".go":    Language.GO,
    ".rs":    Language.RUST,
    ".rb":    Language.RUBY,
    ".cs":    Language.CSHARP,
    ".cpp":   Language.CPP,
    ".cxx":   Language.CPP,
    ".cc":    Language.CPP,
    ".c":     Language.CPP,
    ".h":     Language.CPP,
    ".hpp":   Language.CPP,
}

# ---------------------------------------------------------------------------
# Framework / tool detection by filename / content prefix
# ---------------------------------------------------------------------------

# Maps a filename (or glob-like pattern) to detected framework names.
# Key: exact filename (case-insensitive).
_FILENAME_TO_FRAMEWORKS: Dict[str, List[str]] = {
    # Python test frameworks
    "pytest.ini":       ["pytest"],
    "setup.cfg":        ["pytest"],       # may contain [tool:pytest]
    "pyproject.toml":   ["pytest"],       # may contain [tool.pytest.ini_options]
    "tox.ini":          ["tox", "pytest"],
    # Python web frameworks (entry point hints)
    "app.py":           ["Flask"],
    "wsgi.py":          ["WSGI"],
    "asgi.py":          ["ASGI"],
    # JS/TS test frameworks
    "jest.config.js":   ["jest"],
    "jest.config.ts":   ["jest"],
    "jest.config.mjs":  ["jest"],
    "vitest.config.ts": ["vitest"],
    "vitest.config.js": ["vitest"],
    ".mocharc.js":      ["mocha"],
    ".mocharc.yml":     ["mocha"],
    "jasmine.json":     ["jasmine"],
    # JS build tools
    "vite.config.ts":   ["vite"],
    "vite.config.js":   ["vite"],
    "webpack.config.js":["webpack"],
    "next.config.js":   ["Next.js"],
    "next.config.ts":   ["Next.js"],
    "nuxt.config.ts":   ["Nuxt"],
    # Java build systems
    "pom.xml":          ["Maven"],
    "build.gradle":     ["Gradle"],
    "build.gradle.kts": ["Gradle"],
    # Go modules
    "go.mod":           ["Go modules"],
    # Rust
    "Cargo.toml":       ["Cargo"],
    # Ruby
    "Gemfile":          ["Bundler"],
    "Rakefile":         ["Rake"],
    ".rspec":           ["RSpec"],
    "spec_helper.rb":   ["RSpec"],
    # Docker
    "Dockerfile":       ["Docker"],
    "docker-compose.yml": ["Docker Compose"],
    "docker-compose.yaml": ["Docker Compose"],
}

# Dependency / package manager files
_DEPENDENCY_FILENAMES: Set[str] = {
    # Python
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
    "requirements-prod.txt", "pyproject.toml", "setup.py", "setup.cfg",
    "Pipfile", "Pipfile.lock", "poetry.lock",
    # JavaScript / TypeScript
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    # Java
    "pom.xml", "build.gradle", "build.gradle.kts",
    # Go
    "go.mod", "go.sum",
    # Rust
    "Cargo.toml", "Cargo.lock",
    # Ruby
    "Gemfile", "Gemfile.lock",
    # .NET
    "*.csproj", "*.fsproj", "packages.config", "NuGet.Config",
}

# Package manager names by their manifest file
_MANIFEST_TO_PKG_MANAGER: Dict[str, str] = {
    "requirements.txt": "pip",
    "requirements-dev.txt": "pip",
    "pyproject.toml": "pip/poetry/uv",
    "setup.py": "pip",
    "Pipfile": "pipenv",
    "poetry.lock": "poetry",
    "package.json": "npm",
    "package-lock.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "pom.xml": "Maven",
    "build.gradle": "Gradle",
    "build.gradle.kts": "Gradle",
    "go.mod": "go modules",
    "Cargo.toml": "cargo",
    "Gemfile": "bundler",
}

# Test framework names by file pattern
_TEST_FRAMEWORK_BY_FILE: Dict[str, str] = {
    "pytest.ini": "pytest",
    "tox.ini": "pytest/tox",
    "jest.config.js": "jest",
    "jest.config.ts": "jest",
    "vitest.config.ts": "vitest",
    ".mocharc.js": "mocha",
    ".mocharc.yml": "mocha",
    "jasmine.json": "jasmine",
    ".rspec": "rspec",
    "spec_helper.rb": "rspec",
}

# Likely entry point filenames
_ENTRY_POINT_NAMES: Set[str] = {
    "__main__.py", "main.py", "app.py", "server.py", "wsgi.py", "asgi.py",
    "index.js", "index.ts", "main.js", "main.ts", "server.js", "server.ts",
    "Main.java", "Application.java", "main.go",
}


# ---------------------------------------------------------------------------
# Profiler
# ---------------------------------------------------------------------------

class RepositoryProfiler:
    """
    Inspects a repository and produces a :class:`RepositoryProfile`.

    Parameters
    ----------
    config:
        Optional :class:`InventoryConfig` controlling exclusions and limits.
        Defaults to sensible values if not supplied.
    """

    def __init__(self, config: Optional[InventoryConfig] = None) -> None:
        self._config = config or InventoryConfig()

    def profile(self, repo_path: str) -> RepositoryProfile:
        """
        Build and return a :class:`RepositoryProfile` for *repo_path*.

        Never raises — errors are silently skipped and noted in
        ``profile.excluded_dirs``.
        """
        root = Path(repo_path).resolve()
        pr = RepositoryProfile(repo_path=str(root))

        # Step 1: build file inventory
        inventory = FileInventory(self._config)
        records = inventory.build(repo_path)
        pr.inventory = records
        pr.excluded_dirs = inventory.excluded_dirs

        # Step 2: count by category
        pr.total_files = len(records)
        pr.source_file_count = sum(1 for r in records if r.category == FileCategory.SOURCE)
        pr.test_file_count = sum(1 for r in records if r.category == FileCategory.TEST)
        pr.config_file_count = sum(1 for r in records if r.category == FileCategory.CONFIG)
        pr.doc_file_count = sum(1 for r in records if r.category == FileCategory.DOCS)

        # Step 3: detect languages
        lang_counter: Counter[Language] = Counter()
        for rec in records:
            if rec.language != Language.UNKNOWN and rec.category in (
                FileCategory.SOURCE, FileCategory.TEST
            ):
                lang_counter[rec.language] += 1
        pr.languages = [lang for lang, _ in lang_counter.most_common()]
        pr.primary_language = pr.languages[0] if pr.languages else None

        # Step 4: detect frameworks / tools from filenames
        frameworks: Set[str] = set()
        test_frameworks: Set[str] = set()
        pkg_managers: Set[str] = set()
        dep_files: List[str] = []
        cfg_files: List[str] = []
        entry_points: List[str] = []

        for rec in records:
            fname = rec.name.lower()
            fname_orig = rec.name  # preserve case for display

            # Dependency files
            if fname in {d.lower() for d in _DEPENDENCY_FILENAMES}:
                dep_files.append(rec.relative_path)
                pm = _MANIFEST_TO_PKG_MANAGER.get(fname_orig) or _MANIFEST_TO_PKG_MANAGER.get(fname)
                if pm:
                    pkg_managers.add(pm)

            # Framework signals from filenames
            fw_list = _FILENAME_TO_FRAMEWORKS.get(fname_orig) or _FILENAME_TO_FRAMEWORKS.get(fname)
            if fw_list:
                frameworks.update(fw_list)

            # Test framework signals
            tf = _TEST_FRAMEWORK_BY_FILE.get(fname_orig) or _TEST_FRAMEWORK_BY_FILE.get(fname)
            if tf:
                test_frameworks.add(tf)

            # Config files
            if rec.category == FileCategory.CONFIG:
                cfg_files.append(rec.relative_path)

            # Entry points
            if fname_orig in _ENTRY_POINT_NAMES or fname in {e.lower() for e in _ENTRY_POINT_NAMES}:
                entry_points.append(rec.relative_path)

        # Infer test framework from language if not found from files
        if not test_frameworks:
            if Language.PYTHON in pr.languages:
                test_frameworks.add("pytest")  # default for Python projects

        # Separate test frameworks out of general frameworks list
        general_frameworks = frameworks - test_frameworks
        pr.frameworks = sorted(general_frameworks)
        pr.test_frameworks = sorted(test_frameworks)
        pr.package_managers = sorted(pkg_managers)
        pr.dependency_files = dep_files[:10]
        pr.config_files = cfg_files[:20]
        pr.entry_points = entry_points[:5]

        # Step 5: derive source and test directories
        src_dir_counter: Counter[str] = Counter()
        test_dir_counter: Counter[str] = Counter()
        for rec in records:
            parent = rec.parent_dir
            if rec.category == FileCategory.SOURCE:
                top = parent.split(os.sep)[0] if os.sep in parent else parent
                top = top.split("/")[0] if "/" in top else top
                if top and top != ".":
                    src_dir_counter[top] += 1
            elif rec.category == FileCategory.TEST:
                top = parent.split(os.sep)[0] if os.sep in parent else parent
                top = top.split("/")[0] if "/" in top else top
                if top and top != ".":
                    test_dir_counter[top] += 1

        pr.source_dirs = [d for d, _ in src_dir_counter.most_common(5)]
        pr.test_dirs = [d for d, _ in test_dir_counter.most_common(5)]

        return pr
