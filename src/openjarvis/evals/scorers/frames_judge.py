"""FRAMES scorer — LLM-as-judge for multi-hop factual retrieval.

Adapted from IPW's frames.py evaluation handler.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_GRADER_TEMPLATE = """You are evaluating an AI system's answer to a multi-hop factual question.

Compare the predicted answer against the Ground Truth Answer and determine if the prediction is correct.

## Evaluation Guidelines

1. **Focus on semantic meaning**: Look for equivalent information - exact wording is not required.
2. **Assess factual accuracy**: Determine whether the essential facts from the Ground Truth are present in the answer.
3. **Ignore minor differences**: Capitalization, punctuation, formatting, and word order don't matter.
4. **Partial credit**: If the Ground Truth has multiple parts, all essential parts must be present for a correct rating.
5. **Additional information**: Extra correct information in the prediction is acceptable, but extra incorrect information is not.

## Question
{question}

## Ground Truth Answer
{ground_truth}

## Predicted Answer
{predicted_answer}

Your response MUST use exactly this format:
extracted_final_answer: <the final answer extracted from the predicted answer, or 'None' if no answer is present>
reasoning: <brief explanation of why the extracted answer is or is not correct>
correct: <yes or no>"""


class FRAMESScorer(LLMJudgeScorer):
    """LLM-as-judge evaluation for FRAMES multi-hop factual retrieval."""

    scorer_id = "frames"

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

        prompt = _GRADER_TEMPLATE.format(
            question=record.problem,
            ground_truth=reference,
            predicted_answer=model_answer,
        )

        try:
            raw = self._ask_judge(prompt, temperature=0.0, max_tokens=2048)

            structured_match = re.search(
                r"^correct:\s*(yes|no)",
                raw,
                re.MULTILINE | re.IGNORECASE,
            )
            if structured_match:
                is_correct = structured_match.group(1).lower() == "yes"
            else:
                response_upper = raw.upper().strip()
                if "TRUE" in response_upper:
                    is_correct = True
                elif "FALSE" in response_upper:
                    is_correct = False
                else:
                    LOGGER.warning("Could not parse grade from response: %s", raw[:50])
                    is_correct = False

            meta: Dict[str, Any] = {
                "raw_judge_output": raw,
            }
            extracted = re.search(
                r"^extracted_final_answer:\s*(.+)",
                raw,
                re.MULTILINE,
            )
            if extracted:
                meta["extracted_answer"] = extracted.group(1).strip()

            return is_correct, meta

        except Exception as exc:
            LOGGER.error("FRAMES scoring failed: %s", exc)
            return None, {"error": str(exc)}


__all__ = ["FRAMESScorer"]
