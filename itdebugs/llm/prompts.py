"""Compact prompts used by the ItDebugs LLM reasoning agent."""

from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """You are the root-cause reasoning agent for ItDebugs.

Use ONLY the supplied debugging evidence.

Identify the most likely root cause.

Rules:
- Never invent evidence.
- Never invent files or line numbers.
- Copy faulty code exactly when available.
- Keep every answer extremely short.
- Return ONLY valid JSON matching the requested structure.
"""


def _compact_test(test: Any) -> dict[str, str]:
    """Keep only important failing-test information."""

    if isinstance(test, dict):
        return {
            "test": str(
                test.get("test")
                or test.get("test_name")
                or test.get("node_id")
                or ""
            ),
            "failure": str(
                test.get("failure")
                or test.get("failure_message")
                or ""
            )[:400],
        }

    return {
        "test": str(
            getattr(test, "test_name", None)
            or getattr(test, "node_id", None)
            or test
        ),
        "failure": str(
            getattr(test, "failure_message", "")
        )[:400],
    }


def _compact_evidence(item: Any) -> dict[str, str]:
    """Keep only high-value evidence."""

    if isinstance(item, dict):
        location = item.get("location")

        if not location and item.get("file") is not None:
            location = (
                f"{item.get('file')}:"
                f"{item.get('line', '')}"
            )

        return {
            "category": str(
                item.get("category")
                or item.get("type")
                or ""
            ),
            "location": str(location or ""),
            "description": str(
                item.get("description")
                or item.get("fact")
                or ""
            )[:120],
            "code": str(
                item.get("code")
                or item.get("snippet")
                or ""
            )[:450],
        }

    return {
        "category": str(
            getattr(item, "category", "")
        ),
        "location": str(
            getattr(item, "location", "")
        ),
        "description": str(
            getattr(item, "description", "")
        )[:120],
        "code": str(
            getattr(item, "snippet", "")
        )[:450],
    }


def build_root_cause_prompt(
    *,
    bug_description: str,
    failing_tests: list[Any],
    evidence: list[Any],
) -> str:
    """Build a minimal CPU-friendly root-cause prompt."""

    compact_tests = [
        _compact_test(test)
        for test in failing_tests[:3]
    ]

    compact_evidence = [
        _compact_evidence(item)
        for item in evidence[:6]
    ]

    payload = {
        "bug": bug_description[:400],
        "tests": compact_tests,
        "evidence": compact_evidence,
    }

    evidence_json = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return f"""Determine the root cause.

Evidence:
{evidence_json}

Return ONLY this JSON:

{{
  "root_cause": "one short sentence",
  "file": "exact file path or null",
  "line": 0,
  "faulty_code": "exact code from evidence or null",
  "confidence": "high",
  "suggested_fix": "one short sentence"
}}

IMPORTANT:
- Use the exact file and line from the evidence.
- Copy faulty_code exactly from the evidence.
- Do not add any other fields.
"""