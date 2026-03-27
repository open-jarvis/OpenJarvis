"""doc_qa scorer — fact match, citation check, and checklist evaluation.

Tier 1 (fact match): Check if model answer contains each required fact.
Tier 1 (citation check): Verify document citations match expected sources.
Tier 2 (checklist): Binary checklist for grounding and accuracy.

Score: (facts_found/total) * 0.5 + (citations_correct/citations_made) * 0.3 + checklist * 0.2
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers._checklist import ChecklistScorer, normalize_str

LOGGER = logging.getLogger(__name__)

# Patterns for document citations: [Doc 1], [Document 3], (Doc 2), etc.
_CITATION_PATTERN = re.compile(
    r"\[?\s*(?:Doc(?:ument)?|Source)\s*(\d+)\s*\]?",
    re.IGNORECASE,
)


def _fact_match_score(
    model_answer: str,
    required_facts: List[Dict[str, Any]],
) -> Tuple[float, List[Dict[str, Any]]]:
    """Check which required facts appear in model output."""
    ans_norm = normalize_str(model_answer)
    details: List[Dict[str, Any]] = []

    for fact_entry in required_facts:
        fact = fact_entry["fact"]
        fact_norm = normalize_str(fact)
        words = fact_norm.split()
        # Require majority of words to appear
        matched = sum(1 for w in words if w in ans_norm)
        found = matched / len(words) >= 0.6 if words else False

        details.append(
            {
                "fact": fact,
                "expected_source": fact_entry.get("source_doc_index"),
                "found": found,
            }
        )

    total = len(required_facts)
    found_count = sum(1 for d in details if d["found"])
    score = found_count / total if total > 0 else 1.0

    return score, details


def _citation_check_score(
    model_answer: str,
    required_facts: List[Dict[str, Any]],
) -> Tuple[float, List[Dict[str, Any]]]:
    """Check if cited document indices match expected sources."""
    # Extract all citations from the answer
    citations = _CITATION_PATTERN.findall(model_answer)
    cited_indices = {int(c) - 1 for c in citations}  # 1-indexed to 0-indexed

    if not citations:
        return 0.0, [{"note": "no citations found in answer"}]

    # Check which expected sources are cited
    expected_sources = {
        f.get("source_doc_index")
        for f in required_facts
        if f.get("source_doc_index") is not None
    }

    details: List[Dict[str, Any]] = []
    correct = 0

    for src in expected_sources:
        is_cited = src in cited_indices
        if is_cited:
            correct += 1
        details.append(
            {
                "expected_doc_index": src,
                "cited": is_cited,
            }
        )

    total = len(expected_sources)
    score = correct / total if total > 0 else 0.0

    return score, details


class DocQAScorer(Scorer):
    """Score document QA output by fact coverage, citations, and quality."""

    scorer_id = "doc_qa"

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

        required_facts = record.metadata.get("required_facts", [])
        if not required_facts:
            return None, {"reason": "no_required_facts"}

        # --- Tier 1: Fact match ---
        fact_score, fact_details = _fact_match_score(
            model_answer,
            required_facts,
        )

        # --- Tier 1: Citation check ---
        citation_score, citation_details = _citation_check_score(
            model_answer,
            required_facts,
        )

        # --- Tier 2: Checklist ---
        checklist_score = 0.0
        checklist_details: List[Dict[str, Any]] = []

        if self._judge_backend and self._judge_model:
            items = [
                "Answer uses only facts from the provided documents",
                "Answer directly addresses the question asked",
                "No hallucinated parameters, commands, or facts",
                "Citations are present and properly formatted",
                "Answer is well-organized and clear",
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
            has_citations = bool(_CITATION_PATTERN.search(model_answer))
            has_structure = any(m in ans_lower for m in ["##", "**", "- ", "1."])
            checklist_score = (0.5 if has_citations else 0.0) + (
                0.5 if has_structure else 0.0
            )

        # --- Composite score ---
        final_score = fact_score * 0.5 + citation_score * 0.3 + checklist_score * 0.2

        facts_found = sum(1 for d in fact_details if d["found"])
        is_correct = fact_score >= 0.8 and citation_score >= 0.5 and final_score >= 0.7

        return is_correct, {
            "match_type": "doc_qa",
            "facts_found": facts_found,
            "total_facts": len(required_facts),
            "fact_score": round(fact_score, 3),
            "citation_score": round(citation_score, 3),
            "checklist_score": round(checklist_score, 3),
            "final_score": round(final_score, 3),
            "fact_details": fact_details,
            "citation_details": citation_details,
            "checklist_details": checklist_details,
        }


__all__ = ["DocQAScorer"]
