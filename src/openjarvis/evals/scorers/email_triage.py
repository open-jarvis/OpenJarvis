"""Email triage scorer — classification accuracy + draft quality.

Scores urgency and category via exact match, with LLM fallback
for draft reply quality assessment.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_DRAFT_JUDGE_PROMPT = """You are evaluating an AI-generated email triage response.

The AI was asked to classify an email and draft a reply.

Reference classification:
{reference}

AI response:
{response}

Evaluate:
1. Did the AI correctly identify the urgency level? (critical/high/medium/low)
2. Did the AI correctly identify the category? (action/decision/info/social)
3. Is the draft reply appropriate, professional, and helpful?

Your response MUST use exactly this format:
urgency_correct: <yes or no>
category_correct: <yes or no>
draft_quality: <good, acceptable, or poor>
reasoning: <brief explanation>
overall_correct: <yes or no>"""


def _extract_field(text: str, field: str) -> str:
    """Extract a field value from structured model output."""
    match = re.search(
        rf"^{field}\s*:\s*(.+)",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).strip().lower() if match else ""


class EmailTriageScorer(LLMJudgeScorer):
    """Score email triage: classification accuracy + draft quality."""

    scorer_id = "email_triage"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        ref_urgency = record.metadata.get("urgency", "")
        ref_category = record.metadata.get("category", "")

        # Try exact field extraction first
        pred_urgency = _extract_field(model_answer, "urgency")
        pred_category = _extract_field(model_answer, "category")

        urgency_match = pred_urgency == ref_urgency
        category_match = pred_category == ref_category

        # If both match exactly, score as correct without LLM call
        if urgency_match and category_match:
            return True, {
                "match_type": "exact",
                "urgency_correct": True,
                "category_correct": True,
                "pred_urgency": pred_urgency,
                "pred_category": pred_category,
            }

        # Fall back to LLM judge for ambiguous cases
        try:
            prompt = _DRAFT_JUDGE_PROMPT.format(
                reference=record.reference,
                response=model_answer,
            )
            raw = self._ask_judge(prompt, temperature=0.0, max_tokens=512)

            overall_match = re.search(
                r"^overall_correct:\s*(yes|no)",
                raw,
                re.MULTILINE | re.IGNORECASE,
            )
            is_correct = (
                overall_match.group(1).lower() == "yes"
                if overall_match
                else (urgency_match and category_match)
            )

            urg_match = re.search(
                r"^urgency_correct:\s*(yes|no)",
                raw,
                re.MULTILINE | re.IGNORECASE,
            )
            cat_match = re.search(
                r"^category_correct:\s*(yes|no)",
                raw,
                re.MULTILINE | re.IGNORECASE,
            )

            return is_correct, {
                "match_type": "llm_judge",
                "urgency_correct": (
                    urg_match.group(1).lower() == "yes" if urg_match else urgency_match
                ),
                "category_correct": (
                    cat_match.group(1).lower() == "yes" if cat_match else category_match
                ),
                "pred_urgency": pred_urgency,
                "pred_category": pred_category,
                "raw_judge_output": raw,
            }
        except Exception as exc:
            LOGGER.error("Email triage LLM judge failed: %s", exc)
            return urgency_match and category_match, {
                "match_type": "exact_fallback",
                "urgency_correct": urgency_match,
                "category_correct": category_match,
                "error": str(exc),
            }


__all__ = ["EmailTriageScorer"]
