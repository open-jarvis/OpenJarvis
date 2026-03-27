"""Knowledge base scorer — answer correctness via normalized match + LLM fallback.

Evaluates document-grounded QA by checking if the model answer
matches the reference answer using exact match with normalization,
falling back to LLM judge for semantic comparison.
"""

from __future__ import annotations

import logging
import re
import string
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return " ".join(text.split())


def _contains_key_phrases(answer: str, reference: str) -> bool:
    """Check if answer contains the key phrases from the reference."""
    ref_norm = _normalize(reference)
    ans_norm = _normalize(answer)

    # Split reference into key phrases (sentences or comma-separated items)
    phrases = [p.strip() for p in re.split(r"[.,;]", ref_norm) if p.strip()]
    if not phrases:
        return False

    matched = sum(1 for p in phrases if p in ans_norm)
    return matched / len(phrases) >= 0.5


_LLM_JUDGE_PROMPT = """You are evaluating a knowledge base QA response.

The AI was given document excerpts and asked a question. It should answer based solely on the provided documents.

Reference answer: {reference}
AI answer: {answer}

Evaluate whether the AI's answer is correct and consistent with the reference. Minor wording differences are acceptable as long as the meaning is preserved.

Your response MUST use exactly this format:
factually_correct: <yes or no>
completeness: <complete, partial, or missing>
reasoning: <brief explanation>
overall_correct: <yes or no>"""


class KnowledgeBaseScorer(LLMJudgeScorer):
    """Score knowledge base QA: answer correctness."""

    scorer_id = "knowledge_base"

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

        # Try phrase containment check first
        if _contains_key_phrases(model_answer, reference):
            return True, {"match_type": "phrase_match"}

        # Fall back to LLM judge
        try:
            prompt = _LLM_JUDGE_PROMPT.format(
                reference=reference,
                answer=model_answer,
            )
            raw = self._ask_judge(prompt, temperature=0.0, max_tokens=512)

            overall_match = re.search(
                r"^overall_correct:\s*(yes|no)",
                raw,
                re.MULTILINE | re.IGNORECASE,
            )
            is_correct = (
                overall_match.group(1).lower() == "yes" if overall_match else False
            )

            completeness_match = re.search(
                r"^completeness:\s*(complete|partial|missing)",
                raw,
                re.MULTILINE | re.IGNORECASE,
            )
            completeness = (
                completeness_match.group(1).lower() if completeness_match else "unknown"
            )

            return is_correct, {
                "match_type": "llm_judge",
                "completeness": completeness,
                "raw_judge_output": raw,
            }
        except Exception as exc:
            LOGGER.error("Knowledge base LLM judge failed: %s", exc)
            return False, {
                "match_type": "llm_judge_error",
                "error": str(exc),
            }


__all__ = ["KnowledgeBaseScorer"]
