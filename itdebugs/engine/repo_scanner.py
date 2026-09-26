"""
engine/repo_scanner.py
======================
Inspects a repository directory and returns structured metadata:
  - directory tree
  - Python source files
  - test files
  - package structure
  - README / requirements files

No external dependencies — uses only pathlib and the standard library.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    """Lightweight descriptor for a single file."""
    path: Path
    relative_path: str          # relative to repo_root
    size_bytes: int
    is_test: bool = False
    is_source: bool = False

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class RepoStructure:
    """All structural metadata discovered about a repository."""
    root: Path
    python_files: List[FileInfo] = field(default_factory=list)
    test_files: List[FileInfo] = field(default_factory=list)
    source_files: List[FileInfo] = field(default_factory=list)   # non-test Python
    config_files: List[FileInfo] = field(default_factory=list)   # requirements.txt, setup.py, pyproject.toml
    readme_files: List[FileInfo] = field(default_factory=list)
    package_dirs: List[str] = field(default_factory=list)        # dirs containing __init__.py
    directory_tree: str = ""

    # Convenience: all file paths as strings
    @property
    def all_python_paths(self) -> List[str]:
        return [f.relative_path for f in self.python_files]

    @property
    def test_paths(self) -> List[str]:
        return [f.relative_path for f in self.test_files]

    @property
    def source_paths(self) -> List[str]:
        return [f.relative_path for f in self.source_files]


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

_IGNORED_DIRS = {
    "__pycache__", ".git", ".hg", ".svn", ".tox", ".venv", "venv",
    "env", ".env", "node_modules", ".pytest_cache", ".mypy_cache",
    "dist", "build", "*.egg-info",
}

_CONFIG_NAMES = {
    "requirements.txt", "requirements-dev.txt", "setup.py", "setup.cfg",
    "pyproject.toml", "tox.ini", "Makefile",
}

_README_PREFIXES = {"readme", "README"}


def _is_ignored(path: Path) -> bool:
    """Return True if any component of the path should be skipped."""
    for part in path.parts:
        if part in _IGNORED_DIRS or part.endswith(".egg-info"):
            return True
    return False


def _is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def _build_tree(root: Path, prefix: str = "", max_depth: int = 6, _depth: int = 0) -> str:
    """Recursively build an ASCII directory tree string (pure ASCII, Windows-safe)."""
    if _depth > max_depth:
        return ""
    lines: List[str] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return ""

    visible = [e for e in entries if not _is_ignored(e)]
    for i, entry in enumerate(visible):
        connector = "+-- " if i == len(visible) - 1 else "+-- "
        lines.append(f"{prefix}{connector}{entry.name}")
        if entry.is_dir():
            extension = "    " if i == len(visible) - 1 else "|   "
            subtree = _build_tree(entry, prefix + extension, max_depth, _depth + 1)
            if subtree:
                lines.append(subtree)
    return "\n".join(lines)


def scan_repository(repo_path: str | Path) -> RepoStructure:
    """
    Walk *repo_path* and return a :class:`RepoStructure` describing everything
    the investigation engine needs to know about the project layout.
    """
    root = Path(repo_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Repository path is not a directory: {root}")

    structure = RepoStructure(root=root)
    structure.directory_tree = f"{root.name}/\n" + _build_tree(root)

    package_candidates: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)

        # Prune ignored directories in-place so os.walk doesn't recurse into them
        dirnames[:] = [
            d for d in dirnames
            if not _is_ignored(current / d)
        ]

        # Detect Python packages
        if "__init__.py" in filenames:
            rel_dir = str(current.relative_to(root))
            package_candidates.add(rel_dir)

        for fname in filenames:
            fpath = current / fname
            rel = str(fpath.relative_to(root))

            if _is_ignored(fpath):
                continue

            size = fpath.stat().st_size
            fi = FileInfo(path=fpath, relative_path=rel, size_bytes=size)

            if fname.endswith(".py"):
                fi.is_source = True
                structure.python_files.append(fi)
                if _is_test_file(fpath):
                    fi.is_test = True
                    structure.test_files.append(fi)
                else:
                    structure.source_files.append(fi)

            elif fname in _CONFIG_NAMES:
                structure.config_files.append(fi)

            elif any(fname.startswith(p) for p in _README_PREFIXES) and fname.endswith(".md"):
                structure.readme_files.append(fi)

    structure.package_dirs = sorted(package_candidates)
    return structure


def find_test_directories(structure: RepoStructure) -> List[str]:
    """
    Return a deduplicated list of directory paths (relative to repo root)
    that contain test files — suitable for passing directly to pytest.
    """
    dirs: set[str] = set()
    for fi in structure.test_files:
        parent = str(Path(fi.relative_path).parent)
        dirs.add(parent)
    return sorted(dirs)
