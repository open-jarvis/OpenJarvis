"""Shared binary checklist scorer and text normalization utilities.

Provides:
- ChecklistScorer: evaluates model output against yes/no checklist items
  via a single LLM judge call.
- normalize_str(): lowercase, strip punctuation, collapse whitespace.
- normalize_number_str(): parse numeric strings (strip $, %, commas).
- contains_key_phrases(): check if answer contains >=threshold of reference phrases.
"""

from __future__ import annotations

import logging
import re
import string
from typing import Any, Dict, List, Tuple

LOGGER = logging.getLogger(__name__)


def normalize_str(text: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return " ".join(text.split())


def normalize_number_str(number_str: str) -> float:
    """Strip currency/percent symbols and parse as float."""
    for char in ["$", "%", ","]:
        number_str = number_str.replace(char, "")
    try:
        return float(number_str)
    except ValueError:
        return float("inf")


def contains_key_phrases(
    answer: str,
    reference: str,
    threshold: float = 0.5,
) -> bool:
    """Check if answer contains >=threshold of reference key phrases."""
    ans_norm = normalize_str(answer)

    # Split on delimiters BEFORE normalizing, so punctuation-based delimiters work
    raw_phrases = [p.strip() for p in re.split(r"[.,;]", reference) if p.strip()]
    phrases = [normalize_str(p) for p in raw_phrases if normalize_str(p)]
    if not phrases:
        return False

    matched = sum(1 for p in phrases if p in ans_norm)
    return matched / len(phrases) >= threshold


_CHECKLIST_JUDGE_PROMPT = """You are evaluating an AI response against a checklist of binary criteria.

For each numbered item below, answer YES or NO, followed by a brief reason.

Context (the original task):
{context}

AI response to evaluate:
{response}

Checklist:
{checklist_text}

Respond with exactly one line per item in this format:
<number>. <yes or no> — <brief reason>
"""


class ChecklistScorer:
    """Scores model output against binary yes/no checklist items.

    Makes a single LLM call for all items (not one per item).
    Returns (score, details) where score = items_passed / total.
    """

    def __init__(self, judge_backend, judge_model: str) -> None:
        self._judge_backend = judge_backend
        self._judge_model = judge_model

    def score_checklist(
        self,
        model_answer: str,
        checklist: List[str],
        context: str = "",
    ) -> Tuple[float, List[Dict[str, Any]]]:
        """Evaluate model_answer against checklist items.

        Returns (score, details) where:
          score = passed_items / total_items (0.0 to 1.0)
          details = [{"item": str, "passed": bool, "reasoning": str}, ...]
        """
        if not model_answer or not model_answer.strip():
            return 0.0, [
                {"item": item, "passed": False, "reasoning": "empty response"}
                for item in checklist
            ]

        if not checklist:
            return 1.0, []

        checklist_text = "\n".join(
            f"{i + 1}. {item}" for i, item in enumerate(checklist)
        )

        prompt = _CHECKLIST_JUDGE_PROMPT.format(
            context=context[:1000],
            response=model_answer[:3000],
            checklist_text=checklist_text,
        )

        try:
            raw = self._judge_backend.generate(
                prompt,
                model=self._judge_model,
                system="You are a precise evaluator. Answer YES or NO for each item.",
                temperature=0.0,
                max_tokens=1024,
            )
        except Exception as exc:
            LOGGER.error("Checklist judge failed: %s", exc)
            return 0.0, [
                {"item": item, "passed": False, "reasoning": f"judge error: {exc}"}
                for item in checklist
            ]

        details = self._parse_response(raw, checklist)
        passed = sum(1 for d in details if d["passed"])
        score = passed / len(details) if details else 0.0

        return score, details

    def _parse_response(
        self,
        raw: str,
        checklist: List[str],
    ) -> List[Dict[str, Any]]:
        """Parse the judge response into per-item results."""
        details: List[Dict[str, Any]] = []

        for i, item in enumerate(checklist):
            pattern = rf"(?:^|\n)\s*{i + 1}\.\s*(yes|no)\b\s*(?:—|-)?\s*(.*)"
            match = re.search(pattern, raw, re.IGNORECASE)

            if match:
                passed = match.group(1).lower() == "yes"
                reasoning = match.group(2).strip() if match.group(2) else ""
            else:
                passed = False
                reasoning = "could not parse judge response"

            details.append(
                {
                    "item": item,
                    "passed": passed,
                    "reasoning": reasoning,
                }
            )

        return details


__all__ = [
    "ChecklistScorer",
    "contains_key_phrases",
    "normalize_number_str",
    "normalize_str",
]
