"""LiveResearchBench (Salesforce) scorer — checklist-based evaluation.

Evaluates research reports using per-question checklists for coverage,
plus LLM-as-judge for presentation quality and citation adequacy.

Reference: https://github.com/SalesforceAIResearch/LiveResearchBench
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_COVERAGE_PROMPT = """\
You are evaluating a research report against a checklist of required topics/points.

**Research Question:**
{question}

**Report:**
{report}

**Checklist items to verify (each should be covered in the report):**
{checklist_items}

For each checklist item, determine if the report adequately covers it.
Respond with a JSON array of objects, one per checklist item:
[
  {{"item": "<checklist item text>", "covered": true/false, "evidence": "<brief quote or reason>"}},
  ...
]

Then on the last line, provide the overall coverage score:
coverage_score: <number of covered items>/<total items>"""

_QUALITY_PROMPT = """\
You are evaluating the quality of a research report.

**Research Question:**
{question}

**Report:**
{report}

Rate the report on these dimensions (each 1-5):

1. **Presentation**: Is the report well-structured, readable, and professional?
2. **Depth**: Does the report go beyond surface-level information?
3. **Citation**: Does the report reference specific sources, data, or evidence?
4. **Consistency**: Is the report internally consistent and free of contradictions?

Respond in this exact format:
presentation: <1-5>
depth: <1-5>
citation: <1-5>
consistency: <1-5>
reasoning: <brief explanation>"""


class LiveResearchBenchSFScorer(LLMJudgeScorer):
    """Checklist + quality scorer for Salesforce LiveResearchBench."""

    scorer_id = "liveresearchbench"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response", "score": 0.0}

        question = record.metadata.get("original_question", record.problem)
        checklists = record.metadata.get("checklists", [])

        meta: Dict[str, Any] = {}

        # Phase 1: Checklist coverage (if available)
        coverage_score = 0.0
        if checklists:
            try:
                checklist_text = "\n".join(
                    f"- {item}" for item in checklists
                )
                prompt = _COVERAGE_PROMPT.format(
                    question=question,
                    report=model_answer[:8000],  # Truncate long reports
                    checklist_items=checklist_text,
                )
                raw = self._ask_judge(
                    prompt, temperature=1.0, max_tokens=4096
                )

                # Parse coverage_score from last line
                match = re.search(
                    r"coverage_score:\s*(\d+)\s*/\s*(\d+)", raw
                )
                if match:
                    covered = int(match.group(1))
                    total = int(match.group(2))
                    coverage_score = covered / total if total > 0 else 0.0
                    meta["coverage_covered"] = covered
                    meta["coverage_total"] = total
                else:
                    # Fallback: count "covered": true occurrences
                    covered = raw.lower().count('"covered": true') + raw.lower().count('"covered":true')
                    total = len(checklists)
                    coverage_score = covered / total if total > 0 else 0.0
                    meta["coverage_covered"] = covered
                    meta["coverage_total"] = total

                meta["coverage_score"] = coverage_score
                meta["coverage_raw"] = raw[:500]
            except Exception as exc:
                LOGGER.warning(
                    "Coverage scoring failed for %s: %s",
                    record.record_id,
                    exc,
                )
                meta["coverage_error"] = str(exc)

        # Phase 2: Quality dimensions
        quality_score = 0.0
        try:
            prompt = _QUALITY_PROMPT.format(
                question=question,
                report=model_answer[:8000],
            )
            raw = self._ask_judge(prompt, temperature=1.0, max_tokens=1024)

            dims = {}
            for dim in ["presentation", "depth", "citation", "consistency"]:
                match = re.search(rf"{dim}:\s*(\d)", raw)
                if match:
                    dims[dim] = int(match.group(1))

            if dims:
                quality_score = sum(dims.values()) / (5 * len(dims))
                meta["quality_dims"] = dims
                meta["quality_score"] = quality_score
            meta["quality_raw"] = raw[:500]
        except Exception as exc:
            LOGGER.warning(
                "Quality scoring failed for %s: %s", record.record_id, exc
            )
            meta["quality_error"] = str(exc)

        # Final score: weighted average of coverage and quality
        if checklists:
            final_score = 0.6 * coverage_score + 0.4 * quality_score
        else:
            final_score = quality_score

        meta["final_score"] = final_score
        is_correct = final_score >= 0.5

        return is_correct, meta


__all__ = ["LiveResearchBenchSFScorer"]
