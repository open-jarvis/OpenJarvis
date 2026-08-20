"""TauBench scorer — wraps tau2-bench's evaluation results.

Since TauBench runs its own simulation loop (agent + user simulator +
tools + evaluation), the scorer simply reads the reward that was
computed during task execution and stored in record.metadata.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord


class TauBenchScorer(Scorer):
    """TauBench scorer — reads pre-computed rewards from tau2-bench.

    The actual evaluation (DB state checks, action matching,
    communication checks, NL assertions) is done by tau2-bench's
    evaluator during simulation. This scorer extracts the result.
    """

    scorer_id = "taubench"

    def __init__(self, judge_backend: Any = None, judge_model: str = "") -> None:
        self._judge_backend = judge_backend
        self._judge_model = judge_model

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        reward = record.metadata.get("tau_reward", 0.0)
        info = record.metadata.get("tau_info", {})
        n_messages = record.metadata.get("tau_n_messages", 0)

        is_correct = reward >= 0.5

        return is_correct, {
            "score": reward,
            "breakdown": info,
            "notes": f"reward={reward:.2f}, messages={n_messages}",
        }


__all__ = ["TauBenchScorer"]
