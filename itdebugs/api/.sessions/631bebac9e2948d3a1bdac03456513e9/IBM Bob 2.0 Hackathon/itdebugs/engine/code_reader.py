"""
engine/code_reader.py
=====================
Reads Python source files from a repository and extracts the sections most
relevant to a bug investigation:

  * Full file contents (with line numbers for easy reference)
  * Individual class or function bodies by name
  * Line-range slices
  * Keyword search across source files (grep-style)

No AST parsing — uses only line-by-line text analysis so it works even on
files with syntax errors (which is important when investigating broken code).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SourceFile:
    """Contents and metadata for a single source file."""
    relative_path: str
    absolute_path: str
    lines: List[str]           # raw lines, 0-indexed; line N is lines[N-1]
    total_lines: int

    @property
    def content(self) -> str:
        return "".join(self.lines)

    def get_range(self, start: int, end: int) -> str:
        """Return lines[start-1 : end] with line numbers prepended."""
        sliced = self.lines[start - 1: end]
        return "".join(
            f"{start + i:4d} | {line}"
            for i, line in enumerate(sliced)
        )

    def numbered(self) -> str:
        """Return the entire file with line numbers prepended."""
        return self.get_range(1, self.total_lines)


@dataclass
class CodeMatch:
    """A single grep-style match inside a source file."""
    file: str           # relative path
    line_number: int    # 1-based
    line_text: str      # raw line content


@dataclass
class ExtractedBlock:
    """A named block (function / class / method) extracted from a file."""
    file: str
    name: str
    start_line: int
    end_line: int
    source: str         # the block text with line numbers


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _read_file(path: Path, repo_root: Path) -> SourceFile:
    """Read a file and return a :class:`SourceFile`."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    return SourceFile(
        relative_path=str(path.relative_to(repo_root)),
        absolute_path=str(path),
        lines=lines,
        total_lines=len(lines),
    )


def _find_block_end(lines: List[str], start_index: int) -> int:
    """
    Given the 0-based index of a ``def`` or ``class`` line, return the
    0-based index of its last line using indentation heuristics.

    Works for top-level functions, methods inside classes, and nested
    functions.  Does NOT require valid AST.
    """
    if start_index >= len(lines):
        return start_index

    # Determine the indentation level of the definition line
    def_line = lines[start_index]
    base_indent = len(def_line) - len(def_line.lstrip())

    end = start_index
    i = start_index + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "":
            # blank lines are part of the block
            i += 1
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= base_indent and stripped:
            # We've returned to the same or outer indentation level
            break
        end = i
        i += 1

    return end


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_file(repo_root: str | Path, relative_path: str) -> SourceFile:
    """Read a single file relative to *repo_root*."""
    root = Path(repo_root).resolve()
    full = root / relative_path
    if not full.exists():
        raise FileNotFoundError(f"File not found: {full}")
    return _read_file(full, root)


def read_files(repo_root: str | Path, relative_paths: List[str]) -> Dict[str, SourceFile]:
    """Read multiple files and return a mapping of relative_path → SourceFile."""
    root = Path(repo_root).resolve()
    result: Dict[str, SourceFile] = {}
    for rp in relative_paths:
        full = root / rp
        if full.exists():
            result[rp] = _read_file(full, root)
    return result


def grep(
    repo_root: str | Path,
    pattern: str,
    paths: Optional[List[str]] = None,
    ignore_case: bool = True,
) -> List[CodeMatch]:
    """
    Search for *pattern* (regex) in the given *paths* (relative to
    *repo_root*).  If *paths* is None, searches all ``*.py`` files under
    *repo_root*.

    Returns a list of :class:`CodeMatch` objects, one per matching line.
    """
    root = Path(repo_root).resolve()
    flags = re.IGNORECASE if ignore_case else 0
    compiled = re.compile(pattern, flags)

    if paths is None:
        search_files = list(root.rglob("*.py"))
    else:
        search_files = [root / p for p in paths]

    matches: List[CodeMatch] = []
    for fpath in search_files:
        if not fpath.exists():
            continue
        try:
            text_lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(text_lines, start=1):
            if compiled.search(line):
                matches.append(CodeMatch(
                    file=str(fpath.relative_to(root)),
                    line_number=lineno,
                    line_text=line.rstrip(),
                ))

    return matches


def extract_block(
    repo_root: str | Path,
    relative_path: str,
    name: str,
) -> Optional[ExtractedBlock]:
    """
    Locate the first ``def <name>`` or ``class <name>`` in *relative_path*
    and return its full body as an :class:`ExtractedBlock`.

    Returns None if the name is not found.
    """
    root = Path(repo_root).resolve()
    full = root / relative_path
    if not full.exists():
        return None

    src = _read_file(full, root)
    pattern = re.compile(r"^\s*(def|class)\s+" + re.escape(name) + r"\b")

    for i, line in enumerate(src.lines):
        if pattern.match(line):
            end_i = _find_block_end(src.lines, i)
            start_line = i + 1       # convert to 1-based
            end_line = end_i + 1
            return ExtractedBlock(
                file=relative_path,
                name=name,
                start_line=start_line,
                end_line=end_line,
                source=src.get_range(start_line, end_line),
            )

    return None


def extract_relevant_sections(
    repo_root: str | Path,
    source_file: str,
    keywords: List[str],
    context_lines: int = 5,
) -> List[Tuple[int, str]]:
    """
    For each line in *source_file* that contains any of *keywords*, return a
    tuple of (line_number, context_snippet).  Useful for quickly surfacing
    lines relevant to a bug description without reading the whole file.
    """
    root = Path(repo_root).resolve()
    full = root / source_file
    if not full.exists():
        return []

    src = _read_file(full, root)
    results: List[Tuple[int, str]] = []
    seen_ranges: set[Tuple[int, int]] = set()

    for i, line in enumerate(src.lines):
        if any(kw.lower() in line.lower() for kw in keywords):
            start = max(1, i + 1 - context_lines)
            end = min(src.total_lines, i + 1 + context_lines)
            span = (start, end)
            if span not in seen_ranges:
                seen_ranges.add(span)
                results.append((i + 1, src.get_range(start, end)))

    return results
