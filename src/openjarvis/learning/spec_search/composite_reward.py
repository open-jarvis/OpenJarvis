"""Composite reward for Intelligence-edit training (paper §3.3, Eq. 1).

R(q, y) = alpha * R_acc(q, y) - beta * E_hat(q, y)
                              - gamma * L_hat(q, y)
                              - delta * C_hat(q, y)

The efficiency quantities (E, L, C) are normalised within the evaluated
benchmark before weighting (z-score), so the reward trades dimensionless
deviations rather than raw joules / seconds / dollars (paper Appendix C.6).

Default weights (alpha, beta, gamma, delta) = (0.5, 0.1, 0.1, 0.3).

This reward is consumed only inside an Intelligence edit that triggers
training (LoRA/GRPO). The held-out gate (BenchmarkGate) evaluates the
resulting spec end-to-end and is not affected by these weights.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True, frozen=True)
class RewardWeights:
    """Composite-reward weights from paper Eq. 1."""

    alpha: float = 0.5
    beta: float = 0.1
    gamma: float = 0.1
    delta: float = 0.3


@dataclass(slots=True, frozen=True)
class TrainingSample:
    """One (query, response) candidate scored during Intelligence training.

    All efficiency quantities are raw (un-normalised); normalisation is
    applied across the batch by ``score_batch``.
    """

    accuracy: float  # 0..1; for binary tasks, 0 or 1
    energy_joules: float
    latency_seconds: float
    cost_usd: float


def _zscore(values: Sequence[float]) -> list[float]:
    """Per-batch z-score; returns zeros if the batch has zero variance.

    Within-batch normalisation is the paper's choice (Appendix C.6) so
    the composite reward trades dimensionless deviations.
    """
    if not values:
        return []
    mean = statistics.fmean(values)
    if len(values) < 2:
        return [0.0] * len(values)
    stdev = statistics.pstdev(values)
    if stdev == 0.0:
        return [0.0] * len(values)
    return [(v - mean) / stdev for v in values]


def score_batch(
    samples: Sequence[TrainingSample],
    weights: RewardWeights | None = None,
) -> list[float]:
    """Score a batch of candidates with the paper's composite reward.

    Energy / latency / cost are z-scored within the batch before being
    weighted, so the reward magnitudes are comparable across benchmarks
    and hardware platforms.

    Args:
        samples: candidate (query, response) pairs to score.
        weights: composite-reward weights; uses paper defaults if None.

    Returns:
        One scalar reward per sample, in the same order.
    """
    w = weights or RewardWeights()
    if not samples:
        return []

    e_norm = _zscore([s.energy_joules for s in samples])
    l_norm = _zscore([s.latency_seconds for s in samples])
    c_norm = _zscore([s.cost_usd for s in samples])

    return [
        w.alpha * s.accuracy - w.beta * e - w.gamma * lat - w.delta * cost
        for s, e, lat, cost in zip(samples, e_norm, l_norm, c_norm)
    ]


__all__ = ["RewardWeights", "TrainingSample", "score_batch"]
