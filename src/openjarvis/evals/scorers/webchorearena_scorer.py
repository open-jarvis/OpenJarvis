"""Scorer for WebChoreArena web chore tasks.

Uses the environment-validated scoring pattern (same as WorkArenaScorer):
the ``WebChoreArenaTaskEnv`` runs the original WebArena evaluation harness
(StringEvaluator × URLEvaluator × HTMLContentEvaluator, multiplicative)
and populates ``record.metadata["is_resolved"]`` and ``record.metadata["reward"]``.
This scorer reads those fields.

The evaluation harness inside the task env faithfully mirrors the original:
- StringEvaluator: exact_match, must_include (with |OR| support), fuzzy_match
  (LLM-judged via GPT-4o), ua_match (unachievable task detection)
- URLEvaluator: checks browser's current page URL against reference URLs
- HTMLContentEvaluator: navigates to URLs, runs JS locators on DOM, checks
  element content against expected values
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord


class WebChoreArenaScorer(Scorer):
    """Environment-validated scorer for WebChoreArena tasks.

    Reads ``is_resolved`` and ``reward`` from ``record.metadata``,
    populated by ``WebChoreArenaTaskEnv._run_evaluation()`` which runs
    the original WebArena evaluation harness against the live browser state.
    """

    scorer_id = "webchorearena"

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
                    "WebChoreArena requires a live WebArena standalone "
                    "environment with Playwright for evaluation. Ensure "
                    "the WebArena sites (Shopping, Reddit, GitLab, etc.) "
                    "are running and configured via environment variables."
                ),
            }

        result_meta: Dict[str, Any] = {
            "task_id": meta.get("task_id", ""),
            "site": meta.get("site", ""),
            "type_main": meta.get("type_main", ""),
            "type_sub": meta.get("type_sub", ""),
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


__all__ = ["WebChoreArenaScorer"]
