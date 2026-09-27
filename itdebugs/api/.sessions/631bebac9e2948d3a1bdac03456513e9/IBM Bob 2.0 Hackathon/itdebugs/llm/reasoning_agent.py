"""LLM-powered root-cause reasoning for ItDebugs."""

from __future__ import annotations

import json
import logging
from typing import Any

from .client import OllamaClient, OllamaError
from .prompts import SYSTEM_PROMPT, build_root_cause_prompt
from .schemas import RootCauseHypothesis


logger = logging.getLogger(__name__)


class LLMReasoningAgent:
    """Use a local LLM to reason about a debugging investigation."""

    def __init__(
        self,
        client: OllamaClient | None = None,
    ) -> None:
        self.client = client or OllamaClient()

    def investigate(
        self,
        *,
        bug_description: str,
        failing_tests: list[Any],
        evidence: list[Any],
    ) -> RootCauseHypothesis:
        """Analyze investigation evidence."""

        prompt = build_root_cause_prompt(
            bug_description=bug_description,
            failing_tests=failing_tests,
            evidence=evidence,
        )

        try:
            response = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                json_mode=True,
            )

        except OllamaError:
            logger.exception("LLM reasoning failed.")
            raise

        return self._parse_response(
            response,
            evidence=evidence,
        )

    @staticmethod
    def _parse_response(
        response: str,
        *,
        evidence: list[Any],
    ) -> RootCauseHypothesis:
        """Parse compact LLM JSON into the full investigation schema."""

        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "LLM returned invalid JSON."
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                "LLM response must be a JSON object."
            )

        root_cause = data.get("root_cause")

        if not isinstance(root_cause, str) or not root_cause.strip():
            raise ValueError(
                "LLM response is missing root_cause."
            )

        line = data.get("line")

        if line is not None:
            try:
                line = int(line)
            except (TypeError, ValueError):
                line = None

        confidence = data.get(
            "confidence",
            "medium",
        )

        if confidence not in {
            "high",
            "medium",
            "low",
        }:
            confidence = "medium"

        # Use LLM-provided evidence when valid.
        supporting_evidence = [
            str(item)
            for item in evidence
            if item
        ]

        reasoning = [
            root_cause.strip(),
        ]

        file_value = data.get("file")
        if not isinstance(file_value, str):
            file_value = None

        faulty_code = data.get("faulty_code")
        if not isinstance(faulty_code, str):
            faulty_code = None

        suggested_fix = data.get("suggested_fix")
        if not isinstance(suggested_fix, str):
            suggested_fix = None

        return RootCauseHypothesis(
            root_cause=root_cause.strip(),
            file=file_value,
            line=line,
            faulty_code=faulty_code,
            expected_behavior=None,
            actual_behavior=None,
            reasoning=reasoning,
            supporting_evidence=supporting_evidence,
            alternative_hypotheses=[],
            confidence=confidence,
            suggested_fix=suggested_fix,
            verification_plan=[
                "Run the failing tests.",
                "Run the relevant test suite.",
            ],
        )