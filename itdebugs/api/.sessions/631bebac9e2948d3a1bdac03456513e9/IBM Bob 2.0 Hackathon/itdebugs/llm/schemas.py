"""Structured output models for LLM debugging reasoning."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RootCauseHypothesis:
    """Structured hypothesis produced by the LLM reasoning agent."""

    root_cause: str
    file: str | None = None
    line: int | None = None
    faulty_code: str | None = None
    expected_behavior: str | None = None
    actual_behavior: str | None = None

    reasoning: list[str] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)
    alternative_hypotheses: list[str] = field(default_factory=list)

    confidence: str = "medium"
    suggested_fix: str | None = None
    verification_plan: list[str] = field(default_factory=list)