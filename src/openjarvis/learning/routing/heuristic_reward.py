"""Heuristic reward function — weighted score from latency, cost, efficiency."""

from __future__ import annotations

from typing import Any

from openjarvis.learning._stubs import RewardFunction, RoutingContext


class HeuristicRewardFunction(RewardFunction):
    """Computes a scalar reward based on latency, cost, and token efficiency.

    Each component is normalised to ``[0, 1]`` and combined via a weighted sum.
    """

    def __init__(
        self,
        *,
        weight_latency: float = 0.4,
        weight_cost: float = 0.3,
        weight_efficiency: float = 0.3,
        max_latency: float = 30.0,
        max_cost: float = 0.01,
    ) -> None:
        self.weight_latency = weight_latency
        self.weight_cost = weight_cost
        self.weight_efficiency = weight_efficiency
        self.max_latency = max_latency
        self.max_cost = max_cost

    def compute(
        self,
        context: RoutingContext,
        model_key: str,
        response: str,
        **kwargs: Any,
    ) -> float:
        latency = kwargs.get("latency_seconds", 0.0)
        cost = kwargs.get("cost_usd", 0.0)
        prompt_tokens = kwargs.get("prompt_tokens", 0)
        completion_tokens = kwargs.get("completion_tokens", 0)
        total_tokens = prompt_tokens + completion_tokens

        latency_score = max(0.0, 1.0 - latency / self.max_latency)
        cost_score = max(0.0, 1.0 - cost / self.max_cost)
        efficiency_score = completion_tokens / total_tokens if total_tokens > 0 else 0.5

        reward = (
            self.weight_latency * latency_score
            + self.weight_cost * cost_score
            + self.weight_efficiency * efficiency_score
        )
        return max(0.0, min(1.0, reward))


__all__ = ["HeuristicRewardFunction"]
