"""Tests for compute_pareto_frontier."""

from __future__ import annotations

from typing import Any, Dict

from openjarvis.evals.core.types import MetricStats, RunSummary
from openjarvis.optimize.optimizer import compute_pareto_frontier
from openjarvis.optimize.types import (
    ObjectiveSpec,
    TrialConfig,
    TrialResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trial(
    trial_id: str,
    accuracy: float = 0.0,
    latency: float = 0.0,
    cost: float = 0.0,
    energy: float = 0.0,
) -> TrialResult:
    """Build a minimal TrialResult with the given scalar metrics."""
    return TrialResult(
        trial_id=trial_id,
        config=TrialConfig(trial_id=trial_id),
        accuracy=accuracy,
        mean_latency_seconds=latency,
        total_cost_usd=cost,
        total_energy_joules=energy,
    )


def _make_trial_with_summary(
    trial_id: str,
    accuracy: float = 0.0,
    latency: float = 0.0,
    cost: float = 0.0,
    energy: float = 0.0,
    **summary_kwargs: Any,
) -> TrialResult:
    """Build a TrialResult that also carries a RunSummary.

    Extra keyword arguments are forwarded to the RunSummary constructor,
    allowing callers to set fields like ``ipw_stats``, ``throughput_stats``,
    ``avg_power_watts``, etc.
    """
    # Provide required RunSummary fields with sensible defaults.
    defaults: Dict[str, Any] = dict(
        benchmark="test",
        category="reasoning",
        backend="jarvis-direct",
        model="test-model",
        total_samples=10,
        scored_samples=10,
        correct=int(accuracy * 10),
        accuracy=accuracy,
        errors=0,
        mean_latency_seconds=latency,
        total_cost_usd=cost,
        total_energy_joules=energy,
    )
    defaults.update(summary_kwargs)
    summary = RunSummary(**defaults)

    return TrialResult(
        trial_id=trial_id,
        config=TrialConfig(trial_id=trial_id),
        accuracy=accuracy,
        mean_latency_seconds=latency,
        total_cost_usd=cost,
        total_energy_joules=energy,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Default objectives used by most tests
# ---------------------------------------------------------------------------

DEFAULT_OBJECTIVES = [
    ObjectiveSpec("accuracy", "maximize"),
    ObjectiveSpec("mean_latency_seconds", "minimize"),
    ObjectiveSpec("total_cost_usd", "minimize"),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComputeParetoFrontier:
    """Tests for :func:`compute_pareto_frontier`."""

    def test_single_trial_is_on_frontier(self) -> None:
        """A single trial should always appear on the Pareto frontier."""
        trial = _make_trial("t1", accuracy=0.8, latency=1.5, cost=0.10)
        frontier = compute_pareto_frontier([trial], DEFAULT_OBJECTIVES)

        assert len(frontier) == 1
        assert frontier[0].trial_id == "t1"

    def test_dominated_trial_excluded(self) -> None:
        """Trial B is dominated by Trial A on every objective and should be excluded.

        A: accuracy=0.9 (higher is better), latency=1.0 (lower is better)
        B: accuracy=0.7,                     latency=2.0
        A >= B on all objectives and > B on at least one => B is dominated.
        """
        trial_a = _make_trial("A", accuracy=0.9, latency=1.0, cost=0.05)
        trial_b = _make_trial("B", accuracy=0.7, latency=2.0, cost=0.10)

        frontier = compute_pareto_frontier([trial_a, trial_b], DEFAULT_OBJECTIVES)

        ids = {t.trial_id for t in frontier}
        assert ids == {"A"}

    def test_non_dominated_both_on_frontier(self) -> None:
        """Neither trial dominates the other so both belong on the frontier.

        A: accuracy=0.9 (better), latency=2.0 (worse)
        B: accuracy=0.7 (worse),  latency=0.5 (better)
        """
        trial_a = _make_trial("A", accuracy=0.9, latency=2.0, cost=0.05)
        trial_b = _make_trial("B", accuracy=0.7, latency=0.5, cost=0.05)

        frontier = compute_pareto_frontier([trial_a, trial_b], DEFAULT_OBJECTIVES)

        ids = {t.trial_id for t in frontier}
        assert ids == {"A", "B"}

    def test_empty_input(self) -> None:
        """An empty trial list should produce an empty frontier."""
        frontier = compute_pareto_frontier([], DEFAULT_OBJECTIVES)
        assert frontier == []

    def test_identical_trials(self) -> None:
        """Two trials with identical metrics: neither dominates the other.

        Both should appear on the frontier because domination requires being
        *strictly* better on at least one objective.
        """
        trial_a = _make_trial("A", accuracy=0.8, latency=1.0, cost=0.05)
        trial_b = _make_trial("B", accuracy=0.8, latency=1.0, cost=0.05)

        frontier = compute_pareto_frontier([trial_a, trial_b], DEFAULT_OBJECTIVES)

        ids = {t.trial_id for t in frontier}
        assert ids == {"A", "B"}

    def test_custom_objectives(self) -> None:
        """Custom objectives (maximize IPW, minimize energy) using RunSummary stats.

        Trial A: high IPW, high energy  (good intelligence-per-watt, bad energy)
        Trial B: low IPW,  low energy   (bad intelligence-per-watt, good energy)
        Neither dominates => both on frontier.

        Trial C: low IPW,  high energy  (bad on both) => dominated by A.
        """
        objectives = [
            ObjectiveSpec("ipw", "maximize", weight=1.0),
            ObjectiveSpec("total_energy_joules", "minimize", weight=1.0),
        ]

        trial_a = _make_trial_with_summary(
            "A",
            accuracy=0.9,
            energy=50.0,
            ipw_stats=MetricStats(mean=120.0),
        )
        trial_b = _make_trial_with_summary(
            "B",
            accuracy=0.6,
            energy=10.0,
            ipw_stats=MetricStats(mean=40.0),
        )
        trial_c = _make_trial_with_summary(
            "C",
            accuracy=0.5,
            energy=55.0,
            ipw_stats=MetricStats(mean=30.0),
        )

        frontier = compute_pareto_frontier(
            [trial_a, trial_b, trial_c],
            objectives,
        )

        ids = {t.trial_id for t in frontier}
        assert "A" in ids, "A should be on frontier (best IPW)"
        assert "B" in ids, "B should be on frontier (best energy)"
        assert "C" not in ids, "C is dominated by A (worse IPW AND worse energy)"

    def test_energy_focused_frontier(self) -> None:
        """Accuracy vs energy tradeoff with the default + energy objectives.

        Trial A: high accuracy, high energy  (good accuracy, bad energy)
        Trial B: low accuracy,  low energy   (bad accuracy, good energy)
        Trial C: low accuracy,  high energy  (bad on both) => dominated
        """
        objectives = [
            ObjectiveSpec("accuracy", "maximize"),
            ObjectiveSpec("total_energy_joules", "minimize"),
        ]

        trial_a = _make_trial("A", accuracy=0.95, energy=100.0)
        trial_b = _make_trial("B", accuracy=0.60, energy=10.0)
        trial_c = _make_trial("C", accuracy=0.55, energy=120.0)

        frontier = compute_pareto_frontier(
            [trial_a, trial_b, trial_c],
            objectives,
        )

        ids = {t.trial_id for t in frontier}
        assert ids == {"A", "B"}, (
            "A (best accuracy) and B (best energy) form the frontier; "
            "C is dominated by both"
        )
