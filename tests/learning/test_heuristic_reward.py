"""Tests for HeuristicRewardFunction."""

from __future__ import annotations

import pytest

from openjarvis.learning._stubs import RoutingContext
from openjarvis.learning.routing.heuristic_reward import HeuristicRewardFunction


class TestHeuristicRewardFunction:
    def test_perfect_score(self) -> None:
        rf = HeuristicRewardFunction()
        score = rf.compute(
            RoutingContext(),
            "model-a",
            "response",
            latency_seconds=0.0,
            cost_usd=0.0,
            prompt_tokens=10,
            completion_tokens=10,
        )
        # latency=1.0, cost=1.0, efficiency=0.5 → 0.4*1 + 0.3*1 + 0.3*0.5 = 0.85
        assert score == pytest.approx(0.85)

    def test_worst_score(self) -> None:
        rf = HeuristicRewardFunction()
        score = rf.compute(
            RoutingContext(),
            "model-a",
            "response",
            latency_seconds=60.0,
            cost_usd=0.1,
            prompt_tokens=100,
            completion_tokens=0,
        )
        # latency clamped to 0, cost clamped to 0, efficiency=0/100=0
        assert score == pytest.approx(0.0)

    def test_latency_only_weight(self) -> None:
        rf = HeuristicRewardFunction(
            weight_latency=1.0,
            weight_cost=0.0,
            weight_efficiency=0.0,
        )
        score = rf.compute(
            RoutingContext(),
            "m",
            "",
            latency_seconds=15.0,
            cost_usd=0.0,
            prompt_tokens=10,
            completion_tokens=10,
        )
        # 1 - 15/30 = 0.5
        assert score == pytest.approx(0.5)

    def test_cost_only_weight(self) -> None:
        rf = HeuristicRewardFunction(
            weight_latency=0.0,
            weight_cost=1.0,
            weight_efficiency=0.0,
        )
        score = rf.compute(
            RoutingContext(),
            "m",
            "",
            latency_seconds=0.0,
            cost_usd=0.005,
            prompt_tokens=10,
            completion_tokens=10,
        )
        # 1 - 0.005/0.01 = 0.5
        assert score == pytest.approx(0.5)

    def test_efficiency_only_weight(self) -> None:
        rf = HeuristicRewardFunction(
            weight_latency=0.0,
            weight_cost=0.0,
            weight_efficiency=1.0,
        )
        score = rf.compute(
            RoutingContext(),
            "m",
            "",
            latency_seconds=0.0,
            cost_usd=0.0,
            prompt_tokens=25,
            completion_tokens=75,
        )
        # 75/100 = 0.75
        assert score == pytest.approx(0.75)

    def test_clamped_to_unit_interval(self) -> None:
        rf = HeuristicRewardFunction()
        # Even with extreme values, score should be in [0, 1]
        score = rf.compute(
            RoutingContext(),
            "m",
            "",
            latency_seconds=-10.0,
            cost_usd=-0.1,
            prompt_tokens=0,
            completion_tokens=100,
        )
        assert 0.0 <= score <= 1.0

    def test_custom_max_values(self) -> None:
        rf = HeuristicRewardFunction(max_latency=10.0, max_cost=1.0)
        score = rf.compute(
            RoutingContext(),
            "m",
            "",
            latency_seconds=5.0,
            cost_usd=0.5,
            prompt_tokens=50,
            completion_tokens=50,
        )
        # latency: 1-5/10=0.5, cost: 1-0.5/1.0=0.5, efficiency: 50/100=0.5
        # 0.4*0.5 + 0.3*0.5 + 0.3*0.5 = 0.5
        assert score == pytest.approx(0.5)

    def test_zero_total_tokens_default(self) -> None:
        rf = HeuristicRewardFunction()
        score = rf.compute(
            RoutingContext(),
            "m",
            "",
            latency_seconds=0.0,
            cost_usd=0.0,
            prompt_tokens=0,
            completion_tokens=0,
        )
        # latency=1, cost=1, efficiency default=0.5
        # 0.4*1 + 0.3*1 + 0.3*0.5 = 0.85
        assert score == pytest.approx(0.85)

    def test_extra_kwargs_ignored(self) -> None:
        rf = HeuristicRewardFunction()
        # Should not raise even with extra kwargs
        score = rf.compute(
            RoutingContext(),
            "m",
            "",
            latency_seconds=1.0,
            cost_usd=0.001,
            prompt_tokens=10,
            completion_tokens=10,
            random_extra="ignored",
        )
        assert 0.0 <= score <= 1.0
