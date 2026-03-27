"""WildChat scorer — dual-comparison LLM-as-judge.

Adapted from IPW's wildchat.py evaluation handler.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an impartial judge evaluating the quality of two AI-assistant replies to the same user prompt.

Step 1 – Generate your own answer
Write the response *you* would give to the user. Keep it separate from later analysis.

Step 2 – Decide the query type
Classify the user prompt as either
• **Subjective / open-ended** (creative writing, opinion, advice, brainstorming)
• **Objective / technical** (code, math, logical derivations with a single correct outcome)
If uncertain, default to "Subjective".

Step 3 – Score each assistant with the correct rubric

| Query type | Criteria |
|------------|----------|
| Subjective / open-ended | 1. Correctness / factual soundness 2. Helpfulness 3. Relevance 4. Conciseness 5. Creativity & novelty |
| Objective / technical   | 1. Correctness only |

When using the multi-criteria rubric, note strengths and weaknesses for **each** dimension.
When using the single-criterion rubric, focus exclusively on factual / functional accuracy and ignore style or flair.

Step 4 – Compare & justify
Explain which assistant is better and why, correcting any mistakes you find. Highlight missing but important details. **Be concise.**

Step 5 – Verdict
1. Assistant A is significantly better: [[A>>B]]
2. Assistant A is slightly better: [[A>B]]
3. Tie, Assistant A is equal: [[A=B]]
4. Assistant B is slightly better: [[B>A]]
5. Assistant B is significantly better: [[B>>A]]

Choose exactly one token from: `[[A>>B]]`, `[[A>B]]`, `[[A=B]]`, `[[B>A]]`, `[[B>>A]]`.

---

### Output format (strict)
Return **only** a JSON object that matches the provided schema:

<Your Response To The User Prompt>

```json
{
"query_type": "<query type>",
"explanation": "<multi-criteria explanation> | <single-criteria explanation> (if query_type is \\"Objective / technical\\")",
"verdict": "<one verdict token from: [[A>>B]], [[A>B]], [[A=B]], [[B>A]], [[B>>A]]>"
}
```"""


class WildChatScorer(LLMJudgeScorer):
    """Dual-comparison LLM-as-judge for chat quality."""

    scorer_id = "wildchat"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        reference = record.reference
        if not reference or not reference.strip():
            return None, {"reason": "empty_reference"}

        # Two comparisons: (model vs reference) and (reference vs model)
        verdict1, response1 = self._get_judge_verdict(
            record.problem,
            model_answer,
            reference,
        )
        verdict2, response2 = self._get_judge_verdict(
            record.problem,
            reference,
            model_answer,
        )

        if verdict1 is None or verdict2 is None:
            return None, {
                "reason": "missing_verdicts",
                "verdict1": verdict1,
                "verdict2": verdict2,
            }

        result1 = self._verdict_to_bool(verdict1, generated_is_a=True)
        result2 = self._verdict_to_bool(verdict2, generated_is_a=False)

        meta: Dict[str, Any] = {
            "generated_as_a": {"verdict": verdict1, "response": response1},
            "generated_as_b": {"verdict": verdict2, "response": response2},
        }

        if result1 is None or result2 is None:
            return None, meta

        final_result = result1 or result2
        return final_result, meta

    def _get_judge_verdict(
        self,
        problem: str,
        response_a: str,
        response_b: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        prompt = (
            f"<|User Prompt|>\n{problem}\n\n"
            f"<|The Start of Assistant A's Answer|>\n{response_a}\n"
            f"<|The End of Assistant A's Answer|>\n\n"
            f"<|The Start of Assistant B's Answer|>\n{response_b}\n"
            f"<|The End of Assistant B's Answer|>"
        )

        try:
            raw = self._ask_judge(
                prompt,
                system=SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=2048,
            )
        except Exception as exc:
            LOGGER.error("WildChat judge call failed: %s", exc)
            return None, None

        content = raw.strip()
        verdict_match = re.search(r"\[\[([AB][><=]{1,2}[AB])\]\]", content)
        if verdict_match:
            return verdict_match.group(1), content

        return None, content

    @staticmethod
    def _verdict_to_bool(
        verdict: Optional[str],
        generated_is_a: bool,
    ) -> Optional[bool]:
        if not verdict:
            return None

        verdict_map_a = {
            "A>>B": True,
            "A>B": True,
            "A=B": True,
            "B>A": False,
            "B>>A": False,
        }

        verdict_map_b = {
            "A>>B": False,
            "A>B": False,
            "A=B": True,
            "B>A": True,
            "B>>A": True,
        }

        verdict_map = verdict_map_a if generated_is_a else verdict_map_b
        return verdict_map.get(verdict)


__all__ = ["WildChatScorer"]
