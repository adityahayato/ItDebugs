"""
agents/repo_analyst.py
======================
Repository Analyst agent.

Responsibility
--------------
Scan the target repository and populate the investigation context with
structural metadata: directory tree, Python source files, test files,
package directories, config files, and README files.

Reuses
------
``itdebugs.engine.repo_scanner.scan_repository`` — no duplication.

Populates
---------
ctx.repo_structure  :  RepoStructure
ctx.relevant_files  :  list of relative source file paths (non-test Python)
"""

from __future__ import annotations

from itdebugs.agents.base import BaseAgent
from itdebugs.agents.context import InvestigationContext
from itdebugs.engine.repo_scanner import scan_repository


class RepositoryAnalyst(BaseAgent):
    """
    Scans the repository and builds a structural model of the project.

    This agent runs first so all subsequent agents have filesystem context
    without needing to re-scan independently.

    Future LLM enhancement
    ----------------------
    An LLM-powered version could additionally:
      - Identify the project's primary language / framework from config files
      - Summarise the README to seed the investigation with domain context
      - Classify modules by likely responsibility (data layer, business logic, etc.)
    """

    @property
    def name(self) -> str:
        return "Repository Analyst"

    def _execute(self, ctx: InvestigationContext) -> None:
        self._log(f"[{self.name}] Scanning: {ctx.repo_path}")

        structure = scan_repository(ctx.repo_path)
        ctx.repo_structure = structure

        # Populate relevant_files as a starting point for Code Analyst.
        # Only non-test Python source files are included here; test files
        # are handled by Test Analyst.
        ctx.relevant_files = structure.source_paths

        pkg_count = len(structure.package_dirs)
        src_count = len(structure.source_files)
        test_count = len(structure.test_files)
        ctx.add_note(
            self.name,
            f"Found {src_count} source file(s), {test_count} test file(s), "
            f"{pkg_count} package(s).",
        )
        self._log(
            f"[{self.name}] {src_count} source files, "
            f"{test_count} test files, "
            f"{pkg_count} packages"
        )
