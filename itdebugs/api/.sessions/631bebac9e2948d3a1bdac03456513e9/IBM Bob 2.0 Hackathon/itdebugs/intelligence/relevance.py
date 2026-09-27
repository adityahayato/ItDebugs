"""
itdebugs/intelligence/relevance.py
====================================
Relevance Selector.

Given a :class:`RepositoryProfile` (which includes the full file inventory)
and a natural-language bug description, produces a ranked list of
:class:`CandidateFile` objects for deeper investigation.

Algorithm (deterministic, no LLM)
----------------------------------
Each file in the inventory is scored by a set of lightweight signals.
Scores are additive; the top-N files are returned.

Signals used
------------
1. Keyword match in file path/name           (+2.0 per keyword)
2. Bug-description keyword in parent dirs    (+1.0 per keyword)
3. Source file (not test, not config)        (+0.5 baseline)
4. Test file (useful secondary evidence)     (+0.3 baseline)
5. File in detected source directories       (+1.0)
6. File in detected test directories         (+0.8)
7. Filename is a likely entry point          (+1.5)
8. File is a dependency/config file with
   keywords matching the bug description     (+0.5)
9. Light content scan (first N bytes) for
   keyword matches — only on small files     (+3.0 per keyword hit, capped)

Content scanning is deliberately limited:
  - Only performed on SOURCE and TEST files
  - Only on files smaller than max_content_scan_bytes
  - Only reads the first max_content_scan_bytes bytes
  - Skipped entirely for binary files

Config
------
All limits are controlled by :class:`RelevanceConfig`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from itdebugs.intelligence.models import (
    CandidateFile,
    FileCategory,
    FileRecord,
    Language,
    RepositoryProfile,
    RelevanceScore,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RelevanceConfig:
    """
    Configuration for the relevance selector.
    """
    # Maximum number of candidate files to return
    max_candidates: int = 20

    # Maximum number of files to evaluate (prevents O(n) on huge repos)
    max_files_evaluated: int = 2000

    # Content scanning: only files smaller than this will have their
    # first N bytes read
    max_content_scan_bytes: int = 64 * 1024   # 64 KB

    # How many bytes to actually read from each scanned file
    content_read_bytes: int = 8 * 1024        # 8 KB

    # Maximum keyword hits from content scan per file (prevents noise)
    max_content_hits_per_file: int = 5

    # Minimum score to include in the candidate list (filters noise)
    min_score: float = 0.5


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

_STOPWORDS: Set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "on",
    "at", "by", "for", "with", "about", "as", "into", "through", "that",
    "this", "these", "those", "it", "its", "not", "no", "nor", "but",
    "and", "or", "so", "yet", "both", "either", "neither", "i", "we",
    "you", "they", "them", "their", "our",
}

_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def extract_keywords(text: str) -> List[str]:
    """
    Extract meaningful keywords from *text*.

    Returns unique lowercase terms in order of appearance,
    excluding stop words and single-character tokens.
    """
    # First, preserve quoted strings verbatim
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
    quoted_terms = [q[0] or q[1] for q in quoted]

    # Split remaining words
    words = _WORD_RE.findall(text)
    word_terms = [w.lower() for w in words if w.lower() not in _STOPWORDS and len(w) > 2]

    seen: Set[str] = set()
    result: List[str] = []
    for term in quoted_terms + word_terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _path_keywords(relative_path: str) -> Set[str]:
    """Split a file path into lowercase keyword tokens."""
    path_str = relative_path.replace("\\", "/").replace("_", " ").replace("-", " ")
    parts = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", path_str)
    return {p.lower() for p in parts if len(p) > 2}


# ---------------------------------------------------------------------------
# Content scanner (lightweight, bounded)
# ---------------------------------------------------------------------------

def _scan_content(record: FileRecord, keywords: List[str], max_bytes: int) -> int:
    """
    Read up to *max_bytes* bytes from *record* and count keyword occurrences.

    Returns the number of distinct keywords found (0 on any error).
    """
    if record.is_binary or record.size_bytes == 0:
        return 0
    try:
        with open(record.absolute_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(max_bytes).lower()
        hits = sum(1 for kw in keywords if kw in text)
        return hits
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Relevance Selector
# ---------------------------------------------------------------------------

class RelevanceSelector:
    """
    Scores and ranks files from a :class:`RepositoryProfile` against a
    natural-language bug description.

    Parameters
    ----------
    config:
        :class:`RelevanceConfig` controlling scoring limits.
    """

    def __init__(self, config: Optional[RelevanceConfig] = None) -> None:
        self._config = config or RelevanceConfig()

    def select(
        self,
        profile: RepositoryProfile,
        bug_description: str,
    ) -> List[CandidateFile]:
        """
        Return a ranked list of :class:`CandidateFile` objects most relevant
        to *bug_description*.

        Parameters
        ----------
        profile:
            :class:`RepositoryProfile` containing the full file inventory.
        bug_description:
            Natural-language description of the reported bug.
        """
        keywords = extract_keywords(bug_description)
        if not keywords:
            keywords = ["bug", "error"]   # fallback

        cfg = self._config
        source_dirs = set(profile.source_dirs)
        test_dirs = set(profile.test_dirs)

        entry_point_names: Set[str] = {
            "__main__.py", "main.py", "app.py", "server.py", "wsgi.py", "asgi.py",
            "index.js", "index.ts", "main.js", "main.ts",
        }

        candidates: List[CandidateFile] = []

        # Evaluate up to max_files_evaluated files
        records = profile.inventory[:cfg.max_files_evaluated]

        for record in records:
            score = RelevanceScore(file_path=record.relative_path, total_score=0.0)

            # ── Signal 1: keyword in file path ────────────────────────────
            path_kws = _path_keywords(record.relative_path)
            path_hits = path_kws & set(keywords)
            if path_hits:
                score.add(2.0 * len(path_hits), f"path keywords: {sorted(path_hits)}")

            # ── Signal 2: keyword in parent directory ─────────────────────
            parent_kws = _path_keywords(record.parent_dir)
            parent_hits = parent_kws & set(keywords)
            if parent_hits:
                score.add(1.0 * len(parent_hits), f"parent dir keywords: {sorted(parent_hits)}")

            # ── Signal 3 & 4: file category baseline ─────────────────────
            if record.category == FileCategory.SOURCE:
                score.add(0.5, "is source file")
            elif record.category == FileCategory.TEST:
                score.add(0.3, "is test file")

            # ── Signal 5: in a known source directory ─────────────────────
            top_dir = record.parent_dir.split("/")[0].split("\\")[0]
            if top_dir in source_dirs:
                score.add(1.0, f"in source dir: {top_dir}")
            if top_dir in test_dirs:
                score.add(0.8, f"in test dir: {top_dir}")

            # ── Signal 6: likely entry point ─────────────────────────────
            if record.name in entry_point_names:
                score.add(1.5, "likely entry point")

            # ── Signal 7: content scan (small text files only) ────────────
            if (
                record.category in (FileCategory.SOURCE, FileCategory.TEST)
                and not record.is_binary
                and record.size_bytes <= cfg.max_content_scan_bytes
            ):
                content_hits = _scan_content(record, keywords, cfg.content_read_bytes)
                capped = min(content_hits, cfg.max_content_hits_per_file)
                if capped > 0:
                    score.add(3.0 * capped, f"content scan: {capped} keyword hit(s)")

            # Only include files above the minimum score threshold
            if score.total_score >= cfg.min_score:
                candidates.append(CandidateFile(record=record, score=score))

        # Sort by score descending
        candidates.sort(key=lambda c: c.total_score, reverse=True)

        # Return top N
        return candidates[: cfg.max_candidates]
