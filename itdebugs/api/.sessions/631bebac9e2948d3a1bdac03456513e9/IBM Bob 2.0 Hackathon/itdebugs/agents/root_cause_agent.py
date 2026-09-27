"""
agents/root_cause_agent.py
==========================

Root Cause Agent.

The agent supports two reasoning modes:

1. Deterministic mode
   - Fast
   - Used by the normal test suite
   - Uses the existing investigation engine

2. LLM mode
   - Enabled with ITDEBUGS_USE_LLM=1
   - Uses local IBM Granite through Ollama
   - Uses deterministic evidence as an anchor
   - Validates the LLM result before accepting it
   - Falls back to deterministic inference when necessary

The target repository is never modified by this agent.
"""

from __future__ import annotations

import logging
import os

from itdebugs.agents.base import BaseAgent
from itdebugs.agents.context import InvestigationContext
from itdebugs.engine.investigator import _infer_root_cause
from itdebugs.engine.reporter import RootCauseHypothesis
from itdebugs.llm import LLMReasoningAgent


logger = logging.getLogger(__name__)


class RootCauseAgent(BaseAgent):
    """Produce a validated root-cause hypothesis."""

    @property
    def name(self) -> str:
        return "Root Cause Agent"

    def _execute(self, ctx: InvestigationContext) -> None:
        if ctx.repo_structure is None:
            raise RuntimeError(
                "repo_structure not set; run RepositoryAnalyst first"
            )

        use_llm = os.getenv(
            "ITDEBUGS_USE_LLM",
            "",
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        if use_llm:
            try:
                root_cause = self._run_llm(ctx)

                ctx.root_cause = root_cause

                self._log(
                    f"[{self.name}] LLM root cause identified: "
                    f"{root_cause.file}:{root_cause.line_range} "
                    f"(confidence: {root_cause.confidence})"
                )

                ctx.add_note(
                    self.name,
                    (
                        "LLM reasoning used with deterministic "
                        "evidence validation. "
                        f"Root cause: {root_cause.summary} "
                        f"[{root_cause.file}:"
                        f"{root_cause.line_range}], "
                        f"confidence={root_cause.confidence}"
                    ),
                )

                return

            except Exception as exc:
                logger.warning(
                    "LLM reasoning failed; "
                    "falling back to deterministic inference: %s",
                    exc,
                )

                self._log(
                    f"[{self.name}] LLM failed; "
                    "using deterministic fallback."
                )

                ctx.add_note(
                    self.name,
                    (
                        "LLM reasoning failed; "
                        "deterministic fallback was used."
                    ),
                )

        # ---------------------------------------------------------
        # DETERMINISTIC MODE / FALLBACK
        # ---------------------------------------------------------

        root_cause = self._run_deterministic(ctx)

        ctx.root_cause = root_cause

        if root_cause:
            self._log(
                f"[{self.name}] Deterministic root cause identified: "
                f"{root_cause.file}:{root_cause.line_range} "
                f"(confidence: {root_cause.confidence})"
            )

            ctx.add_note(
                self.name,
                (
                    f"Root cause: {root_cause.summary} "
                    f"[{root_cause.file}:{root_cause.line_range}], "
                    f"confidence={root_cause.confidence}"
                ),
            )
        else:
            self._log(
                f"[{self.name}] Could not determine root cause."
            )

            ctx.add_note(
                self.name,
                "Root cause could not be determined from available evidence.",
            )

    def _run_deterministic(
        self,
        ctx: InvestigationContext,
    ) -> RootCauseHypothesis | None:
        """Run the original deterministic investigation engine."""

        if ctx.repo_structure is None:
            raise RuntimeError(
                "repo_structure not set; run RepositoryAnalyst first"
            )

        structure = ctx.repo_structure

        return _infer_root_cause(
            evidence=ctx.evidence,
            failing_tests=ctx.failing_tests,
            repo_root=ctx.repo_path,
            structure=structure,
            bug_description=ctx.bug_description,
        )

    def _run_llm(
        self,
        ctx: InvestigationContext,
    ) -> RootCauseHypothesis:
        """
        Run Granite using deterministic root-cause evidence as an anchor.

        The deterministic engine is intentionally run first. This gives
        the local LLM the strongest available evidence and prevents the
        model from selecting an arbitrary suspicious line.
        """

        deterministic = self._run_deterministic(ctx)

        # Put the strongest deterministic evidence first.
        prioritized_evidence = list(ctx.evidence)

        if deterministic and deterministic.file:
            target_file = deterministic.file.replace("\\", "/")

            target_line: int | None = None

            try:
                target_line = int(
                    str(deterministic.line_range).split("-")[0]
                )
            except (TypeError, ValueError):
                target_line = None

            matching = []
            remaining = []

            for item in prioritized_evidence:
                location = str(
                    getattr(item, "location", "")
                ).replace("\\", "/")

                if target_file in location:
                    if (
                        target_line is None
                        or f":{target_line}" in location
                    ):
                        matching.append(item)
                        continue

                remaining.append(item)

            prioritized_evidence = matching + remaining

        llm_agent = LLMReasoningAgent()

        llm_result = llm_agent.investigate(
            bug_description=ctx.bug_description,
            failing_tests=ctx.failing_tests,
            evidence=prioritized_evidence,
        )

        # ---------------------------------------------------------
        # VALIDATE THE LLM LOCATION
        # ---------------------------------------------------------

        if deterministic and deterministic.file:
            deterministic_file = (
                deterministic.file
                .replace("\\", "/")
            )

            llm_file = (
                str(llm_result.file)
                .replace("\\", "/")
                if llm_result.file
                else ""
            )

            llm_line = llm_result.line

            deterministic_line: int | None = None

            try:
                deterministic_line = int(
                    str(deterministic.line_range).split("-")[0]
                )
            except (TypeError, ValueError):
                deterministic_line = None

            location_matches = (
                llm_file == deterministic_file
                and (
                    deterministic_line is None
                    or llm_line == deterministic_line
                )
            )

            if not location_matches:
                self._log(
                    f"[{self.name}] LLM proposed "
                    f"{llm_result.file}:{llm_result.line}; "
                    f"deterministic evidence identifies "
                    f"{deterministic.file}:"
                    f"{deterministic.line_range}. "
                    "Using deterministic location."
                )

                ctx.add_note(
                    self.name,
                    (
                        "LLM location differed from the "
                        "deterministic evidence anchor; "
                        "deterministic root cause was retained."
                    ),
                )

                # Keep the deterministic location and concrete code,
                # while preserving useful LLM reasoning.
                return RootCauseHypothesis(
                    summary=llm_result.root_cause,
                    file=deterministic.file,
                    line_range=deterministic.line_range,
                    explanation=(
                        llm_result.root_cause
                        + "\n\n"
                        + (
                            llm_result.suggested_fix
                            or "Review the identified faulty code."
                        )
                    ),
                    confidence=deterministic.confidence,
                    faulty_code=(
                        deterministic.faulty_code
                        or llm_result.faulty_code
                        or ""
                    ),
                    suggested_fix=(
                        llm_result.suggested_fix
                        or deterministic.suggested_fix
                    ),
                )

        return self._convert_llm_result(llm_result)

    @staticmethod
    def _convert_llm_result(
        llm_result,
    ) -> RootCauseHypothesis:
        """Convert the LLM schema into the existing ItDebugs schema."""

        file = llm_result.file or "unknown"

        if llm_result.line is not None:
            line_range = str(llm_result.line)
        else:
            line_range = "unknown"

        explanation = llm_result.root_cause

        if llm_result.suggested_fix:
            explanation += (
                "\n\nSuggested fix: "
                + llm_result.suggested_fix
            )

        return RootCauseHypothesis(
            summary=llm_result.root_cause,
            file=file,
            line_range=line_range,
            explanation=explanation,
            confidence=llm_result.confidence,
            faulty_code=llm_result.faulty_code or "",
            suggested_fix=(
                llm_result.suggested_fix
                or "Review the identified faulty code."
            ),
        )