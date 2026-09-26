"""
itdebugs.agents
===============
Specialized analysis agents for the ItDebugs orchestration pipeline.

Pipeline order
--------------
1. RepositoryAnalyst    — scan filesystem, discover files
2. TestAnalyst          — run tests, identify failures, extract keywords
3. CodeAnalyst          — grep source files, flag suspicious locations
4. EvidenceAgent        — aggregate all evidence into a clean list
5. RootCauseAgent       — infer root cause from evidence
6. VerificationAgent    — verify hypothesis consistency, report gaps

All agents share an :class:`InvestigationContext` object.
"""

from itdebugs.agents.context import InvestigationContext, VerificationResult
from itdebugs.agents.base import BaseAgent
from itdebugs.agents.repo_analyst import RepositoryAnalyst
from itdebugs.agents.test_analyst import TestAnalyst
from itdebugs.agents.code_analyst import CodeAnalyst
from itdebugs.agents.evidence_agent import EvidenceAgent
from itdebugs.agents.root_cause_agent import RootCauseAgent
from itdebugs.agents.verification_agent import VerificationAgent

__all__ = [
    "InvestigationContext",
    "VerificationResult",
    "BaseAgent",
    "RepositoryAnalyst",
    "TestAnalyst",
    "CodeAnalyst",
    "EvidenceAgent",
    "RootCauseAgent",
    "VerificationAgent",
]
