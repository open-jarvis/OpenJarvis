"""daily_digest scorer — phrase match, ordering, and checklist evaluation.

Tier 1 (phrase match): Check each must-mention item against model output.
Tier 1 (ordering): Check that top-priority items appear in first half of response.
Tier 2 (checklist): Binary checklist for structure, accuracy, and actionability.

Score: (items_mentioned/total) * 0.5 + ordering_score * 0.3 + checklist * 0.2
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers._checklist import ChecklistScorer, normalize_str

LOGGER = logging.getLogger(__name__)


def _phrase_match_score(
    model_answer: str,
    must_mention: List[str],
) -> Tuple[float, List[Dict[str, Any]]]:
    """Check which must-mention items appear in model output."""
    ans_norm = normalize_str(model_answer)
    details: List[Dict[str, Any]] = []

    for item in must_mention:
        item_norm = normalize_str(item)
        words = item_norm.split()
        # Require majority of words to appear in the answer
        matched_words = sum(1 for w in words if w in ans_norm)
        found = matched_words / len(words) >= 0.6 if words else False

        details.append({"item": item, "found": found})

    total = len(must_mention)
    mentioned = sum(1 for d in details if d["found"])
    score = mentioned / total if total > 0 else 1.0

    return score, details


def _ordering_score(
    model_answer: str,
    priority_order: List[str],
) -> Tuple[float, List[Dict[str, Any]]]:
    """Check if high-priority items appear in the first half of response."""
    if not priority_order:
        return 1.0, []

    ans_norm = normalize_str(model_answer)
    midpoint = len(ans_norm) // 2
    first_half = ans_norm[:midpoint]

    details: List[Dict[str, Any]] = []
    in_first_half = 0

    for item in priority_order:
        item_norm = normalize_str(item)
        words = item_norm.split()
        matched = sum(1 for w in words if w in first_half)
        found_early = matched / len(words) >= 0.6 if words else False

        details.append({"item": item, "in_first_half": found_early})
        if found_early:
            in_first_half += 1

    score = in_first_half / len(priority_order)
    return score, details


class DailyDigestScorer(Scorer):
    """Score daily digest output by coverage, ordering, and quality."""

    scorer_id = "daily_digest"

    def __init__(
        self,
        judge_backend=None,
        judge_model: str = "",
    ) -> None:
        self._judge_backend = judge_backend
        self._judge_model = judge_model

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        must_mention = record.metadata.get("must_mention", [])
        priority_order = record.metadata.get("priority_order", [])

        if not must_mention:
            return None, {"reason": "no_must_mention_items"}

        # --- Tier 1: Phrase match ---
        phrase_score, phrase_details = _phrase_match_score(
            model_answer,
            must_mention,
        )

        # --- Tier 1: Ordering ---
        order_score, order_details = _ordering_score(
            model_answer,
            priority_order,
        )

        # --- Tier 2: Checklist ---
        checklist_score = 0.0
        checklist_details: List[Dict[str, Any]] = []

        if self._judge_backend and self._judge_model:
            items = [
                "The digest has clear sections or groupings",
                "No fabricated events or meetings are included",
                "The digest includes actionable next steps",
                "Urgent items are clearly highlighted",
                "The tone is professional and concise",
            ]
            scorer = ChecklistScorer(
                self._judge_backend,
                self._judge_model,
            )
            checklist_score, checklist_details = scorer.score_checklist(
                model_answer,
                items,
                context=record.problem,
            )
        else:
            # Heuristic fallback
            ans_lower = model_answer.lower()
            has_sections = any(
                marker in ans_lower
                for marker in ["##", "**", "---", "priority", "action"]
            )
            has_actions = any(
                kw in ans_lower for kw in ["action", "todo", "next step", "follow up"]
            )
            checklist_score = (0.5 if has_sections else 0.0) + (
                0.5 if has_actions else 0.0
            )

        # --- Composite score ---
        final_score = phrase_score * 0.5 + order_score * 0.3 + checklist_score * 0.2

        items_mentioned = sum(1 for d in phrase_details if d["found"])
        is_correct = phrase_score >= 0.8 and order_score >= 0.5 and final_score >= 0.7

        return is_correct, {
            "match_type": "daily_digest",
            "items_mentioned": items_mentioned,
            "total_items": len(must_mention),
            "phrase_score": round(phrase_score, 3),
            "ordering_score": round(order_score, 3),
            "checklist_score": round(checklist_score, 3),
            "final_score": round(final_score, 3),
            "phrase_details": phrase_details,
            "ordering_details": order_details,
            "checklist_details": checklist_details,
        }


__all__ = ["DailyDigestScorer"]
