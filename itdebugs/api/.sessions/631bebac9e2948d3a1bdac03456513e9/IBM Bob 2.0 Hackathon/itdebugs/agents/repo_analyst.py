"""
agents/repo_analyst.py
======================
Repository Analyst agent.

Responsibility
--------------
Scan the target repository and populate the investigation context with
structural metadata, a technology-stack profile, and an initial candidate
file list ranked by relevance to the bug description.

Uses
----
``itdebugs.intelligence.RepositoryProfiler``   — builds RepositoryProfile
``itdebugs.intelligence.RelevanceSelector``    — ranks candidate files
``itdebugs.engine.repo_scanner.scan_repository`` — builds RepoStructure
  (kept for backward compatibility with downstream agents)

Populates
---------
ctx.repo_structure   :  RepoStructure  (engine layer, for downstream compat)
ctx.repo_profile     :  RepositoryProfile
ctx.candidate_files  :  List[CandidateFile]  (ranked by relevance)
ctx.repo_index       :  RepositoryIndex  (profile + candidates bundle)
ctx.relevant_files   :  List[str]  (candidate paths as strings, for Code Analyst)
"""

from __future__ import annotations

from itdebugs.agents.base import BaseAgent
from itdebugs.agents.context import InvestigationContext
from itdebugs.engine.repo_scanner import scan_repository
from itdebugs.intelligence.models import RepositoryIndex
from itdebugs.intelligence.profiler import RepositoryProfiler
from itdebugs.intelligence.relevance import RelevanceSelector


class RepositoryAnalyst(BaseAgent):
    """
    Scans the repository, builds a technology-stack profile, and produces
    an initial ranked list of candidate files for the investigation.

    This agent runs first so all subsequent agents have:
      - filesystem context  (repo_structure)
      - technology profile  (repo_profile)
      - pre-ranked file list  (candidate_files / relevant_files)

    Future LLM enhancement
    ----------------------
    An LLM-powered version could additionally:
      - Summarise the README to seed the investigation with domain context
      - Classify modules by inferred responsibility
      - Identify architecture patterns (MVC, layered, etc.)
    """

    @property
    def name(self) -> str:
        return "Repository Analyst"

    def _execute(self, ctx: InvestigationContext) -> None:
        self._log(f"[{self.name}] Scanning: {ctx.repo_path}")

        # ── Step A: engine-layer scan (RepoStructure for downstream compat) ──
        structure = scan_repository(ctx.repo_path)
        ctx.repo_structure = structure

        # ── Step B: intelligence-layer profile ───────────────────────────────
        profiler = RepositoryProfiler()
        profile = profiler.profile(ctx.repo_path)
        ctx.repo_profile = profile

        # ── Step C: relevance selection ───────────────────────────────────────
        selector = RelevanceSelector()
        candidates = selector.select(profile, ctx.bug_description)
        ctx.candidate_files = candidates

        # Build the RepositoryIndex bundle
        ctx.repo_index = RepositoryIndex(
            profile=profile,
            candidates=candidates,
        )

        # ── Step D: populate ctx.relevant_files for Code Analyst ──────────────
        # Use candidate paths if we have them; fall back to all source paths.
        if candidates:
            ctx.relevant_files = [c.relative_path for c in candidates]
        else:
            ctx.relevant_files = structure.source_paths

        # ── Logging / notes ───────────────────────────────────────────────────
        lang_str = ", ".join(l.value for l in profile.languages) or "unknown"
        tf_str = ", ".join(profile.test_frameworks) or "none detected"
        self._log(f"[{self.name}] Languages: {lang_str}  Test fw: {tf_str}")
        self._log(
            f"[{self.name}] {profile.source_file_count} source, "
            f"{profile.test_file_count} test, "
            f"{len(candidates)} candidate file(s)"
        )

        ctx.add_note(
            self.name,
            f"Profile: lang={lang_str}, test_fw={tf_str}, "
            f"src={profile.source_file_count}, test={profile.test_file_count}, "
            f"candidates={len(candidates)}.",
        )
