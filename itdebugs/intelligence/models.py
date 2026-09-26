"""
itdebugs/intelligence/models.py
================================
Structured data models for the Repository Intelligence layer.

These dataclasses are the contract between:
  - Repository profiling (profiler.py)
  - File inventory (inventory.py)
  - Relevance selection (relevance.py)
  - The investigation agents that consume the results

All models are plain dataclasses — no external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class FileCategory(str, Enum):
    """Logical category assigned to each file during inventory."""
    SOURCE      = "source"       # application / library source code
    TEST        = "test"         # test files (test_*.py, *.spec.ts, etc.)
    CONFIG      = "config"       # project configuration (pyproject.toml, tsconfig.json, …)
    DEPENDENCY  = "dependency"   # package manager manifests (requirements.txt, package.json, …)
    DOCS        = "docs"         # README, markdown, documentation
    GENERATED   = "generated"    # build artifacts, compiled output, coverage reports
    UNKNOWN     = "unknown"      # could not classify


class Language(str, Enum):
    PYTHON      = "Python"
    JAVASCRIPT  = "JavaScript"
    TYPESCRIPT  = "TypeScript"
    JAVA        = "Java"
    KOTLIN      = "Kotlin"
    GO          = "Go"
    RUST        = "Rust"
    RUBY        = "Ruby"
    CSHARP      = "C#"
    CPP         = "C++"
    UNKNOWN     = "unknown"


# ---------------------------------------------------------------------------
# File record (from inventory)
# ---------------------------------------------------------------------------

@dataclass
class FileRecord:
    """
    Lightweight metadata for a single file in the repository.

    Full content is NOT stored here.  The record is cheap to create and
    safe to accumulate for large repositories.
    """
    relative_path: str          # path relative to repository root
    absolute_path: str          # absolute path (for reading later if needed)
    size_bytes: int
    extension: str              # lowercase, e.g. ".py"
    language: Language          # detected from extension
    category: FileCategory
    is_binary: bool = False     # True if file appears to be binary

    @property
    def name(self) -> str:
        return Path(self.relative_path).name

    @property
    def parent_dir(self) -> str:
        return str(Path(self.relative_path).parent)

    @property
    def size_kb(self) -> float:
        return self.size_bytes / 1024


# ---------------------------------------------------------------------------
# Repository profile
# ---------------------------------------------------------------------------

@dataclass
class RepositoryProfile:
    """
    High-level description of a repository's structure and technology stack.

    Produced by :class:`itdebugs.intelligence.profiler.RepositoryProfiler`.
    Consumed by :class:`itdebugs.intelligence.relevance.RelevanceSelector`
    and displayed in the CLI summary.
    """
    repo_path: str

    # Counts
    total_files: int = 0
    source_file_count: int = 0
    test_file_count: int = 0
    config_file_count: int = 0
    doc_file_count: int = 0

    # Technology stack
    languages: List[Language] = field(default_factory=list)       # detected languages, ordered by file count
    primary_language: Optional[Language] = None                    # most common language
    frameworks: List[str] = field(default_factory=list)            # e.g. ["pytest", "FastAPI"]
    test_frameworks: List[str] = field(default_factory=list)       # e.g. ["pytest", "jest"]
    package_managers: List[str] = field(default_factory=list)      # e.g. ["pip", "npm"]

    # Key files
    dependency_files: List[str] = field(default_factory=list)      # relative paths
    config_files: List[str] = field(default_factory=list)          # relative paths
    entry_points: List[str] = field(default_factory=list)          # likely __main__ / index files

    # Directory structure
    source_dirs: List[str] = field(default_factory=list)           # likely source roots
    test_dirs: List[str] = field(default_factory=list)             # likely test roots
    excluded_dirs: List[str] = field(default_factory=list)         # dirs skipped during scan

    # Raw inventory for downstream use
    inventory: List[FileRecord] = field(default_factory=list)

    def summary_lines(self) -> List[str]:
        """Return a short human-readable summary (for CLI display)."""
        lines: List[str] = []
        lang_str = ", ".join(l.value for l in self.languages) if self.languages else "unknown"
        fw_str = ", ".join(self.frameworks) if self.frameworks else "none detected"
        tf_str = ", ".join(self.test_frameworks) if self.test_frameworks else "none detected"
        pm_str = ", ".join(self.package_managers) if self.package_managers else "none detected"
        dep_str = ", ".join(self.dependency_files[:3]) if self.dependency_files else "none"

        lines.append(f"  Languages     : {lang_str}")
        lines.append(f"  Frameworks    : {fw_str}")
        lines.append(f"  Test framework: {tf_str}")
        lines.append(f"  Pkg managers  : {pm_str}")
        lines.append(f"  Source files  : {self.source_file_count}")
        lines.append(f"  Test files    : {self.test_file_count}")
        lines.append(f"  Dependencies  : {dep_str}")
        return lines


# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------

@dataclass
class RelevanceScore:
    """
    Detailed breakdown of why a file received its score.
    """
    file_path: str
    total_score: float
    reasons: List[str] = field(default_factory=list)   # human-readable signal descriptions

    def add(self, points: float, reason: str) -> None:
        self.total_score += points
        self.reasons.append(f"+{points:.1f}: {reason}")


@dataclass
class CandidateFile:
    """
    A file selected for deeper investigation, with its relevance score.
    """
    record: FileRecord
    score: RelevanceScore

    @property
    def relative_path(self) -> str:
        return self.record.relative_path

    @property
    def total_score(self) -> float:
        return self.score.total_score


# ---------------------------------------------------------------------------
# Repository index (complete intelligence output)
# ---------------------------------------------------------------------------

@dataclass
class RepositoryIndex:
    """
    The complete output of a Repository Intelligence run.

    Contains the profile, full inventory, and selected candidate files.
    This is the primary object passed from RepositoryAnalyst to downstream agents.
    """
    profile: RepositoryProfile
    candidates: List[CandidateFile] = field(default_factory=list)

    @property
    def candidate_paths(self) -> List[str]:
        return [c.relative_path for c in self.candidates]

    @property
    def top_candidate(self) -> Optional[CandidateFile]:
        return self.candidates[0] if self.candidates else None
