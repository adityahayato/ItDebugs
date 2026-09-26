"""
agents/root_cause_agent.py
==========================
Root Cause Agent.

Responsibility
--------------
Consume the assembled evidence and produce a structured
:class:`RootCauseHypothesis` describing:
  - The most likely root cause (one sentence)
  - The affected file and line
  - The faulty code snippet
  - A suggested fix description (NOT applied automatically)
  - Confidence level and remaining uncertainty

Reuses
------
``itdebugs.engine.investigator._infer_root_cause`` — delegates the pattern-
matching inference to the existing engine function so there is no duplication.

Requires
--------
ctx.repo_structure  (set by RepositoryAnalyst)
ctx.failing_tests   (set by TestAnalyst)
ctx.evidence        (set by EvidenceAgent)

Populates
---------
ctx.root_cause  :  Optional[RootCauseHypothesis]
"""

from __future__ import annotations

from itdebugs.agents.base import BaseAgent
from itdebugs.agents.context import InvestigationContext

# Reuse the root-cause inference logic from the existing engine
from itdebugs.engine.investigator import _infer_root_cause


class RootCauseAgent(BaseAgent):
    """
    Synthesises collected evidence into a root-cause hypothesis.

    Delegates the pattern-matching inference to the existing engine's
    ``_infer_root_cause`` function, which looks for:
      - wrong string literals in comparisons
      - mismatched status / value names
      - other classic bug patterns

    The agent never modifies the target project's source code.

    Future LLM enhancement
    ----------------------
    The ``_execute`` method calls ``_infer_root_cause`` which is purely
    deterministic.  To replace it with an LLM:
      1. Build a prompt from ``ctx.evidence`` and ``ctx.bug_description``.
      2. Call the LLM API.
      3. Parse the structured response into a ``RootCauseHypothesis``.
      4. Assign to ``ctx.root_cause``.
    The rest of the pipeline (Verification Agent, report rendering) is
    unaffected.
    """

    @property
    def name(self) -> str:
        return "Root Cause Agent"

    def _execute(self, ctx: InvestigationContext) -> None:
        if ctx.repo_structure is None:
            raise RuntimeError("repo_structure not set; run RepositoryAnalyst first")

        self._log(f"[{self.name}] Analysing {len(ctx.evidence)} evidence items ...")

        root_cause = _infer_root_cause(
            evidence=ctx.evidence,
            failing_tests=ctx.failing_tests,
            repo_root=ctx.repo_path,
            structure=ctx.repo_structure,
            bug_description=ctx.bug_description,
        )

        ctx.root_cause = root_cause

        if root_cause:
            self._log(
                f"[{self.name}] Root cause identified: "
                f"{root_cause.file}:{root_cause.line_range} "
                f"(confidence: {root_cause.confidence})"
            )
            ctx.add_note(
                self.name,
                f"Root cause: {root_cause.summary} "
                f"[{root_cause.file}:{root_cause.line_range}, "
                f"confidence={root_cause.confidence}]",
            )
        else:
            self._log(f"[{self.name}] Could not determine root cause from available evidence.")
            ctx.add_note(self.name, "Root cause could not be determined from available evidence.")
