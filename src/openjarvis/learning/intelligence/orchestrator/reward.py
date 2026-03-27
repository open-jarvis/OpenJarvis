"""Multi-objective reward function for orchestrator training.

Adapted from IPW's ``reward.py``.  Balances accuracy, cost, energy,
latency, and power into a single scalar reward used by both the SFT
grading pipeline and the GRPO policy gradient.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from openjarvis.learning.intelligence.orchestrator.types import Episode


@dataclass
class RewardWeights:
    """Weights for multi-objective reward function.

    Each metric has its own coefficient:
    - alpha: Accuracy (correctness of answer)
    - beta_cost: API/cloud cost in USD
    - beta_energy: Energy consumption in joules
    - gamma_latency: Response time in seconds
    - gamma_power: Peak power usage in watts
    """

    alpha: float = 0.4
    beta_cost: float = 0.15
    beta_energy: float = 0.15
    gamma_latency: float = 0.15
    gamma_power: float = 0.15

    def __post_init__(self) -> None:
        """Validate weights sum to 1.0."""
        total = (
            self.alpha
            + self.beta_cost
            + self.beta_energy
            + self.gamma_latency
            + self.gamma_power
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights should sum to 1.0, got {total}")


@dataclass
class Normalizers:
    """Normalization constants for reward scaling.

    These are typical values used to scale metrics to similar ranges.
    Tune based on your specific tools and tasks.
    """

    energy_scale: float = 100.0
    cost_scale: float = 0.10
    latency_scale: float = 30.0
    power_scale: float = 200.0


class MultiObjectiveReward:
    """Multi-objective reward combining accuracy, cost, energy, latency, power.

    Formula::

        reward = alpha * accuracy
                 - beta_cost  * (cost   / cost_scale)
                 - beta_energy * (energy / energy_scale)
                 - gamma_latency * (latency / latency_scale)
                 - gamma_power   * (power   / power_scale)
    """

    def __init__(
        self,
        weights: RewardWeights,
        normalizers: Normalizers,
    ) -> None:
        self.weights = weights
        self.normalizers = normalizers

    def compute(self, episode: Episode) -> float:
        """Compute scalar reward for an episode."""
        accuracy_reward = 1.0 if episode.correct else 0.0

        cost_penalty = episode.total_cost_usd / self.normalizers.cost_scale
        energy_penalty = episode.total_energy_joules / self.normalizers.energy_scale
        latency_penalty = episode.total_latency_seconds / self.normalizers.latency_scale
        power_penalty = episode.max_power_watts / self.normalizers.power_scale

        return (
            self.weights.alpha * accuracy_reward
            - self.weights.beta_cost * cost_penalty
            - self.weights.beta_energy * energy_penalty
            - self.weights.gamma_latency * latency_penalty
            - self.weights.gamma_power * power_penalty
        )

    def compute_with_breakdown(self, episode: Episode) -> Dict[str, float]:
        """Compute reward with detailed per-component breakdown."""
        accuracy_reward = 1.0 if episode.correct else 0.0

        cost_penalty = episode.total_cost_usd / self.normalizers.cost_scale
        energy_penalty = episode.total_energy_joules / self.normalizers.energy_scale
        latency_penalty = episode.total_latency_seconds / self.normalizers.latency_scale
        power_penalty = episode.max_power_watts / self.normalizers.power_scale

        accuracy_component = self.weights.alpha * accuracy_reward
        cost_component = -self.weights.beta_cost * cost_penalty
        energy_component = -self.weights.beta_energy * energy_penalty
        latency_component = -self.weights.gamma_latency * latency_penalty
        power_component = -self.weights.gamma_power * power_penalty

        total_reward = (
            accuracy_component
            + cost_component
            + energy_component
            + latency_component
            + power_component
        )

        ipj = episode.compute_ipj()

        return {
            "total_reward": total_reward,
            "accuracy_reward": accuracy_reward,
            "accuracy_component": accuracy_component,
            "cost_penalty": cost_penalty,
            "cost_component": cost_component,
            "energy_penalty": energy_penalty,
            "energy_component": energy_component,
            "latency_penalty": latency_penalty,
            "latency_component": latency_component,
            "power_penalty": power_penalty,
            "power_component": power_component,
            "ipj": ipj,
            "total_energy_joules": episode.total_energy_joules,
            "total_cost_usd": episode.total_cost_usd,
            "total_latency_seconds": episode.total_latency_seconds,
        }

    def compute_batch(self, episodes: List[Episode]) -> List[float]:
        """Compute rewards for a batch of episodes."""
        return [self.compute(ep) for ep in episodes]


class AdaptiveRewardWeights:
    """Adaptive reward weights that shift during training.

    Early training focuses on accuracy (higher alpha).
    Late training optimises efficiency (higher cost/energy/power weights).
    """

    def __init__(
        self,
        initial_alpha: float = 0.6,
        final_alpha: float = 0.3,
        initial_beta_cost: float = 0.1,
        final_beta_cost: float = 0.15,
        initial_beta_energy: float = 0.1,
        final_beta_energy: float = 0.2,
        initial_gamma_latency: float = 0.1,
        final_gamma_latency: float = 0.15,
        initial_gamma_power: float = 0.1,
        final_gamma_power: float = 0.2,
        total_steps: int = 10000,
    ) -> None:
        self.initial_alpha = initial_alpha
        self.final_alpha = final_alpha
        self.initial_beta_cost = initial_beta_cost
        self.final_beta_cost = final_beta_cost
        self.initial_beta_energy = initial_beta_energy
        self.final_beta_energy = final_beta_energy
        self.initial_gamma_latency = initial_gamma_latency
        self.final_gamma_latency = final_gamma_latency
        self.initial_gamma_power = initial_gamma_power
        self.final_gamma_power = final_gamma_power
        self.total_steps = total_steps

    def get_weights(self, current_step: int) -> RewardWeights:
        """Get weights for *current_step* via linear interpolation."""
        progress = min(1.0, current_step / self.total_steps)

        alpha = self.initial_alpha + (self.final_alpha - self.initial_alpha) * progress
        beta_cost = (
            self.initial_beta_cost
            + (self.final_beta_cost - self.initial_beta_cost) * progress
        )
        beta_energy = (
            self.initial_beta_energy
            + (self.final_beta_energy - self.initial_beta_energy) * progress
        )
        gamma_latency = (
            self.initial_gamma_latency
            + (self.final_gamma_latency - self.initial_gamma_latency) * progress
        )
        gamma_power = (
            self.initial_gamma_power
            + (self.final_gamma_power - self.initial_gamma_power) * progress
        )

        # Normalize to sum to 1.0
        total = alpha + beta_cost + beta_energy + gamma_latency + gamma_power
        return RewardWeights(
            alpha=alpha / total,
            beta_cost=beta_cost / total,
            beta_energy=beta_energy / total,
            gamma_latency=gamma_latency / total,
            gamma_power=gamma_power / total,
        )


__all__ = [
    "AdaptiveRewardWeights",
    "MultiObjectiveReward",
    "Normalizers",
    "RewardWeights",
]
