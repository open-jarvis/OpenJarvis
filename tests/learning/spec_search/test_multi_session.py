"""Tests for SpecSearchLoop (paper Algorithm 1)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from openjarvis.learning.spec_search.models import (
    AutonomyMode,
    BenchmarkSnapshot,
    LearningSession,
    SessionStatus,
    TriggerKind,
)
from openjarvis.learning.spec_search.multi_session import (
    SpecSearchLoop,
)


def _session(
    score: float,
    cost: float = 0.1,
    status: SessionStatus = SessionStatus.COMPLETED,
    error: str | None = None,
) -> LearningSession:
    return LearningSession(
        id=f"s-{score}",
        trigger=TriggerKind.ON_DEMAND,
        trigger_metadata={},
        status=status,
        autonomy_mode=AutonomyMode.AUTO,
        started_at=datetime.now(timezone.utc),
        diagnosis_path="/tmp/diag.md",
        plan_path="/tmp/plan.json",
        benchmark_before=BenchmarkSnapshot(
            benchmark_version="v1",
            overall_score=0.0,
            cluster_scores={},
            task_count=10,
            elapsed_seconds=1.0,
        ),
        benchmark_after=BenchmarkSnapshot(
            benchmark_version="v1",
            overall_score=score,
            cluster_scores={},
            task_count=10,
            elapsed_seconds=1.0,
        ),
        git_checkpoint_pre="sha-pre",
        teacher_cost_usd=cost,
        error=error,
    )


def _orch_yielding(sessions: list[LearningSession]) -> MagicMock:
    """Mock orchestrator whose .run(trigger) returns the next session."""
    orch = MagicMock()
    orch.run.side_effect = sessions
    return orch


class TestSpecSearchLoop:
    def test_validates_stagnation_k(self) -> None:
        with pytest.raises(ValueError):
            SpecSearchLoop(MagicMock(), stagnation_k=0)

    def test_validates_budget(self) -> None:
        with pytest.raises(ValueError):
            SpecSearchLoop(MagicMock(), max_total_cost_usd=0)

    def test_stops_after_k_sessions_without_improvement(self) -> None:
        # First session improves to 0.6; next 3 do not improve. With k=3
        # the loop should stop after the 4th session.
        orch = _orch_yielding(
            [
                _session(0.6),
                _session(0.6),
                _session(0.6),
                _session(0.6),
            ]
        )
        loop = SpecSearchLoop(orch, stagnation_k=3, max_total_cost_usd=10.0)
        result = loop.run()
        assert result.stop_reason == "stagnation"
        assert len(result.sessions) == 4
        assert result.best_overall_score == pytest.approx(0.6)

    def test_keeps_improving_resets_streak(self) -> None:
        # Sessions improve each time; loop only stops when budget hits.
        orch = _orch_yielding(
            [
                _session(0.5, cost=2.0),
                _session(0.6, cost=2.0),
                _session(0.7, cost=2.0),
                _session(0.8, cost=2.0),  # cumulative = 8.0
                _session(0.9, cost=3.0),  # cumulative = 11.0 -> over budget
            ]
        )
        loop = SpecSearchLoop(orch, stagnation_k=10, max_total_cost_usd=10.0)
        result = loop.run()
        assert result.stop_reason == "budget"
        assert len(result.sessions) == 5
        assert result.best_overall_score == pytest.approx(0.9)

    def test_failed_session_terminates_loop(self) -> None:
        orch = _orch_yielding(
            [
                _session(0.5),
                _session(0.0, status=SessionStatus.FAILED, error="crash"),
            ]
        )
        loop = SpecSearchLoop(orch, stagnation_k=5, max_total_cost_usd=10.0)
        result = loop.run()
        assert result.stop_reason == "failed"
        assert len(result.sessions) == 2

    def test_total_cost_accumulates(self) -> None:
        orch = _orch_yielding(
            [
                _session(0.5, cost=1.0),
                _session(0.5, cost=2.0),
                _session(0.5, cost=3.0),
            ]
        )
        loop = SpecSearchLoop(orch, stagnation_k=2, max_total_cost_usd=100.0)
        result = loop.run()
        assert result.total_cost_usd == pytest.approx(6.0)

    def test_eps_threshold_filters_noise(self) -> None:
        # Improvement smaller than stagnation_eps does not reset the streak.
        orch = _orch_yielding(
            [
                _session(0.500),
                _session(0.5005),  # below default eps=0.001
                _session(0.5009),  # below eps from current best
            ]
        )
        loop = SpecSearchLoop(
            orch, stagnation_k=2, stagnation_eps=0.001, max_total_cost_usd=10.0
        )
        result = loop.run()
        assert result.stop_reason == "stagnation"
        assert len(result.sessions) == 3
        assert result.best_overall_score == pytest.approx(0.500)
