"""Tests for openjarvis.learning.distillation.gate.benchmark_gate module.

All tests use mock scorers — no live EvalRunner.
"""

from __future__ import annotations

from openjarvis.learning.distillation.models import BenchmarkSnapshot


def _make_scorer(scores: dict[str, float], overall: float | None = None):
    """Return a callable that produces a BenchmarkSnapshot with given scores."""

    def scorer(
        *, benchmark_version: str, subsample_size: int, seed: int
    ) -> BenchmarkSnapshot:
        computed = sum(scores.values()) / max(len(scores), 1)
        return BenchmarkSnapshot(
            benchmark_version=benchmark_version,
            overall_score=overall if overall is not None else computed,
            cluster_scores=scores,
            task_count=subsample_size,
            elapsed_seconds=5.0,
        )

    return scorer


class TestBenchmarkGate:
    """Tests for BenchmarkGate."""

    def test_accepts_improving_edit(self) -> None:
        from openjarvis.learning.distillation.gate.benchmark_gate import (
            BenchmarkGate,
        )

        before = BenchmarkSnapshot(
            benchmark_version="v1",
            overall_score=0.6,
            cluster_scores={"c1": 0.5, "c2": 0.7},
            task_count=50,
            elapsed_seconds=10.0,
        )
        gate = BenchmarkGate(
            scorer=_make_scorer({"c1": 0.6, "c2": 0.75}, overall=0.68),
            benchmark_version="v1",
            min_improvement=0.0,
            max_regression=0.05,
            subsample_size=50,
        )
        result = gate.evaluate(before=before, session_seed=42)
        assert result.accepted
        assert result.snapshot.overall_score == 0.68
        assert result.delta > 0

    def test_rejects_no_improvement(self) -> None:
        from openjarvis.learning.distillation.gate.benchmark_gate import (
            BenchmarkGate,
        )

        before = BenchmarkSnapshot(
            benchmark_version="v1",
            overall_score=0.7,
            cluster_scores={"c1": 0.6, "c2": 0.8},
            task_count=50,
            elapsed_seconds=10.0,
        )
        gate = BenchmarkGate(
            scorer=_make_scorer({"c1": 0.6, "c2": 0.8}, overall=0.7),
            benchmark_version="v1",
            min_improvement=0.0,
            max_regression=0.05,
            subsample_size=50,
        )
        result = gate.evaluate(before=before, session_seed=42)
        assert not result.accepted
        assert "no improvement" in result.reason.lower()

    def test_rejects_regression(self) -> None:
        from openjarvis.learning.distillation.gate.benchmark_gate import (
            BenchmarkGate,
        )

        before = BenchmarkSnapshot(
            benchmark_version="v1",
            overall_score=0.7,
            cluster_scores={"c1": 0.6, "c2": 0.8},
            task_count=50,
            elapsed_seconds=10.0,
        )
        # overall improves but c2 regresses badly
        gate = BenchmarkGate(
            scorer=_make_scorer({"c1": 0.75, "c2": 0.65}, overall=0.72),
            benchmark_version="v1",
            min_improvement=0.0,
            max_regression=0.05,
            subsample_size=50,
        )
        result = gate.evaluate(before=before, session_seed=42)
        assert not result.accepted
        assert "regression" in result.reason.lower()

    def test_min_improvement_threshold(self) -> None:
        from openjarvis.learning.distillation.gate.benchmark_gate import (
            BenchmarkGate,
        )

        before = BenchmarkSnapshot(
            benchmark_version="v1",
            overall_score=0.7,
            cluster_scores={"c1": 0.6, "c2": 0.8},
            task_count=50,
            elapsed_seconds=10.0,
        )
        # Tiny improvement of 0.01, but min_improvement requires 0.05
        gate = BenchmarkGate(
            scorer=_make_scorer({"c1": 0.61, "c2": 0.81}, overall=0.71),
            benchmark_version="v1",
            min_improvement=0.05,
            max_regression=0.05,
            subsample_size=50,
        )
        result = gate.evaluate(before=before, session_seed=42)
        assert not result.accepted

    def test_result_contains_snapshot(self) -> None:
        from openjarvis.learning.distillation.gate.benchmark_gate import (
            BenchmarkGate,
        )

        before = BenchmarkSnapshot(
            benchmark_version="v1",
            overall_score=0.5,
            cluster_scores={"c1": 0.5},
            task_count=50,
            elapsed_seconds=10.0,
        )
        gate = BenchmarkGate(
            scorer=_make_scorer({"c1": 0.7}, overall=0.7),
            benchmark_version="v1",
            min_improvement=0.0,
            max_regression=0.05,
            subsample_size=50,
        )
        result = gate.evaluate(before=before, session_seed=42)
        assert isinstance(result.snapshot, BenchmarkSnapshot)
        assert result.snapshot.benchmark_version == "v1"
