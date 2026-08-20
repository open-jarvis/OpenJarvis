"""LLM-judge scorer for AMA-Bench agent memory assessment.

Follows the evaluation protocol from the AMA-Bench paper (Appendix C.1):
- Judge receives (question, reference_answer, predicted_answer) triplet
- Returns binary yes/no decision
- Reports both Accuracy (judge-based) and token-level F1
"""

from __future__ import annotations

import logging
import re
import string
from collections import Counter
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

# Prompt from AMA-Bench paper Appendix C.1 (Binary Correctness Judgement)
_JUDGE_SYSTEM = (
    "You are an expert evaluator. You will be given a question, "
    "a reference answer, and a predicted answer.\n"
    "Your task is to determine if the predicted answer is correct based on:\n"
    "1. Factual correctness compared to the reference\n"
    "2. Completeness of the answer\n"
    "3. Relevance to the question"
)

_JUDGE_PROMPT = (
    "Question: {question}\n\n"
    "Reference Answer: {reference}\n\n"
    "Predicted Answer: {predicted_answer}\n\n"
    "Is the predicted answer correct? "
    "Respond with ONLY 'yes' or 'no'. "
    "Do not include any thinking process, explanation, or additional text.\n"
    "Answer:"
)

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _compute_token_f1(prediction: str, reference: str) -> float:
    """Compute token-level F1 between prediction and reference (SQuAD-style)."""
    pred_tokens = _normalize_and_tokenize(prediction)
    ref_tokens = _normalize_and_tokenize(reference)
    if not ref_tokens:
        return 1.0 if not pred_tokens else 0.0
    if not pred_tokens:
        return 0.0
    common = Counter(pred_tokens) & Counter(ref_tokens)
    num_common = sum(common.values())
    if num_common == 0:
        return 0.0
    precision = num_common / len(pred_tokens)
    recall = num_common / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def _normalize_and_tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, collapse whitespace, tokenize."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return text.split()


class AMABenchScorer(LLMJudgeScorer):
    """Score AMA-Bench QA via LLM judge + token F1.

    Follows the paper's evaluation protocol: Accuracy via LLM-as-judge
    (Qwen3-32B recommended) plus token-level F1 as a secondary metric.
    """

    scorer_id = "ama-bench"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response", "f1": 0.0}

        if not record.reference or not record.reference.strip():
            return None, {"reason": "no_ground_truth"}

        question = record.problem
        if "## Question" in question:
            question = question.split("## Question")[-1].strip()

        f1 = _compute_token_f1(model_answer, record.reference)

        prompt = _JUDGE_PROMPT.format(
            question=question,
            reference=record.reference,
            predicted_answer=model_answer,
        )

        raw = self._ask_judge(
            prompt,
            system=_JUDGE_SYSTEM,
            temperature=0.0,
            max_tokens=128,
        )
        label = _parse_judge_label(raw)
        if label is None:
            LOGGER.warning(
                "AMA-Bench judge returned unparseable output for %s, "
                "falling back to F1 threshold: %r",
                record.record_id,
                raw[:200],
            )
            is_correct = f1 >= 0.5
            return is_correct, {
                "match_type": "f1_fallback",
                "raw_judge_output": raw[:200],
                "f1": round(f1, 4),
                "capability": record.metadata.get("capability", ""),
                "judge_parse_failed": True,
            }

        return label == "yes", {
            "match_type": "llm_judge",
            "raw_judge_output": raw,
            "f1": round(f1, 4),
            "capability": record.metadata.get("capability", ""),
        }


def _parse_judge_label(raw: str) -> Optional[str]:
    """Parse binary yes/no label from judge response.

    Handles models that emit <think>...</think> blocks before the answer,
    and various formatting quirks.
    """
    text = raw.strip().lower()

    # Strip thinking tags (Qwen3, etc.)
    text = _THINK_TAG_RE.sub("", text).strip()

    # Direct match
    if text in ("yes", "no"):
        return text

    # Check each line for a bare yes/no token
    for line in text.splitlines():
        tok = line.strip().rstrip(".:,").lower()
        if tok in ("yes", "no"):
            return tok

    # Last resort: search for yes/no anywhere in the cleaned text
    if re.search(r"\byes\b", text):
        return "yes"
    if re.search(r"\bno\b", text):
        return "no"

    return None
