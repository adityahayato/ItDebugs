"""
itdebugs/intelligence/inventory.py
====================================
File Inventory builder.

Walks a repository directory and produces a list of :class:`FileRecord`
objects containing lightweight per-file metadata.

Large-repository safety
-----------------------
* Configurable exclusion list for generated/vendor/cache directories.
* Maximum total file count (stops walking at the limit).
* Maximum file size before marking a file as oversized/skipped.
* Binary file detection via a quick null-byte sniff on the first 512 bytes.
* Permission errors are silently skipped.
* All limits are configurable via :class:`InventoryConfig`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from itdebugs.intelligence.models import FileCategory, FileRecord, Language


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default set of directory names to exclude during traversal
_DEFAULT_EXCLUDED_DIRS: Set[str] = {
    # Version control
    ".git", ".hg", ".svn",
    # Python
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".venv", "venv", "env", ".env",
    # JavaScript / Node
    "node_modules", ".next", ".nuxt", ".turbo",
    # Build output
    "dist", "build", "out", "target", "_build", ".build",
    "coverage", ".coverage", "htmlcov",
    # Java
    ".gradle", ".idea", ".classpath",
    # IDE
    ".vscode", ".idea", ".eclipse",
    # Package caches
    ".pip", ".cache", ".yarn",
    # Generated / vendor
    "vendor", "third_party", "extern", "generated",
    # Egg info
}


@dataclass
class InventoryConfig:
    """
    Configuration for the file inventory builder.

    All limits have conservative defaults suitable for a medium-large
    repository.  Adjust them for very large monorepos.
    """
    # Extra dirs to exclude in addition to the default set
    extra_excluded_dirs: Set[str] = field(default_factory=set)

    # Stop after collecting this many files (prevents runaway on giant repos)
    max_files: int = 5000

    # Files larger than this will be recorded but marked as binary/oversized
    # and will NOT have their content read by the relevance layer.
    max_file_size_bytes: int = 2 * 1024 * 1024  # 2 MB

    # Walk no deeper than this many directory levels
    max_depth: int = 12

    # Whether to record binary files (they are never read for content)
    include_binary: bool = False

    @property
    def excluded_dirs(self) -> Set[str]:
        return _DEFAULT_EXCLUDED_DIRS | self.extra_excluded_dirs


# ---------------------------------------------------------------------------
# Language detection by extension
# ---------------------------------------------------------------------------

_EXT_TO_LANGUAGE: dict[str, Language] = {
    ".py":   Language.PYTHON,
    ".pyw":  Language.PYTHON,
    ".js":   Language.JAVASCRIPT,
    ".mjs":  Language.JAVASCRIPT,
    ".cjs":  Language.JAVASCRIPT,
    ".jsx":  Language.JAVASCRIPT,
    ".ts":   Language.TYPESCRIPT,
    ".tsx":  Language.TYPESCRIPT,
    ".java": Language.JAVA,
    ".kt":   Language.KOTLIN,
    ".kts":  Language.KOTLIN,
    ".go":   Language.GO,
    ".rs":   Language.RUST,
    ".rb":   Language.RUBY,
    ".cs":   Language.CSHARP,
    ".cpp":  Language.CPP,
    ".cxx":  Language.CPP,
    ".cc":   Language.CPP,
    ".c":    Language.CPP,
    ".h":    Language.CPP,
    ".hpp":  Language.CPP,
}

# ---------------------------------------------------------------------------
# Category detection
# ---------------------------------------------------------------------------

# Source directories that should NOT be classified as source
_NON_SOURCE_DIRS: Set[str] = {"test", "tests", "spec", "specs", "__tests__", "e2e"}

# Config / dependency filenames
_CONFIG_NAMES: Set[str] = {
    "pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini",
    ".flake8", ".pylintrc", "mypy.ini", ".mypy.ini", "ruff.toml",
    "tsconfig.json", "jsconfig.json", ".babelrc", ".eslintrc",
    ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
    ".prettierrc", ".prettierrc.json", ".prettierrc.yml",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Makefile",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".dockerignore", ".gitignore", ".gitattributes",
    "Procfile", ".env.example", "Makefile",
}

_DEPENDENCY_NAMES: Set[str] = {
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
    "requirements-prod.txt", "Pipfile", "Pipfile.lock", "poetry.lock",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Gemfile", "Gemfile.lock", "composer.json", "composer.lock",
    "go.mod",  # also a config, treated as dependency
}

_DOC_EXTENSIONS: Set[str] = {".md", ".rst", ".txt", ".adoc", ".rdoc"}
_DOC_NAMES: Set[str] = {"readme", "changelog", "contributing", "license", "authors", "history"}

_GENERATED_DIRS: Set[str] = {"dist", "build", "out", "coverage", "htmlcov", ".next", "target"}
_GENERATED_EXTENSIONS: Set[str] = {
    ".pyc", ".pyo", ".class", ".jar", ".war", ".o", ".obj",
    ".exe", ".dll", ".so", ".dylib", ".a",
    ".min.js", ".min.css", ".map",
}


def _detect_language(ext: str) -> Language:
    return _EXT_TO_LANGUAGE.get(ext.lower(), Language.UNKNOWN)


def _is_test_file(fname: str, parent_parts: List[str]) -> bool:
    """Heuristic: file is a test if its name starts with test_ or ends with
    _test, or lives in a test/spec directory."""
    lower = fname.lower()
    if lower.startswith("test_") or lower.endswith("_test.py"):
        return True
    if lower.startswith("spec_") or lower.endswith(".spec.ts") or lower.endswith(".spec.js"):
        return True
    if lower.endswith(".test.ts") or lower.endswith(".test.js"):
        return True
    # Check parent directories
    lower_parts = {p.lower() for p in parent_parts}
    return bool(lower_parts & _NON_SOURCE_DIRS)


def _is_binary(path: Path, max_bytes: int = 512) -> bool:
    """Quick binary detection: check first max_bytes for null bytes."""
    try:
        with path.open("rb") as fh:
            chunk = fh.read(max_bytes)
        return b"\x00" in chunk
    except OSError:
        return False


def _classify(
    fname: str,
    ext: str,
    parent_parts: List[str],
    rel_path: str,
) -> FileCategory:
    """Assign a :class:`FileCategory` to a file."""
    lower = fname.lower()
    lower_ext = ext.lower()

    # Generated / build artifacts
    if lower_ext in _GENERATED_EXTENSIONS:
        return FileCategory.GENERATED
    top_dir = parent_parts[0].lower() if parent_parts else ""
    if top_dir in _GENERATED_DIRS:
        return FileCategory.GENERATED

    # Documentation
    if lower_ext in _DOC_EXTENSIONS:
        stem = Path(fname).stem.lower()
        if stem in _DOC_NAMES or lower_ext in {".md", ".rst"}:
            return FileCategory.DOCS

    # Dependency manifests (checked before config because some overlap)
    if lower in _DEPENDENCY_NAMES:
        return FileCategory.DEPENDENCY

    # Config files
    if lower in {c.lower() for c in _CONFIG_NAMES}:
        return FileCategory.CONFIG

    # Source / test
    if _detect_language(lower_ext) != Language.UNKNOWN:
        if _is_test_file(fname, parent_parts):
            return FileCategory.TEST
        return FileCategory.SOURCE

    return FileCategory.UNKNOWN


# ---------------------------------------------------------------------------
# FileInventory
# ---------------------------------------------------------------------------

class FileInventory:
    """
    Builds a lightweight :class:`FileRecord` list for a repository.

    Parameters
    ----------
    config:
        :class:`InventoryConfig` controlling exclusions, limits, and behaviour.
    """

    def __init__(self, config: Optional[InventoryConfig] = None) -> None:
        self._config = config or InventoryConfig()
        self.excluded_dirs: List[str] = []   # dirs that were skipped

    def build(self, repo_path: str) -> List[FileRecord]:
        """
        Walk *repo_path* and return a list of :class:`FileRecord` objects.

        Respects all limits in :attr:`_config`.  Never raises.
        """
        root = Path(repo_path).resolve()
        if not root.exists():
            return []

        cfg = self._config
        records: List[FileRecord] = []
        excluded: List[str] = []

        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            depth = len(current.relative_to(root).parts)

            # Depth limit
            if depth > cfg.max_depth:
                dirnames.clear()
                continue

            # Prune excluded directories in-place
            to_remove = []
            for d in dirnames:
                if d in cfg.excluded_dirs or d.endswith(".egg-info"):
                    to_remove.append(d)
                    try:
                        rel = str((current / d).relative_to(root))
                    except ValueError:
                        rel = d
                    excluded.append(rel)
            for d in to_remove:
                dirnames.remove(d)

            # File count limit
            if len(records) >= cfg.max_files:
                dirnames.clear()
                break

            # Compute parent parts for category classification
            try:
                rel_dir = current.relative_to(root)
                parent_parts = list(rel_dir.parts)
            except ValueError:
                parent_parts = []

            for fname in filenames:
                if len(records) >= cfg.max_files:
                    break

                fpath = current / fname
                try:
                    size = fpath.stat().st_size
                except OSError:
                    continue

                ext = fpath.suffix  # e.g. ".py"
                rel = str(fpath.relative_to(root))
                language = _detect_language(ext)

                # Skip binary files unless configured to include them
                is_binary = False
                if size > 0 and size <= cfg.max_file_size_bytes:
                    is_binary = _is_binary(fpath)
                elif size > cfg.max_file_size_bytes:
                    is_binary = True  # treat oversized as binary (won't be read)

                if is_binary and not cfg.include_binary:
                    continue

                category = _classify(fname, ext, parent_parts, rel)

                records.append(FileRecord(
                    relative_path=rel,
                    absolute_path=str(fpath),
                    size_bytes=size,
                    extension=ext.lower(),
                    language=language,
                    category=category,
                    is_binary=is_binary,
                ))

        self.excluded_dirs = excluded
        return records
