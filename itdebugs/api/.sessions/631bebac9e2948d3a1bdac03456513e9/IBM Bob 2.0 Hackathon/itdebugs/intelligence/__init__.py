"""
itdebugs.intelligence
======================
Repository Intelligence layer for ItDebugs.

Provides repository profiling, file inventory, and bug-description
relevance selection — suitable for repositories of any size.

Quick usage
-----------
    from itdebugs.intelligence import RepositoryProfiler, RelevanceSelector

    profiler = RepositoryProfiler()
    profile = profiler.profile("path/to/repo")

    selector = RelevanceSelector()
    candidates = selector.select(profile, "Completed tasks appear in pending list")
    for c in candidates:
        print(c.relative_path, c.total_score)
"""

from itdebugs.intelligence.models import (
    FileCategory,
    FileRecord,
    Language,
    RepositoryProfile,
    RelevanceScore,
    CandidateFile,
    RepositoryIndex,
)
from itdebugs.intelligence.inventory import FileInventory, InventoryConfig
from itdebugs.intelligence.profiler import RepositoryProfiler
from itdebugs.intelligence.relevance import RelevanceSelector, RelevanceConfig, extract_keywords

__all__ = [
    # Models
    "FileCategory",
    "FileRecord",
    "Language",
    "RepositoryProfile",
    "RelevanceScore",
    "CandidateFile",
    "RepositoryIndex",
    # Components
    "FileInventory",
    "InventoryConfig",
    "RepositoryProfiler",
    "RelevanceSelector",
    "RelevanceConfig",
    "extract_keywords",
]
