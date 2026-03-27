"""Scorer for WorkArena++ enterprise workflow tasks.

Uses the native ``task.validate()`` reward from BrowserGym, which checks
the actual state of the ServiceNow instance via Playwright.  No LLM
judging — scoring is fully deterministic based on environment validation.

This mirrors the TerminalBenchNativeScorer pattern: the ``WorkArenaTaskEnv``
populates ``record.metadata["is_resolved"]`` and ``record.metadata["reward"]``
after calling ``task.validate()``, and this scorer reads those fields.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord


class WorkArenaScorer(Scorer):
    """Environment-validated scorer for WorkArena++ tasks.

    Reads ``is_resolved`` and ``reward`` from ``record.metadata``,
    populated by ``WorkArenaTaskEnv.run_tests()`` which calls the
    original ``task.validate(page, chat_messages)``.
    """

    scorer_id = "workarena"

    def __init__(
        self,
        judge_backend: object = None,
        judge_model: str = "",
    ) -> None:
        self._judge_backend = judge_backend
        self._judge_model = judge_model

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        meta = record.metadata

        is_resolved = meta.get("is_resolved")
        reward = meta.get("reward")
        test_results = meta.get("test_results")

        if is_resolved is None and reward is None and test_results is None:
            return None, {
                "reason": "no_environment_results",
                "message": (
                    "WorkArena requires a live ServiceNow instance with "
                    "BrowserGym for evaluation. Run with --agentic flag "
                    "and ensure browsergym-workarena is installed with "
                    "ServiceNow instance access configured."
                ),
            }

        result_meta: Dict[str, Any] = {
            "task_id": meta.get("task_id", ""),
            "level": meta.get("level", ""),
            "category": meta.get("category", ""),
        }

        if test_results is not None:
            result_meta["test_results"] = test_results

        if reward is not None:
            result_meta["reward"] = reward

        if is_resolved is not None:
            is_correct = bool(is_resolved)
            result_meta["is_resolved"] = is_resolved
            return is_correct, result_meta

        if reward is not None:
            is_correct = float(reward) == 1.0
            result_meta["is_resolved"] = is_correct
            return is_correct, result_meta

        return None, {
            "reason": "is_resolved_missing",
            "test_results": test_results,
        }


__all__ = ["WorkArenaScorer"]
