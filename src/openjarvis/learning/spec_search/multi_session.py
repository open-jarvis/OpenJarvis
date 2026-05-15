"""Multi-session loop for LLM-guided spec search (paper Algorithm 1).

The single-session ``SpecSearchOrchestrator.run(trigger)`` does one
diagnose / plan / execute / record pass. Algorithm 1 in the paper
specifies a *multi-session* loop that repeats this pass until either
gate-score stagnation (default *k* = 5 sessions with no improvement)
or budget exhaustion.

``SpecSearchLoop`` wraps an existing ``SpecSearchOrchestrator`` and
implements that stopping logic without modifying the orchestrator
itself, so existing single-session callers and tests are unaffected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from openjarvis.learning.spec_search.models import (
    LearningSession,
    SessionStatus,
)
from openjarvis.learning.spec_search.triggers import OnDemandTrigger

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LoopResult:
    """Final state of a multi-session run.

    ``stop_reason`` is one of:

    - ``"stagnation"`` — gate score did not improve for ``stagnation_k``
      consecutive sessions.
    - ``"budget"`` — cumulative teacher cost reached ``max_total_cost_usd``.
    - ``"failed"`` — a session returned ``SessionStatus.FAILED``; the loop
      exits rather than burning more budget on a broken state.
    """

    sessions: list[LearningSession] = field(default_factory=list)
    stop_reason: str = "stagnation"
    total_cost_usd: float = 0.0
    best_overall_score: float = 0.0


class SpecSearchLoop:
    """Paper Algorithm 1: greedy gated edits across primitives, multi-session.

    Args:
        orchestrator: a constructed ``SpecSearchOrchestrator``. Each tick
            of the loop calls ``orchestrator.run(trigger)``.
        stagnation_k: stop after this many consecutive sessions with no
            gate-score improvement (paper default: 5).
        stagnation_eps: gate-score delta below this counts as "no
            improvement" — guards against floating-point noise.
        max_total_cost_usd: cumulative teacher-cost budget across all
            sessions. The loop stops as soon as this is exceeded.
    """

    def __init__(
        self,
        orchestrator: Any,
        *,
        stagnation_k: int = 5,
        stagnation_eps: float = 0.001,
        max_total_cost_usd: float = 50.0,
    ) -> None:
        if stagnation_k < 1:
            raise ValueError("stagnation_k must be >= 1")
        if max_total_cost_usd <= 0:
            raise ValueError("max_total_cost_usd must be > 0")
        self._orch = orchestrator
        self._k = stagnation_k
        self._eps = stagnation_eps
        self._budget = max_total_cost_usd

    def run(self, trigger: Any | None = None) -> LoopResult:
        """Run sessions until stagnation, budget, or failure."""
        result = LoopResult()
        no_improve_streak = 0

        while True:
            session_trigger = trigger if trigger is not None else OnDemandTrigger()
            session = self._orch.run(session_trigger)
            result.sessions.append(session)
            result.total_cost_usd += session.teacher_cost_usd or 0.0

            if session.status == SessionStatus.FAILED:
                result.stop_reason = "failed"
                logger.info(
                    "spec-search loop stopping: session failed (%s)",
                    session.error,
                )
                break

            after_score = (
                session.benchmark_after.overall_score
                if session.benchmark_after is not None
                else 0.0
            )
            if after_score > result.best_overall_score + self._eps:
                result.best_overall_score = after_score
                no_improve_streak = 0
            else:
                no_improve_streak += 1

            if no_improve_streak >= self._k:
                result.stop_reason = "stagnation"
                logger.info(
                    "spec-search loop stopping: %d sessions without improvement",
                    no_improve_streak,
                )
                break

            if result.total_cost_usd >= self._budget:
                result.stop_reason = "budget"
                logger.info(
                    "spec-search loop stopping: cumulative cost $%.2f >= budget $%.2f",
                    result.total_cost_usd,
                    self._budget,
                )
                break

        return result


__all__ = ["LoopResult", "SpecSearchLoop"]
