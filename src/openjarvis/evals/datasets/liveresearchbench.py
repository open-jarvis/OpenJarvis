"""LiveResearchBench (Salesforce) dataset provider.

80 expert-curated deep research tasks with per-question evaluation
checklists across three domains: daily life, enterprise, and academia.
543 checklist items total (grouped by question).

Reference: https://github.com/SalesforceAIResearch/LiveResearchBench
HuggingFace: Salesforce/LiveResearchBench (gated — accept terms first)
"""

from __future__ import annotations

import logging
import random
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_HF_DATASET = "Salesforce/LiveResearchBench"


def _replace_date_placeholders(text: str) -> str:
    """Replace dynamic date placeholders in queries."""
    now = datetime.now()
    text = text.replace("{{current_year}}", str(now.year))
    text = text.replace("{{last_year}}", str(now.year - 1))
    text = text.replace("{{current_date}}", now.strftime("%Y-%m-%d"))
    text = text.replace("{{date}}", now.strftime("%Y-%m-%d"))
    text = re.sub(r"\{current_year\}", str(now.year), text)
    text = re.sub(r"\{last_year\}", str(now.year - 1), text)
    return text


class LiveResearchBenchSFDataset(DatasetProvider):
    """Salesforce LiveResearchBench — 80 expert-curated research tasks.

    The HuggingFace dataset has 543 rows (multiple checklist items per
    question). We group by ``qid`` to produce one EvalRecord per unique
    question, with all checklist items aggregated in metadata.
    """

    dataset_id = "liveresearchbench"
    dataset_name = "LiveResearchBench (Salesforce)"

    def __init__(self) -> None:
        self._records: Optional[List[EvalRecord]] = None

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        try:
            from datasets import load_dataset
        except ImportError:
            raise ImportError(
                "datasets package required. Install with: pip install datasets"
            )

        import os

        hf_token = os.environ.get("HF_TOKEN") or os.environ.get(
            "HUGGING_FACE_HUB_TOKEN"
        )

        # Try question_with_checklist first (has evaluation criteria)
        hf_config = split or "question_with_checklist"
        LOGGER.info(
            "Loading LiveResearchBench from HuggingFace (%s, config=%s)",
            _HF_DATASET,
            hf_config,
        )

        try:
            ds = load_dataset(
                _HF_DATASET, hf_config, split="test", token=hf_token
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load {_HF_DATASET}. This is a gated dataset — "
                "visit https://huggingface.co/datasets/Salesforce/LiveResearchBench "
                "to accept the terms, then set HF_TOKEN in your environment. "
                f"Error: {exc}"
            ) from exc

        # Group rows by qid (multiple checklist items per question)
        questions: Dict[str, Dict[str, Any]] = {}
        checklists_by_qid: Dict[str, List[str]] = defaultdict(list)

        for row in ds:
            qid = str(row.get("qid", ""))
            if not qid:
                continue

            if qid not in questions:
                question = row.get("question", "") or row.get(
                    "question_no_placeholder", ""
                )
                questions[qid] = {
                    "question": question,
                    "category": row.get("category", ""),
                }

            checklist = row.get("checklist", "") or row.get(
                "checklist_no_placeholder", ""
            )
            if checklist:
                checklists_by_qid[qid].append(checklist)

        # Build EvalRecords
        records: List[EvalRecord] = []
        for qid, info in questions.items():
            question = info["question"]
            if not question:
                continue

            question = _replace_date_placeholders(question)

            problem = (
                "You are a research assistant. Please conduct thorough "
                "research on the following question and write a "
                "comprehensive report with citations.\n\n"
                f"{question}"
            )

            metadata: Dict[str, Any] = {
                "qid": qid,
                "original_question": question,
                "category": info.get("category", ""),
                "checklists": checklists_by_qid.get(qid, []),
            }

            records.append(
                EvalRecord(
                    record_id=f"lrb-{qid}",
                    problem=problem,
                    reference="",
                    category="liveresearchbench",
                    metadata=metadata,
                )
            )

        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(records)

        if max_samples is not None:
            records = records[:max_samples]

        self._records = records
        total_checklists = sum(
            len(r.metadata.get("checklists", [])) for r in records
        )
        LOGGER.info(
            "LiveResearchBench: loaded %d tasks (%d checklist items)",
            len(self._records),
            total_checklists,
        )

    def iter_records(self) -> Iterable[EvalRecord]:
        if self._records is None:
            raise RuntimeError("Call .load() before iterating")
        return iter(self._records)

    def size(self) -> int:
        if self._records is None:
            raise RuntimeError("Call .load() before size()")
        return len(self._records)


__all__ = ["LiveResearchBenchSFDataset"]
