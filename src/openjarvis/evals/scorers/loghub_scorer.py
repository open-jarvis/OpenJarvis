"""Scorer for LogHub log anomaly detection benchmark."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

_ANOMALY_PATTERN = re.compile(r"\bANOMAL(?:Y|OUS)\b", re.IGNORECASE)
_NORMAL_PATTERN = re.compile(r"\bNORMAL\b", re.IGNORECASE)


class LogHubScorer(LLMJudgeScorer):
    """Score log anomaly detection: extract ANOMALY/NORMAL classification."""

    scorer_id = "loghub"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        reference = record.reference.lower().strip()

        # Extract classification from response
        has_anomaly = bool(_ANOMALY_PATTERN.search(model_answer))
        has_normal = bool(_NORMAL_PATTERN.search(model_answer))

        if has_anomaly and not has_normal:
            predicted = "anomaly"
        elif has_normal and not has_anomaly:
            predicted = "normal"
        elif has_anomaly and has_normal:
            # Ambiguous — check which appears first
            a_pos = _ANOMALY_PATTERN.search(model_answer).start()
            n_pos = _NORMAL_PATTERN.search(model_answer).start()
            predicted = "anomaly" if a_pos < n_pos else "normal"
        else:
            # Neither keyword found — use LLM judge fallback
            return self._llm_fallback(record, model_answer)

        is_correct = predicted == reference
        return is_correct, {
            "match_type": "exact",
            "predicted": predicted,
            "reference": reference,
        }

    def _llm_fallback(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        """Use LLM judge when keyword extraction fails."""
        prompt = (
            f"A log analysis agent was asked to classify a log session.\n\n"
            f"The agent responded:\n{model_answer}\n\n"
            f"Does the agent's response indicate the logs are "
            f"ANOMALOUS or NORMAL?\n\n"
            f"Respond with exactly: ANOMALY or NORMAL"
        )
        try:
            raw = self._ask_judge(prompt, temperature=0.0, max_tokens=32)
            has_anomaly = bool(_ANOMALY_PATTERN.search(raw))
            predicted = "anomaly" if has_anomaly else "normal"
            reference = record.reference.lower().strip()
            is_correct = predicted == reference
            return is_correct, {
                "match_type": "llm_fallback",
                "predicted": predicted,
                "reference": reference,
                "raw_judge_output": raw,
            }
        except Exception as exc:
            return False, {
                "match_type": "llm_fallback_error",
                "error": str(exc),
            }
