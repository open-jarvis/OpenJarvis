"""Tests for openjarvis.learning.distillation.gate.regression module."""

from __future__ import annotations

from openjarvis.learning.distillation.models import BenchmarkSnapshot


def _make_snapshot(
    overall: float = 0.7,
    clusters: dict[str, float] | None = None,
) -> BenchmarkSnapshot:
    return BenchmarkSnapshot(
        benchmark_version="personal_v1",
        overall_score=overall,
        cluster_scores=clusters or {"c1": 0.6, "c2": 0.8},
        task_count=50,
        elapsed_seconds=60.0,
    )


class TestRegressionCheck:
    """Tests for regression_check()."""

    def test_no_regression_when_all_improve(self) -> None:
        from openjarvis.learning.distillation.gate.regression import (
            regression_check,
        )

        before = _make_snapshot(overall=0.6, clusters={"c1": 0.5, "c2": 0.7})
        after = _make_snapshot(overall=0.7, clusters={"c1": 0.6, "c2": 0.8})
        result = regression_check(before, after, max_regression=0.05)
        assert not result.has_regression

    def test_detects_cluster_regression(self) -> None:
        from openjarvis.learning.distillation.gate.regression import (
            regression_check,
        )

        before = _make_snapshot(overall=0.7, clusters={"c1": 0.6, "c2": 0.8})
        after = _make_snapshot(overall=0.72, clusters={"c1": 0.65, "c2": 0.70})
        result = regression_check(before, after, max_regression=0.05)
        assert result.has_regression
        assert "c2" in result.regressed_clusters

    def test_small_drop_within_threshold(self) -> None:
        from openjarvis.learning.distillation.gate.regression import (
            regression_check,
        )

        before = _make_snapshot(overall=0.7, clusters={"c1": 0.6, "c2": 0.8})
        after = _make_snapshot(overall=0.72, clusters={"c1": 0.63, "c2": 0.76})
        result = regression_check(before, after, max_regression=0.05)
        assert not result.has_regression

    def test_new_cluster_in_after_not_flagged(self) -> None:
        from openjarvis.learning.distillation.gate.regression import (
            regression_check,
        )

        before = _make_snapshot(overall=0.7, clusters={"c1": 0.6})
        after = _make_snapshot(overall=0.75, clusters={"c1": 0.65, "c2": 0.8})
        result = regression_check(before, after, max_regression=0.05)
        assert not result.has_regression

    def test_missing_cluster_in_after_flagged(self) -> None:
        from openjarvis.learning.distillation.gate.regression import (
            regression_check,
        )

        before = _make_snapshot(overall=0.7, clusters={"c1": 0.6, "c2": 0.8})
        after = _make_snapshot(overall=0.72, clusters={"c1": 0.65})
        # c2 disappeared — treat as regression (score went from 0.8 to 0.0)
        result = regression_check(before, after, max_regression=0.05)
        assert result.has_regression
        assert "c2" in result.regressed_clusters

    def test_result_has_details(self) -> None:
        from openjarvis.learning.distillation.gate.regression import (
            regression_check,
        )

        before = _make_snapshot(overall=0.7, clusters={"c1": 0.6, "c2": 0.8})
        after = _make_snapshot(overall=0.68, clusters={"c1": 0.55, "c2": 0.75})
        result = regression_check(before, after, max_regression=0.03)
        assert result.has_regression
        assert len(result.regressed_clusters) >= 1
        # Check that deltas are provided
        for cluster_id, delta in result.regressed_clusters.items():
            assert delta < 0
