"""Scorer for PaperArena: MC exact match + LLM judge for CA/OA."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

_JUDGE_PROMPT = """You are evaluating a scientific question answer.

## Question
{question}

## Reference Answer
{reference}

## Agent's Answer
{model_answer}

Is the agent's answer correct? Consider semantic equivalence, not exact wording.
For numerical answers, accept reasonable rounding.
Respond with exactly: CORRECT or INCORRECT"""


class PaperArenaScorer(LLMJudgeScorer):
    """Score PaperArena: MC via letter extraction, CA/OA via LLM judge."""

    scorer_id = "paperarena"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        if not record.reference or not record.reference.strip():
            return None, {"reason": "no_ground_truth"}

        question_type = record.metadata.get("question_type", "OA").upper()

        if question_type == "MC":
            return self._score_mc(record, model_answer)
        else:
            return self._score_open(record, model_answer)

    def _score_mc(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        """Score multiple-choice via letter extraction."""
        ref_letter = record.reference.strip().upper()
        if len(ref_letter) != 1 or ref_letter not in "ABCD":
            # Reference is not a single letter; fall back to judge
            return self._score_open(record, model_answer)

        # Try regex extraction for answer letter
        extracted = self._extract_letter(model_answer)

        if extracted is None:
            # Fall back to LLM extraction
            extracted = self._extract_letter_with_llm(
                record.problem,
                model_answer,
            )

        if extracted is None:
            return None, {
                "match_type": "exact_letter",
                "reason": "no_letter_extracted",
            }

        is_correct = extracted == ref_letter
        return is_correct, {
            "match_type": "exact_letter",
            "reference_letter": ref_letter,
            "candidate_letter": extracted,
        }

    def _extract_letter(self, text: str) -> Optional[str]:
        """Try to extract a single answer letter from text via regex."""
        # Common patterns: "The answer is A", "A)", "(A)", just "A"
        patterns = [
            r"(?:the\s+answer\s+is|answer:?)\s*([A-D])\b",
            r"\b([A-D])\)",
            r"\(([A-D])\)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).upper()

        # Last single capital letter on its own line
        lines = text.strip().splitlines()
        for line in reversed(lines):
            stripped = line.strip()
            if len(stripped) == 1 and stripped.upper() in "ABCD":
                return stripped.upper()

        return None

    def _extract_letter_with_llm(
        self,
        problem: str,
        model_answer: str,
    ) -> Optional[str]:
        """Use LLM to extract answer letter."""
        prompt = (
            f"Extract the final answer letter (A, B, C, or D) from this response.\n"
            f"Problem: {problem[:2000]}\n"
            f"Response: {model_answer[:2000]}\n\n"
            f"Return ONLY a single letter (A-D), or NONE if no answer found."
        )
        try:
            raw = self._ask_judge(prompt, max_tokens=4096)
            letter = raw.strip().upper()
            m = re.search(r"([A-D])", letter)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    def _score_open(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        """Score CA/OA via LLM judge."""
        question = record.problem
        if "## Question" in question:
            question = question.split("## Question")[-1].strip()

        prompt = _JUDGE_PROMPT.format(
            question=question,
            reference=record.reference,
            model_answer=model_answer,
        )

        try:
            raw = self._ask_judge(prompt, max_tokens=4096)
            is_correct = bool(re.search(r"\bCORRECT\b", raw, re.IGNORECASE))
            if re.search(r"\bINCORRECT\b", raw, re.IGNORECASE):
                is_correct = False

            return is_correct, {
                "match_type": "llm_judge",
                "raw_judge_output": raw,
                "question_type": record.metadata.get("question_type", "OA"),
            }
        except Exception as exc:
            return False, {
                "match_type": "llm_judge_error",
                "error": str(exc),
            }


__all__ = ["PaperArenaScorer"]
