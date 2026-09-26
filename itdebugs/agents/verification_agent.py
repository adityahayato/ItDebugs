"""
agents/verification_agent.py
============================
Verification Agent.

Responsibility
--------------
Verify whether the proposed root cause is consistent with the available
evidence and test results.  This is a *review* step — the agent:

  1. Checks that every failing test is addressed by the root cause hypothesis.
  2. Checks that the flagged file/line appears in the grep evidence.
  3. Checks for contradictions (e.g. the supposedly faulty method passes in
     some tests but fails in others with the same call).
  4. Identifies gaps (e.g. failing tests that the root cause does not explain).
  5. Records its findings in a :class:`VerificationResult`.

This agent does NOT fix the bug.  It only assesses the quality of the
investigation so far.

Requires
--------
ctx.evidence      (set by EvidenceAgent)
ctx.failing_tests (set by TestAnalyst)
ctx.root_cause    (set by RootCauseAgent — may be None)

Populates
---------
ctx.verification  :  VerificationResult
"""

from __future__ import annotations

from typing import List

from itdebugs.agents.base import BaseAgent
from itdebugs.agents.context import InvestigationContext, VerificationResult


class VerificationAgent(BaseAgent):
    """
    Reviews the investigation result for consistency and completeness.

    Does not modify the target project.  Does not apply any fixes.

    Future LLM enhancement
    ----------------------
    An LLM-powered version could:
      - Explain in natural language why evidence supports or contradicts the
        root cause hypothesis
      - Ask follow-up questions if the evidence is ambiguous
      - Produce a confidence score based on semantic similarity
    """

    @property
    def name(self) -> str:
        return "Verification Agent"

    def _execute(self, ctx: InvestigationContext) -> None:
        supporting: List[str] = []
        contradictions: List[str] = []
        gaps: List[str] = []

        rc = ctx.root_cause

        # ── Check 1: is there a root cause at all? ────────────────────────
        if rc is None:
            result = VerificationResult(
                consistent=False,
                confidence_assessment="No root cause was identified — investigation inconclusive.",
                gaps=["Root cause could not be determined from the available evidence."],
            )
            ctx.verification = result
            ctx.add_note(self.name, "Verification: inconclusive — no root cause proposed.")
            self._log(f"[{self.name}] Inconclusive — no root cause.")
            return

        # ── Check 2: does the flagged file appear in grep evidence? ───────
        flagged_file = rc.file
        grep_locations = [
            ev.location for ev in ctx.evidence if ev.category == "grep_match"
        ]
        file_in_grep = any(flagged_file in loc for loc in grep_locations)
        if file_in_grep:
            supporting.append(
                f"Flagged file '{flagged_file}' appears in grep evidence."
            )
        else:
            gaps.append(
                f"Flagged file '{flagged_file}' was not found in grep evidence — "
                "verify the file path is correct."
            )

        # ── Check 3: does the faulty code appear in the evidence snippets? ─
        faulty_snippet_short = rc.faulty_code.strip()[:60]
        code_evidence_snippets = [
            ev.snippet for ev in ctx.evidence
            if ev.category in ("code_inspection", "grep_match")
        ]
        faulty_in_evidence = any(
            faulty_snippet_short in snippet
            for snippet in code_evidence_snippets
            if snippet
        )
        if faulty_in_evidence:
            supporting.append(
                "The faulty code snippet was found in the collected code evidence."
            )
        else:
            gaps.append(
                "The exact faulty code snippet was not captured in evidence — "
                "consider inspecting the flagged line manually."
            )

        # ── Check 4: are all failing tests addressed? ─────────────────────
        failing_names = {tr.test_name for tr in ctx.failing_tests}
        failing_evidence_names = {
            ev.location.split("::")[-1]
            for ev in ctx.evidence
            if ev.category == "failing_test"
        }
        addressed = failing_names & failing_evidence_names
        unaddressed = failing_names - failing_evidence_names

        if addressed:
            supporting.append(
                f"Evidence collected for {len(addressed)} failing test(s): "
                f"{sorted(addressed)[:3]}."
            )
        if unaddressed:
            gaps.append(
                f"{len(unaddressed)} failing test(s) not reflected in evidence: "
                f"{sorted(unaddressed)[:3]}."
            )

        # ── Check 5: confidence assessment ───────────────────────────────
        n_support = len(supporting)
        n_contra = len(contradictions)
        n_gaps = len(gaps)

        if n_support >= 2 and n_contra == 0 and n_gaps == 0:
            confidence_text = (
                f"HIGH — {n_support} supporting finding(s), no contradictions, no gaps."
            )
            consistent = True
        elif n_support >= 1 and n_contra == 0:
            confidence_text = (
                f"MEDIUM — {n_support} supporting finding(s), {n_gaps} gap(s)."
            )
            consistent = True
        elif n_contra > 0:
            confidence_text = (
                f"LOW — {n_contra} contradiction(s) found."
            )
            consistent = False
        else:
            confidence_text = "LOW — insufficient evidence to verify the hypothesis."
            consistent = False

        result = VerificationResult(
            consistent=consistent,
            confidence_assessment=confidence_text,
            supporting_evidence=supporting,
            contradictions=contradictions,
            gaps=gaps,
            notes=(
                f"Root cause points to {flagged_file} line {rc.line_range}. "
                f"Fix has NOT been applied — manual review required."
            ),
        )
        ctx.verification = result

        status = "CONSISTENT" if consistent else "INCONSISTENT"
        self._log(f"[{self.name}] Verification result: {status} ({confidence_text})")
        ctx.add_note(
            self.name,
            f"Verification: {status}. {confidence_text} "
            f"Supporting: {supporting[:2]}. Gaps: {gaps[:2]}.",
        )
