"""Pick the best paradigm rendering per task.

The label for SFT is the *cheapest strategy that still solves the task*: among
the predicted-correct renderings, keep the one with the highest multi-objective
reward (accuracy minus cost/energy/latency/power). This is the local-first
thesis expressed as a training target.
"""

from __future__ import annotations

from typing import List, Optional

from openjarvis.learning.intelligence.orchestrator.reward import (
    MultiObjectiveReward,
    Normalizers,
    RewardWeights,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.paradigms import (
    RenderedEpisode,
)

_DEFAULT_REWARD = MultiObjectiveReward(RewardWeights(), Normalizers())


def select_best(
    renderings: List[RenderedEpisode],
    *,
    reward: Optional[MultiObjectiveReward] = None,
) -> Optional[RenderedEpisode]:
    """Return the highest-reward predicted-correct rendering, or ``None``.

    ``None`` means no paradigm was predicted to solve the task — the task is
    dropped from the SFT set rather than teaching a wrong trajectory.
    """
    scorer = reward or _DEFAULT_REWARD
    correct = [r for r in renderings if r.predicted_correct]
    if not correct:
        return None
    return max(correct, key=lambda r: scorer.compute(r.episode))


__all__ = ["select_best"]
