"""Tests for orchestrator multi-objective reward."""

from __future__ import annotations

import pytest

from openjarvis.learning.intelligence.orchestrator.reward import (
    AdaptiveRewardWeights,
    MultiObjectiveReward,
    Normalizers,
    RewardWeights,
)
from openjarvis.learning.intelligence.orchestrator.types import (
    Episode,
)


class TestRewardWeights:
    def test_default_sum(self):
        w = RewardWeights()
        total = w.alpha + w.beta_cost + w.beta_energy + w.gamma_latency + w.gamma_power
        assert abs(total - 1.0) < 0.01

    def test_invalid_sum_raises(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            RewardWeights(alpha=0.9, beta_cost=0.5)

    def test_custom_weights(self):
        w = RewardWeights(
            alpha=0.5,
            beta_cost=0.1,
            beta_energy=0.1,
            gamma_latency=0.2,
            gamma_power=0.1,
        )
        assert w.alpha == 0.5


class TestMultiObjectiveReward:
    def _make_episode(self, correct: bool = True) -> Episode:
        ep = Episode(
            task_id="t",
            initial_prompt="q",
            ground_truth="4",
            final_answer="4" if correct else "5",
            correct=correct,
            total_energy_joules=50.0,
            total_cost_usd=0.05,
            total_latency_seconds=15.0,
            max_power_watts=100.0,
        )
        return ep

    def test_correct_episode_positive(self):
        reward_fn = MultiObjectiveReward(RewardWeights(), Normalizers())
        ep = self._make_episode(correct=True)
        r = reward_fn.compute(ep)
        assert r > 0, "Correct episode should have positive reward"

    def test_incorrect_episode_negative(self):
        reward_fn = MultiObjectiveReward(RewardWeights(), Normalizers())
        ep = self._make_episode(correct=False)
        r = reward_fn.compute(ep)
        assert r < 0, "Incorrect episode should have negative reward"

    def test_correct_better_than_incorrect(self):
        reward_fn = MultiObjectiveReward(RewardWeights(), Normalizers())
        correct = reward_fn.compute(self._make_episode(correct=True))
        incorrect = reward_fn.compute(self._make_episode(correct=False))
        assert correct > incorrect

    def test_compute_with_breakdown(self):
        reward_fn = MultiObjectiveReward(RewardWeights(), Normalizers())
        ep = self._make_episode(correct=True)
        bd = reward_fn.compute_with_breakdown(ep)
        assert "total_reward" in bd
        assert "accuracy_reward" in bd
        assert bd["accuracy_reward"] == 1.0
        assert bd["cost_penalty"] > 0
        assert bd["energy_penalty"] > 0
        assert "ipj" in bd

    def test_compute_batch(self):
        reward_fn = MultiObjectiveReward(RewardWeights(), Normalizers())
        episodes = [
            self._make_episode(correct=True),
            self._make_episode(correct=False),
        ]
        rewards = reward_fn.compute_batch(episodes)
        assert len(rewards) == 2
        assert rewards[0] > rewards[1]

    def test_zero_cost_episode(self):
        reward_fn = MultiObjectiveReward(RewardWeights(), Normalizers())
        ep = Episode(
            task_id="t",
            initial_prompt="q",
            correct=True,
            total_energy_joules=0.0,
            total_cost_usd=0.0,
            total_latency_seconds=0.0,
            max_power_watts=0.0,
        )
        r = reward_fn.compute(ep)
        # Only accuracy component, no penalties
        assert r == pytest.approx(RewardWeights().alpha)


class TestAdaptiveRewardWeights:
    def test_at_zero_progress(self):
        adaptive = AdaptiveRewardWeights(total_steps=10000)
        w = adaptive.get_weights(0)
        total = w.alpha + w.beta_cost + w.beta_energy + w.gamma_latency + w.gamma_power
        assert abs(total - 1.0) < 0.01
        # At step 0, alpha should be close to initial (highest)
        assert w.alpha > 0.5

    def test_at_fifty_percent(self):
        adaptive = AdaptiveRewardWeights(total_steps=10000)
        w = adaptive.get_weights(5000)
        total = w.alpha + w.beta_cost + w.beta_energy + w.gamma_latency + w.gamma_power
        assert abs(total - 1.0) < 0.01

    def test_at_hundred_percent(self):
        adaptive = AdaptiveRewardWeights(total_steps=10000)
        w = adaptive.get_weights(10000)
        total = w.alpha + w.beta_cost + w.beta_energy + w.gamma_latency + w.gamma_power
        assert abs(total - 1.0) < 0.01
        # At step 10000, alpha should be lower
        w0 = adaptive.get_weights(0)
        assert w.alpha < w0.alpha

    def test_alpha_decreases(self):
        adaptive = AdaptiveRewardWeights(total_steps=1000)
        w_start = adaptive.get_weights(0)
        w_end = adaptive.get_weights(1000)
        assert w_start.alpha > w_end.alpha

    def test_beyond_total_steps_clamped(self):
        adaptive = AdaptiveRewardWeights(total_steps=100)
        w = adaptive.get_weights(200)
        total = w.alpha + w.beta_cost + w.beta_energy + w.gamma_latency + w.gamma_power
        assert abs(total - 1.0) < 0.01
