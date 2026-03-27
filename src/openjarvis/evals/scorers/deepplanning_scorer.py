"""LLM-judge scorer for DeepPlanning constraint satisfaction."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

_JUDGE_PROMPT = """You are evaluating a planning task response.

## Task Type: {task_type}

## Original Task
{problem}

## Reference Plan
{reference}

## Agent's Plan
{model_answer}

Evaluate whether the agent's plan satisfies ALL constraints from the task.

For travel planning, check:
- Route consistency and feasibility
- Time feasibility (business hours, travel times)
- Budget accuracy (costs within stated limits)
- Personalization requirements met

For shopping tasks, check:
- Correct products selected
- Coupon/discount rules applied correctly
- Cart total accuracy

Respond with exactly: CORRECT or INCORRECT
Then provide a brief explanation."""


class DeepPlanningScorer(LLMJudgeScorer):
    """Score DeepPlanning responses via LLM judge on constraint satisfaction."""

    scorer_id = "deepplanning"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        if not record.reference or not record.reference.strip():
            return None, {"reason": "no_ground_truth"}

        task_type = record.metadata.get("task_type", "planning")

        # Extract problem without system prompt prefix
        problem = record.problem
        if "## Task" in problem:
            problem = problem.split("## Task", 1)[-1]

        prompt = _JUDGE_PROMPT.format(
            task_type=task_type,
            problem=problem,
            reference=record.reference,
            model_answer=model_answer,
        )

        try:
            raw = self._ask_judge(prompt, max_tokens=4096)
            is_correct = bool(re.search(r"\bCORRECT\b", raw, re.IGNORECASE))
            if re.search(r"\bINCORRECT\b", raw, re.IGNORECASE):
                is_correct = False

            return is_correct, {
                "match_type": "llm_judge",
                "raw_judge_output": raw,
                "task_type": task_type,
            }
        except Exception as exc:
            return False, {
                "match_type": "llm_judge_error",
                "error": str(exc),
            }


__all__ = ["DeepPlanningScorer"]
