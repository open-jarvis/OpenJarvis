"""Reasoning judge scorer -- LLM-as-judge for math and reasoning tasks.

Attempts normalized exact match first, then falls back to an LLM judge
for semantic comparison.  Adapted from IPW's reasoning evaluation handlers.
"""

from __future__ import annotations

import logging
import re
import string
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _normalize_number_str(number_str: str) -> float:
    for char in ["$", "%", ","]:
        number_str = number_str.replace(char, "")
    try:
        return float(number_str)
    except ValueError:
        return float("inf")


def _normalize_str(input_str: str) -> str:
    no_spaces = re.sub(r"\s", "", input_str)
    translator = str.maketrans("", "", string.punctuation)
    return no_spaces.lower().translate(translator)


def _is_float(element: object) -> bool:
    try:
        float(element)  # type: ignore[arg-type]
        return True
    except (ValueError, TypeError):
        return False


def _extract_boxed(text: str) -> Optional[str]:
    r"""Extract content from \boxed{...} if present."""
    match = re.search(r"\\boxed\{([^}]+)\}", text)
    if match:
        return match.group(1).strip()
    return None


def reasoning_exact_match(model_answer: str, ground_truth: str) -> bool:
    """Normalized exact match for reasoning answers.

    Handles numbers, LaTeX boxed answers, and plain strings.
    """
    if model_answer is None:
        return False

    # Try extracting boxed answer from model output
    boxed = _extract_boxed(model_answer)
    if boxed is not None:
        model_answer = boxed

    # Also extract boxed from ground truth if present
    gt_boxed = _extract_boxed(ground_truth)
    if gt_boxed is not None:
        ground_truth = gt_boxed

    # Numeric comparison
    if _is_float(ground_truth):
        return _normalize_number_str(model_answer) == float(ground_truth)

    return _normalize_str(model_answer) == _normalize_str(ground_truth)


# ---------------------------------------------------------------------------
# LLM judge grading template
# ---------------------------------------------------------------------------

_GRADER_TEMPLATE = """You are evaluating an AI system's answer to a reasoning problem.

Compare the predicted answer against the Ground Truth Answer.

Question: {question}
Ground Truth Answer: {ground_truth}
Predicted Answer: {predicted_answer}

Focus on whether the final answer is mathematically/logically correct, not on the solution path.

Your response MUST use exactly this format:
extracted_final_answer: <the final answer extracted from the predicted answer>
reasoning: <brief explanation>
correct: <yes or no>"""


class ReasoningJudgeScorer(LLMJudgeScorer):
    """LLM-as-judge evaluation for reasoning tasks.

    Fast path: normalized exact match (no API call).
    Slow path: LLM judge for semantic equivalence.
    """

    scorer_id = "reasoning_judge"

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
            LOGGER.error("Reasoning LLM judge failed: %s", exc)
            return False, {
                "match_type": "llm_fallback_error",
                "error": str(exc),
            }


__all__ = ["ReasoningJudgeScorer", "reasoning_exact_match"]
