"""SimpleQA scorer -- normalized exact match with LLM fallback.

Evaluates short factual answers using exact string matching (with
normalization) and falls back to an LLM judge for semantic comparison.
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
# Normalization helpers (shared with GAIA scorer)
# ---------------------------------------------------------------------------


def _normalize_number_str(number_str: str) -> float:
    for char in ["$", "%", ","]:
        number_str = number_str.replace(char, "")
    try:
        return float(number_str)
    except ValueError:
        return float("inf")


def _normalize_str(input_str: str, remove_punct: bool = True) -> str:
    no_spaces = re.sub(r"\s", "", input_str)
    if remove_punct:
        translator = str.maketrans("", "", string.punctuation)
        return no_spaces.lower().translate(translator)
    return no_spaces.lower()


def _is_float(element: object) -> bool:
    try:
        float(element)  # type: ignore[arg-type]
        return True
    except (ValueError, TypeError):
        return False


def exact_match(model_answer: str, ground_truth: str) -> bool:
    """Exact-match scorer with normalization for numbers and strings."""
    if model_answer is None:
        model_answer = "None"

    if _is_float(ground_truth):
        normalized = _normalize_number_str(model_answer)
        return normalized == float(ground_truth)

    return _normalize_str(model_answer) == _normalize_str(ground_truth)


# ---------------------------------------------------------------------------
# LLM fallback prompt
# ---------------------------------------------------------------------------

_LLM_FALLBACK_PROMPT = """You are evaluating whether a predicted answer matches the gold answer for a factual question.

Question: {question}
Gold answer: {gold_answer}
Predicted answer: {predicted_answer}

The answers should be semantically equivalent. Minor differences in formatting, capitalization, or phrasing are acceptable.

Your response MUST use exactly this format:
extracted_final_answer: <extracted answer from prediction>
reasoning: <brief explanation>
correct: <yes or no>"""


class SimpleQAScorer(LLMJudgeScorer):
    """SimpleQA evaluation: exact match with normalization + LLM fallback."""

    scorer_id = "simpleqa"

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

        # Try exact match first (fast, no API call)
        if exact_match(model_answer, reference):
            return True, {"match_type": "exact"}

        # LLM fallback for semantic comparison
        try:
            prompt = _LLM_FALLBACK_PROMPT.format(
                question=record.problem or "(No question provided)",
                gold_answer=reference,
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
            extracted_match = re.search(
                r"^extracted_final_answer:\s*(.+)",
                raw,
                re.MULTILINE,
            )
            if extracted_match:
                meta["extracted_answer"] = extracted_match.group(1).strip()

            return is_correct, meta

        except Exception as exc:
            LOGGER.error("SimpleQA LLM fallback failed: %s", exc)
            return False, {
                "match_type": "llm_fallback_error",
                "error": str(exc),
            }


__all__ = ["SimpleQAScorer", "exact_match"]
