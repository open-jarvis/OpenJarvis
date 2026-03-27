"""browser_assistant scorer — exact match, semantic checklist, and source check.

Tier 1 (exact match): For exact facts, normalize and match numbers/names/versions.
Tier 2 (semantic checklist): For semantic facts, binary yes/no via LLM judge.
Tier 2 (quality checklist): No fabricated numbers, sources cited, answers question.
Tier 1 (sources): Check if any URL or explicit reference is mentioned.

Score: (exact/total_exact) * 0.35 + (semantic/total_semantic) * 0.35
       + quality_checklist * 0.15 + sources_cited * 0.15
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers._checklist import (
    ChecklistScorer,
    normalize_number_str,
    normalize_str,
)

LOGGER = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"https?://\S+")


def _exact_match_score(
    model_answer: str,
    exact_facts: List[str],
) -> Tuple[float, List[Dict[str, Any]]]:
    """Check if exact facts appear in model output."""
    ans_norm = normalize_str(model_answer)
    details: List[Dict[str, Any]] = []

    for fact in exact_facts:
        fact_norm = normalize_str(fact)
        words = fact_norm.split()

        # Try direct substring match first
        if fact_norm in ans_norm:
            details.append({"fact": fact, "found": True})
            continue

        # Try number matching for numeric facts
        try:
            fact_num = normalize_number_str(fact)
            if fact_num != float("inf"):
                # Look for the number in the answer
                found = str(int(fact_num)) in ans_norm or fact_norm in ans_norm
                details.append({"fact": fact, "found": found})
                continue
        except (ValueError, OverflowError):
            pass

        # Word-level match as fallback
        matched = sum(1 for w in words if w in ans_norm)
        found = matched / len(words) >= 0.6 if words else False
        details.append({"fact": fact, "found": found})

    total = len(exact_facts)
    found_count = sum(1 for d in details if d["found"])
    score = found_count / total if total > 0 else 1.0

    return score, details


def _sources_cited(model_answer: str) -> bool:
    """Check if the answer includes any URL or source references."""
    if _URL_PATTERN.search(model_answer):
        return True
    # Check for common source reference patterns
    ans_lower = model_answer.lower()
    source_indicators = [
        "source:",
        "reference:",
        "according to",
        "official documentation",
        "official docs",
        "cited from",
        "as stated in",
    ]
    return any(ind in ans_lower for ind in source_indicators)


class BrowserAssistantScorer(Scorer):
    """Score web research output by fact accuracy and sourcing."""

    scorer_id = "browser_assistant"

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

        exact_facts = record.metadata.get("exact_facts", [])
        semantic_facts = record.metadata.get("semantic_facts", [])

        if not exact_facts and not semantic_facts:
            return None, {"reason": "no_expected_facts"}

        # --- Tier 1: Exact match ---
        exact_score = 1.0
        exact_details: List[Dict[str, Any]] = []
        if exact_facts:
            exact_score, exact_details = _exact_match_score(
                model_answer,
                exact_facts,
            )

        # --- Tier 2: Semantic checklist ---
        semantic_score = 1.0
        semantic_details: List[Dict[str, Any]] = []
        if semantic_facts:
            if self._judge_backend and self._judge_model:
                scorer = ChecklistScorer(
                    self._judge_backend,
                    self._judge_model,
                )
                semantic_score, semantic_details = scorer.score_checklist(
                    model_answer,
                    [f"The answer covers: {fact}" for fact in semantic_facts],
                    context=record.problem,
                )
            else:
                # Heuristic fallback: word-level matching
                ans_norm = normalize_str(model_answer)
                matched = 0
                for fact in semantic_facts:
                    words = normalize_str(fact).split()
                    word_matches = sum(1 for w in words if w in ans_norm)
                    found = word_matches / len(words) >= 0.4 if words else False
                    semantic_details.append(
                        {"item": fact, "passed": found},
                    )
                    if found:
                        matched += 1
                semantic_score = (
                    matched / len(semantic_facts) if semantic_facts else 1.0
                )

        # --- Quality checklist ---
        quality_score = 0.0
        quality_details: List[Dict[str, Any]] = []
        if self._judge_backend and self._judge_model:
            items = [
                "No fabricated numbers or statistics",
                "Sources or references are cited",
                "Answer directly addresses the question",
            ]
            scorer = ChecklistScorer(
                self._judge_backend,
                self._judge_model,
            )
            quality_score, quality_details = scorer.score_checklist(
                model_answer,
                items,
                context=record.problem,
            )
        else:
            # Heuristic
            has_numbers = bool(re.search(r"\d+", model_answer))
            has_sources = _sources_cited(model_answer)
            quality_score = (0.5 if has_numbers else 0.0) + (
                0.5 if has_sources else 0.0
            )

        # --- Sources ---
        has_sources = _sources_cited(model_answer)
        source_score = 1.0 if has_sources else 0.0

        # --- Composite score ---
        total_exact = len(exact_facts)
        total_semantic = len(semantic_facts)
        total_all = total_exact + total_semantic

        # Weight exact and semantic proportionally
        if total_all > 0:
            exact_weight = 0.35
            semantic_weight = 0.35
        else:
            exact_weight = 0.0
            semantic_weight = 0.0

        # If no exact facts, give semantic full weight and vice versa
        if not exact_facts and semantic_facts:
            exact_weight = 0.0
            semantic_weight = 0.7
        elif exact_facts and not semantic_facts:
            exact_weight = 0.7
            semantic_weight = 0.0

        final_score = (
            exact_score * exact_weight
            + semantic_score * semantic_weight
            + quality_score * 0.15
            + source_score * 0.15
        )

        exact_found = sum(1 for d in exact_details if d["found"])
        semantic_passed = sum(1 for d in semantic_details if d.get("passed"))

        is_correct = final_score >= 0.7

        return is_correct, {
            "match_type": "browser_research",
            "exact_found": exact_found,
            "total_exact": total_exact,
            "exact_score": round(exact_score, 3),
            "semantic_passed": semantic_passed,
            "total_semantic": total_semantic,
            "semantic_score": round(semantic_score, 3),
            "quality_score": round(quality_score, 3),
            "sources_cited": has_sources,
            "final_score": round(final_score, 3),
            "exact_details": exact_details,
            "semantic_details": semantic_details,
            "quality_details": quality_details,
        }


__all__ = ["BrowserAssistantScorer"]
