"""Tests for the cost-aware GRPO reward (offline, no GPU)."""

from __future__ import annotations

from dataclasses import dataclass

from openjarvis.learning.intelligence.orchestrator.reward import (
    CostAwareReward,
    lambda_sweep,
)


@dataclass
class FakeEpisode:
    """Minimal stand-in exposing the two fields CostAwareReward reads."""

    correct: bool
    total_cost_usd: float = 0.0


class TestCostAwareReward:
    def test_correct_zero_cost_is_plus_one(self):
        r = CostAwareReward(lam=0.0)
        assert r.compute(FakeEpisode(correct=True, total_cost_usd=0.0)) == 1.0

    def test_incorrect_zero_cost_is_minus_one(self):
        r = CostAwareReward(lam=0.0)
        assert r.compute(FakeEpisode(correct=False, total_cost_usd=0.0)) == -1.0

    def test_correct_with_lam_penalty_when_cost(self):
        # base=+1, penalty = lam * cost / cost_max = 0.2 * 0.05 / 0.10 = 0.1
        r = CostAwareReward(lam=0.2, cost_max=0.10)
        val = r.compute(FakeEpisode(correct=True, total_cost_usd=0.05))
        assert abs(val - (1.0 - 0.1)) < 1e-9

    def test_lam_zero_ignores_cost(self):
        r = CostAwareReward(lam=0.0, cost_max=0.10)
        val = r.compute(FakeEpisode(correct=True, total_cost_usd=0.5))
        assert val == 1.0

    def test_cost_at_budget_full_penalty(self):
        # cost == cost_max → penalty == lam exactly.
        r = CostAwareReward(lam=0.4, cost_max=0.10)
        val = r.compute(FakeEpisode(correct=True, total_cost_usd=0.10))
        assert abs(val - (1.0 - 0.4)) < 1e-9

    def test_incorrect_also_penalised(self):
        r = CostAwareReward(lam=0.2, cost_max=0.10)
        val = r.compute(FakeEpisode(correct=False, total_cost_usd=0.05))
        assert abs(val - (-1.0 - 0.1)) < 1e-9

    def test_breakdown_fields(self):
        r = CostAwareReward(lam=0.2, cost_max=0.10)
        b = r.compute_with_breakdown(FakeEpisode(correct=True, total_cost_usd=0.05))
        assert set(b) == {"correct", "base", "cost_term", "reward"}
        assert b["correct"] == 1.0
        assert b["base"] == 1.0
        assert abs(b["cost_term"] - (-0.1)) < 1e-9
        assert abs(b["reward"] - 0.9) < 1e-9

    def test_breakdown_reward_matches_compute(self):
        r = CostAwareReward(lam=0.3, cost_max=0.10)
        ep = FakeEpisode(correct=False, total_cost_usd=0.07)
        assert abs(r.compute_with_breakdown(ep)["reward"] - r.compute(ep)) < 1e-12

    def test_compute_batch(self):
        r = CostAwareReward(lam=0.0)
        eps = [FakeEpisode(correct=True), FakeEpisode(correct=False)]
        assert r.compute_batch(eps) == [1.0, -1.0]


class TestLambdaSweep:
    def test_sweep_length(self):
        values = [0.0, 0.05, 0.1, 0.2, 0.4]
        rewards = lambda_sweep(values)
        assert len(rewards) == len(values)

    def test_sweep_assigns_lambdas(self):
        values = [0.0, 0.05, 0.1, 0.2, 0.4]
        rewards = lambda_sweep(values, cost_max=0.25)
        assert [r.lam for r in rewards] == values
        assert all(r.cost_max == 0.25 for r in rewards)

    def test_sweep_returns_costaware(self):
        rewards = lambda_sweep([0.1])
        assert isinstance(rewards[0], CostAwareReward)
