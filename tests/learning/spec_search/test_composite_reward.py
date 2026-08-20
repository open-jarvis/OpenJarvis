"""Tests for the paper Eq. 1 composite reward."""

from __future__ import annotations

import pytest

from openjarvis.learning.spec_search.composite_reward import (
    RewardWeights,
    TrainingSample,
    score_batch,
)


class TestScoreBatch:
    def test_empty_batch_returns_empty(self) -> None:
        assert score_batch([]) == []

    def test_single_sample_has_zero_efficiency_penalties(self) -> None:
        # With one sample the within-batch z-score collapses to 0, so the
        # reward reduces to alpha * accuracy.
        sample = TrainingSample(
            accuracy=1.0, energy_joules=999.0, latency_seconds=42.0, cost_usd=0.05
        )
        [r] = score_batch([sample], weights=RewardWeights())
        assert r == pytest.approx(0.5)  # alpha = 0.5

    def test_higher_accuracy_ranks_above_lower_at_equal_efficiency(self) -> None:
        a = TrainingSample(
            accuracy=1.0, energy_joules=200, latency_seconds=5, cost_usd=0.0
        )
        b = TrainingSample(
            accuracy=0.0, energy_joules=200, latency_seconds=5, cost_usd=0.0
        )
        ra, rb = score_batch([a, b])
        assert ra > rb

    def test_lower_efficiency_costs_lower_reward_at_equal_accuracy(self) -> None:
        # Two equally-accurate samples; the slower / more energy-hungry one
        # gets penalized.
        fast = TrainingSample(
            accuracy=1.0, energy_joules=100, latency_seconds=2, cost_usd=0.0
        )
        slow = TrainingSample(
            accuracy=1.0, energy_joules=400, latency_seconds=8, cost_usd=0.0
        )
        r_fast, r_slow = score_batch([fast, slow])
        assert r_fast > r_slow

    def test_paper_default_weights(self) -> None:
        w = RewardWeights()
        assert (w.alpha, w.beta, w.gamma, w.delta) == (0.5, 0.1, 0.1, 0.3)

    def test_custom_weights_change_ranking(self) -> None:
        # An accuracy-only weighting (alpha=1, others=0) collapses to raw
        # accuracy and ignores efficiency entirely.
        a = TrainingSample(
            accuracy=1.0, energy_joules=999, latency_seconds=99, cost_usd=99
        )
        b = TrainingSample(accuracy=1.0, energy_joules=1, latency_seconds=1, cost_usd=0)
        rewards = score_batch(
            [a, b], weights=RewardWeights(alpha=1.0, beta=0.0, gamma=0.0, delta=0.0)
        )
        assert rewards[0] == pytest.approx(rewards[1])
        assert rewards[0] == pytest.approx(1.0)

    def test_zero_variance_batch_drops_efficiency_terms(self) -> None:
        # If all samples share the same energy/latency/cost, z-score is 0
        # for every term, so the reward is just alpha * accuracy.
        samples = [
            TrainingSample(
                accuracy=1.0, energy_joules=100, latency_seconds=2, cost_usd=0.0
            ),
            TrainingSample(
                accuracy=0.5, energy_joules=100, latency_seconds=2, cost_usd=0.0
            ),
        ]
        rewards = score_batch(samples)
        assert rewards[0] == pytest.approx(0.5)
        assert rewards[1] == pytest.approx(0.25)
