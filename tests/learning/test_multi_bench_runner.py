"""Tests for MultiBenchTrialRunner and related multi-benchmark features."""

from __future__ import annotations

from unittest.mock import patch

from openjarvis.learning.optimize.trial_runner import (
    BenchmarkSpec,
    MultiBenchTrialRunner,
)
from openjarvis.learning.optimize.types import (
    BenchmarkScore,
    SampleScore,
    TrialConfig,
    TrialResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_trial_result(
    trial_id: str = "test-001",
    accuracy: float = 0.5,
    latency: float = 5.0,
    cost: float = 0.1,
    energy: float = 100.0,
    tokens: int = 1000,
    samples: int = 50,
    scores: list | None = None,
) -> TrialResult:
    config = TrialConfig(
        trial_id=trial_id,
        params={"agent.type": "orchestrator"},
    )
    sample_scores = scores or [
        SampleScore(record_id=f"s{i}", is_correct=i < int(accuracy * samples))
        for i in range(samples)
    ]
    return TrialResult(
        trial_id=trial_id,
        config=config,
        accuracy=accuracy,
        mean_latency_seconds=latency,
        total_cost_usd=cost,
        total_energy_joules=energy,
        total_tokens=tokens,
        samples_evaluated=samples,
        sample_scores=sample_scores,
    )


# ---------------------------------------------------------------------------
# BenchmarkSpec tests
# ---------------------------------------------------------------------------


class TestBenchmarkSpec:
    def test_defaults(self):
        spec = BenchmarkSpec(benchmark="supergpqa")
        assert spec.benchmark == "supergpqa"
        assert spec.max_samples == 200
        assert spec.weight == 1.0

    def test_custom(self):
        spec = BenchmarkSpec(benchmark="gaia", max_samples=100, weight=0.4)
        assert spec.max_samples == 100
        assert spec.weight == 0.4


# ---------------------------------------------------------------------------
# BenchmarkScore tests
# ---------------------------------------------------------------------------


class TestBenchmarkScore:
    def test_creation(self):
        score = BenchmarkScore(
            benchmark="hle",
            accuracy=0.75,
            weight=0.2,
        )
        assert score.benchmark == "hle"
        assert score.accuracy == 0.75
        assert score.weight == 0.2
        assert score.errors == 0
        assert score.sample_scores == []


# ---------------------------------------------------------------------------
# MultiBenchTrialRunner aggregation tests
# ---------------------------------------------------------------------------


class TestMultiBenchAggregation:
    """Test the _aggregate method directly."""

    def test_weighted_accuracy_040_040_020(self):
        """Verify 0.4/0.4/0.2 weighting matches expected composite."""
        config = TrialConfig(trial_id="agg-001", params={})
        per_benchmark = [
            BenchmarkScore(
                benchmark="terminalbench-native",
                accuracy=0.60,
                mean_latency_seconds=8.0,
                total_cost_usd=0.5,
                total_energy_joules=200.0,
                total_tokens=5000,
                samples_evaluated=200,
                weight=0.4,
            ),
            BenchmarkScore(
                benchmark="gaia",
                accuracy=0.40,
                mean_latency_seconds=12.0,
                total_cost_usd=0.8,
                total_energy_joules=300.0,
                total_tokens=8000,
                samples_evaluated=200,
                weight=0.4,
            ),
            BenchmarkScore(
                benchmark="hle",
                accuracy=0.20,
                mean_latency_seconds=5.0,
                total_cost_usd=0.2,
                total_energy_joules=80.0,
                total_tokens=2000,
                samples_evaluated=200,
                weight=0.2,
            ),
        ]
        result = MultiBenchTrialRunner._aggregate(config, per_benchmark)

        # Weighted accuracy: (0.60*0.4 + 0.40*0.4 + 0.20*0.2) / 1.0 = 0.44
        assert abs(result.accuracy - 0.44) < 1e-6

        # Latency: weighted by samples (all 200 each)
        # (8*200 + 12*200 + 5*200) / 600 = 25*200/600 = 8.333...
        expected_latency = (8.0 * 200 + 12.0 * 200 + 5.0 * 200) / 600
        assert abs(result.mean_latency_seconds - expected_latency) < 1e-6

        # Sums
        assert abs(result.total_cost_usd - 1.5) < 1e-6
        assert abs(result.total_energy_joules - 580.0) < 1e-6
        assert result.total_tokens == 15000
        assert result.samples_evaluated == 600

        # Per-benchmark populated
        assert len(result.per_benchmark) == 3
        assert result.per_benchmark[0].benchmark == "terminalbench-native"

    def test_unequal_samples(self):
        """Latency weighting adjusts for different sample counts."""
        config = TrialConfig(trial_id="agg-002", params={})
        per_benchmark = [
            BenchmarkScore(
                benchmark="a",
                accuracy=1.0,
                mean_latency_seconds=10.0,
                samples_evaluated=100,
                weight=0.5,
            ),
            BenchmarkScore(
                benchmark="b",
                accuracy=0.0,
                mean_latency_seconds=2.0,
                samples_evaluated=400,
                weight=0.5,
            ),
        ]
        result = MultiBenchTrialRunner._aggregate(config, per_benchmark)

        # Weighted accuracy: (1.0*0.5 + 0.0*0.5) / 1.0 = 0.5
        assert abs(result.accuracy - 0.5) < 1e-6

        # Latency: (10*100 + 2*400) / 500 = 1800/500 = 3.6
        assert abs(result.mean_latency_seconds - 3.6) < 1e-6

    def test_errors_in_failure_modes(self):
        config = TrialConfig(trial_id="agg-003", params={})
        per_benchmark = [
            BenchmarkScore(
                benchmark="bench1",
                accuracy=0.5,
                samples_evaluated=10,
                errors=3,
                weight=1.0,
            ),
        ]
        result = MultiBenchTrialRunner._aggregate(config, per_benchmark)
        assert "bench1: 3 errors" in result.failure_modes


# ---------------------------------------------------------------------------
# MultiBenchTrialRunner.run_trial (mocked)
# ---------------------------------------------------------------------------


class TestMultiBenchRunTrial:
    @patch("openjarvis.learning.optimize.trial_runner.TrialRunner.run_trial")
    def test_delegates_to_trial_runners(self, mock_run_trial):
        """Each benchmark gets its own TrialRunner call."""
        mock_run_trial.return_value = _make_trial_result()

        specs = [
            BenchmarkSpec("bench-a", max_samples=10, weight=0.6),
            BenchmarkSpec("bench-b", max_samples=20, weight=0.4),
        ]
        runner = MultiBenchTrialRunner(benchmark_specs=specs)
        trial = TrialConfig(trial_id="t-001", params={})

        result = runner.run_trial(trial)

        assert mock_run_trial.call_count == 2
        assert len(result.per_benchmark) == 2
        assert result.per_benchmark[0].weight == 0.6
        assert result.per_benchmark[1].weight == 0.4


# ---------------------------------------------------------------------------
# load_benchmark_specs tests
# ---------------------------------------------------------------------------


class TestLoadBenchmarkSpecs:
    def test_multi_benchmark_format(self):
        from openjarvis.learning.optimize.config import load_benchmark_specs

        data = {
            "optimize": {
                "benchmarks": [
                    {"name": "terminalbench-native", "max_samples": 200, "weight": 0.4},
                    {"name": "gaia", "max_samples": 200, "weight": 0.4},
                    {"name": "hle", "max_samples": 200, "weight": 0.2},
                ],
            },
        }
        specs = load_benchmark_specs(data)
        assert len(specs) == 3
        assert specs[0].benchmark == "terminalbench-native"
        assert specs[0].weight == 0.4
        assert specs[2].benchmark == "hle"
        assert specs[2].weight == 0.2

    def test_single_benchmark_fallback(self):
        from openjarvis.learning.optimize.config import load_benchmark_specs

        data = {
            "optimize": {
                "benchmark": "supergpqa",
                "max_samples": 100,
            },
        }
        specs = load_benchmark_specs(data)
        assert len(specs) == 1
        assert specs[0].benchmark == "supergpqa"
        assert specs[0].max_samples == 100

    def test_empty_returns_empty(self):
        from openjarvis.learning.optimize.config import load_benchmark_specs

        specs = load_benchmark_specs({"optimize": {}})
        assert specs == []

    def test_no_optimize_section(self):
        from openjarvis.learning.optimize.config import load_benchmark_specs

        specs = load_benchmark_specs({})
        assert specs == []


# ---------------------------------------------------------------------------
# TrialResult.per_benchmark field
# ---------------------------------------------------------------------------


class TestTrialResultPerBenchmark:
    def test_default_empty(self):
        result = TrialResult(
            trial_id="x",
            config=TrialConfig(trial_id="x", params={}),
        )
        assert result.per_benchmark == []

    def test_populated(self):
        scores = [
            BenchmarkScore(benchmark="a", accuracy=0.8, weight=0.5),
            BenchmarkScore(benchmark="b", accuracy=0.6, weight=0.5),
        ]
        result = TrialResult(
            trial_id="x",
            config=TrialConfig(trial_id="x", params={}),
            per_benchmark=scores,
        )
        assert len(result.per_benchmark) == 2


# ---------------------------------------------------------------------------
# _PARAM_TO_RECIPE includes max_tokens
# ---------------------------------------------------------------------------


class TestParamToRecipe:
    def test_max_tokens_mapping(self):
        from openjarvis.learning.optimize.types import _PARAM_TO_RECIPE

        assert "intelligence.max_tokens" in _PARAM_TO_RECIPE
        assert _PARAM_TO_RECIPE["intelligence.max_tokens"] == "max_tokens"

    def test_trial_config_to_recipe_max_tokens(self):
        config = TrialConfig(
            trial_id="t1",
            params={"intelligence.max_tokens": 16384},
        )
        recipe = config.to_recipe()
        assert recipe.max_tokens == 16384
