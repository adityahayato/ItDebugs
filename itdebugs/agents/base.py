"""
agents/base.py
==============
Base class and interface for all ItDebugs agents.

Every agent in the pipeline:
  1. Has a unique ``name`` (used in log output and error attribution).
  2. Accepts an :class:`InvestigationContext` as its only input.
  3. Mutates the context in-place and returns it.
  4. Never raises — exceptions are caught and recorded in ``ctx.errors``.

This contract makes agents:
  * Independently testable  (pass a minimal context, check mutations)
  * Independently replaceable  (swap deterministic logic for an LLM call)
  * Safe for future parallel execution  (the orchestrator can snapshot the
    context before dispatching a group of non-dependent agents)

Subclassing
-----------
Override ``_execute(ctx)`` — do NOT override ``run()``.  The ``run()`` method
provides the error-handling wrapper and progress logging.
"""

from __future__ import annotations

import sys
import time
from abc import ABC, abstractmethod

from itdebugs.agents.context import InvestigationContext


class BaseAgent(ABC):
    """
    Abstract base for all ItDebugs pipeline agents.

    Parameters
    ----------
    verbose:
        When True, progress messages are printed to stderr.
    """

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable agent name shown in progress output."""

    def run(self, ctx: InvestigationContext) -> InvestigationContext:
        """
        Execute this agent against *ctx*.

        The method logs start/finish, delegates to ``_execute``, and
        catches any unexpected exception so the pipeline keeps running.
        Always returns the (possibly mutated) context.
        """
        self._log(f"[{self.name}] Starting ...")
        t0 = time.monotonic()
        try:
            self._execute(ctx)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error in {self.name}: {exc}"
            ctx.add_error(self.name, str(exc))
            self._log(f"[{self.name}] ERROR: {exc}", error=True)
        else:
            elapsed = time.monotonic() - t0
            self._log(f"[{self.name}] Done ({elapsed:.2f}s)")
        return ctx

    # ------------------------------------------------------------------
    # For subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    def _execute(self, ctx: InvestigationContext) -> None:
        """
        Core agent logic.  Mutates *ctx* in place.
        Raise any exception on failure — ``run()`` will catch it.
        """

    def _log(self, msg: str, error: bool = False) -> None:
        if self.verbose or error:
            stream = sys.stderr
            print(f"  {msg}", file=stream)
