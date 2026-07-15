"""SuperGPQA MCQ scorer — LLM-based letter extraction + exact match.

Adapted from IPW's mcq.py and gpqa.py evaluation handlers.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)


class SuperGPQAScorer(LLMJudgeScorer):
    """Score SuperGPQA responses by extracting answer letter via LLM."""

    scorer_id = "supergpqa"

    def _valid_letters_from_options(self, metadata: Dict[str, Any]) -> str:
        options = metadata.get("options")
        if isinstance(options, list) and options:
            n = len(options)
            return "".join(chr(ord("A") + i) for i in range(n))
        return "ABCD"

    def _extract_answer_direct(
        self,
        model_answer: str,
        valid_letters: str,
    ) -> Optional[str]:
        """High-confidence, unambiguous letter straight from the output.

        Only an explicit ``\\boxed{X}`` counts here. We deliberately do NOT regex
        prose like "the answer is X": the letters "I" and "A" are real English
        words, so "FINAL_ANSWER: I need ..." would grab "I" — the exact bug that
        mislabels answers. Semantic extraction is left to the judge below.
        """
        if not model_answer:
            return None
        for cand in reversed(re.findall(r"\\boxed\{\s*([A-Za-z])\s*\}", model_answer)):
            if cand.upper() in valid_letters:
                return cand.upper()
        return None

    def _extract_answer_with_llm(
        self,
        problem: str,
        model_answer: str,
        valid_letters: str,
    ) -> Optional[str]:
        """Use the judge LLM to extract the answer letter from the response."""
        last_letter = valid_letters[-1] if valid_letters else "D"

        system_prompt = (
            f"You are an answer extraction assistant. Extract the final multiple choice answer "
            f"from the response. Return ONLY a single letter (A-{last_letter}). "
            f"If no valid answer letter is found, return 'NONE'."
        )

        user_prompt = (
            f"Problem: {problem}\nResponse: {model_answer}\n\n"
            f"Extract the final answer letter:"
        )

        try:
            raw_response = self._ask_judge(
                user_prompt,
                system=system_prompt,
                temperature=0.0,
                max_tokens=2048,
            )

            extracted = raw_response.strip().upper()
            if "NONE" in extracted:
                return None

            # Accept only an ISOLATED letter — never the first cap of a word like
            # "It"/"None". Prefer an explicit "the answer is X" phrasing.
            answer_match = re.search(
                r"(?:THE ANSWER IS:?\s*)?\b([A-Z])\b(?![A-Za-z'])",
                extracted,
                re.IGNORECASE,
            )
            if answer_match:
                extracted = answer_match.group(1).upper()

            if extracted in valid_letters:
                return extracted

            return None

        except Exception as exc:
            LOGGER.error("Error in LLM-based answer extraction: %s", exc)
            return None

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        ref = record.reference.strip().upper()
        if not ref:
            return None, {"reason": "missing_reference_letter"}

        valid_letters = self._valid_letters_from_options(record.metadata)

        # Parse straight from the output first (fast, deterministic, no "I" bug);
        # only fall back to the judge when no isolated letter is present.
        method = "direct"
        candidate = self._extract_answer_direct(model_answer, valid_letters)
        if not candidate:
            method = "llm"
            candidate = self._extract_answer_with_llm(
                record.problem,
                model_answer,
                valid_letters,
            )
        if not candidate:
            return None, {"reason": "no_choice_letter_extracted"}

        is_correct = candidate == ref
        meta = {
            "reference_letter": ref,
            "candidate_letter": candidate,
            "valid_letters": valid_letters,
            "extract_method": method,
        }
        return is_correct, meta


__all__ = ["SuperGPQAScorer"]
