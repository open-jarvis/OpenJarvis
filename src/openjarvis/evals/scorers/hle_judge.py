"""HLE scorer -- LLM-as-judge for Humanity's Last Exam.

Uses the same exact-match-then-LLM-fallback pattern as the reasoning
judge but with an HLE-specific grading template.  Adapted from IPW's
evaluation handlers.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers.reasoning_judge import reasoning_exact_match

LOGGER = logging.getLogger(__name__)

_GRADER_TEMPLATE = """You are evaluating an AI system's answer to a challenging reasoning problem from Humanity's Last Exam (HLE).

Compare the predicted answer against the Ground Truth Answer.

Question: {question}
Ground Truth Answer: {ground_truth}
Predicted Answer: {predicted_answer}

Focus on whether the final answer is correct. These are expert-level questions, so pay close attention to precision and accuracy of the response.

Your response MUST use exactly this format:
extracted_final_answer: <the final answer extracted from the predicted answer>
reasoning: <brief explanation>
correct: <yes or no>"""


class HLEScorer(LLMJudgeScorer):
    """LLM-as-judge evaluation for HLE benchmark.

    Fast path: normalized exact match (no API call).
    Slow path: LLM judge for semantic equivalence.
    """

    scorer_id = "hle"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        reference = record.reference
        if not reference or not reference.strip():
            return None, {"reason": "no_ground_truth"}

        # Fast exact match
        if reasoning_exact_match(model_answer, reference):
            return True, {"match_type": "exact"}

        # LLM fallback
        try:
            prompt = _GRADER_TEMPLATE.format(
                question=record.problem or "(No question provided)",
                ground_truth=reference,
                predicted_answer=model_answer,
            )
            raw = self._ask_judge(prompt, temperature=0.0, max_tokens=2048)

            structured_match = re.search(
                r"^correct:\s*(yes|no)",
                raw,
                re.MULTILINE | re.IGNORECASE,
            )
            if structured_match:
                is_correct = structured_match.group(1).lower() == "yes"
            else:
                is_correct = "CORRECT" in raw.upper() and "INCORRECT" not in raw.upper()

            meta: Dict[str, Any] = {
                "match_type": "llm_fallback",
                "raw_judge_output": raw,
            }
            extracted = re.search(
                r"^extracted_final_answer:\s*(.+)",
                raw,
                re.MULTILINE,
            )
            if extracted:
                meta["extracted_answer"] = extracted.group(1).strip()

            return is_correct, meta

        except Exception as exc:
            LOGGER.error("HLE LLM judge failed: %s", exc)
            return False, {
                "match_type": "llm_fallback_error",
                "error": str(exc),
            }


__all__ = ["HLEScorer"]
