"""LLM-judge scorer for personal benchmarks."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.backend import InferenceBackend
from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord


class PersonalBenchmarkScorer(LLMJudgeScorer):
    """Judges a candidate response against the best-known response from traces."""

    scorer_id: str = "personal_judge"

    def __init__(self, judge_backend: InferenceBackend, judge_model: str) -> None:
        super().__init__(judge_backend, judge_model)

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        """Compare *model_answer* against *record.reference* using the judge LLM.

        Returns ``(is_correct, metadata)`` where *is_correct* indicates whether
        the candidate answer is at least as good as the reference.
        """
        prompt = (
            "Compare these two answers to the query.\n\n"
            f"Query: {record.problem}\n\n"
            "Reference answer (known good):\n"
            f"{record.reference}\n\n"
            "Candidate answer:\n"
            f"{model_answer}\n\n"
            "Is the candidate answer at least as good as the reference? "
            'Respond with exactly "YES" or "NO" on the first line, '
            "then explain your reasoning."
        )
        response = self._ask_judge(
            prompt,
            system="You are an impartial quality judge.",
        )
        first_line = response.strip().split("\n")[0].strip().upper()
        is_correct = first_line.startswith("YES")
        return is_correct, {"judge_response": response}


__all__ = ["PersonalBenchmarkScorer"]
