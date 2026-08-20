"""LiveResearchBench dataset provider — Salesforce's checklist-based benchmark.

Loads Salesforce/LiveResearchBench from HuggingFace. Each task has a research
question and a set of checklist items used for fine-grained, coverage-based
evaluation.

Note: This is the actual LiveResearchBench by Salesforce (arxiv 2510.14240).
The existing ``liveresearch`` module points at DeepResearchBench
(Ayanami0730/deep_research_bench) despite its misleading class name.

Reference: https://github.com/SalesforceAIResearch/LiveResearchBench
Paper:     https://arxiv.org/abs/2510.14240
Dataset:   https://huggingface.co/datasets/Salesforce/LiveResearchBench
"""

from __future__ import annotations

import json
import logging
import random
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.splits import apply_split
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

HF_DATASET_ID = "Salesforce/LiveResearchBench"
DEFAULT_HF_CONFIG = "question_with_checklist"
DEFAULT_HF_SPLIT = "test"


def _parse_checklist(checklist: Any) -> List[str]:
    """Parse the checklist field — may be a JSON string, list, or newline text."""
    if isinstance(checklist, list):
        return [str(item).strip() for item in checklist if str(item).strip()]
    if not isinstance(checklist, str) or not checklist.strip():
        return []
    try:
        parsed = json.loads(checklist)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, str):
            return [parsed.strip()] if parsed.strip() else []
    except json.JSONDecodeError:
        pass
    # Fall back: treat as newline-separated items
    return [line.strip() for line in checklist.splitlines() if line.strip()]


class LiveResearchBenchDataset(DatasetProvider):
    """LiveResearchBench — Salesforce's expert-curated deep research benchmark.

    Loads tasks from HuggingFace with per-task checklists used for
    coverage-based evaluation. Tasks span 7 domains (Science/Tech, Business,
    Health, Law/Governance, Society/Culture, Education, Media).
    """

    dataset_id = "liveresearchbench"
    dataset_name = "LiveResearchBench"

    def __init__(
        self,
        hf_config: Optional[str] = None,
        hf_split: Optional[str] = None,
    ) -> None:
        self._hf_config = hf_config or DEFAULT_HF_CONFIG
        self._hf_split = hf_split or DEFAULT_HF_SPLIT
        self._records: List[EvalRecord] = []

    def verify_requirements(self) -> List[str]:
        issues: List[str] = []
        try:
            import datasets  # noqa: F401
        except ImportError:
            issues.append(
                "The 'datasets' package is required for LiveResearchBench. "
                "Install with: pip install datasets"
            )
        return issues

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        from datasets import load_dataset

        hf_split = (
            self._hf_split
            if split in ("train", "test", "all") or split is None
            else split
        )
        LOGGER.info(
            "Loading %s (config=%s, split=%s) from HuggingFace ...",
            HF_DATASET_ID,
            self._hf_config,
            hf_split,
        )
        ds = load_dataset(HF_DATASET_ID, self._hf_config, split=hf_split)

        # `question_with_checklist` has multiple rows per qid (one per
        # checklist_id). Group by qid and fold all checklist items into a
        # single record per question.
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in ds:
            qid = str(row.get("qid", "") or "").strip()
            if not qid:
                continue
            question = row.get("question") or row.get("question_no_placeholder") or ""
            if qid not in grouped:
                grouped[qid] = {
                    "qid": qid,
                    "question": question,
                    "category": row.get("category", "") or "",
                    "checklist": [],
                }
            cl_items = _parse_checklist(
                row.get("checklist") or row.get("checklist_no_placeholder")
            )
            grouped[qid]["checklist"].extend(cl_items)

        records = list(grouped.values())
        if not records:
            raise RuntimeError(
                f"LiveResearchBench: no records found in {HF_DATASET_ID} "
                f"(config={self._hf_config}, split={hf_split})"
            )

        effective_seed = 42 if seed is None else seed
        if split in ("train", "test", "all"):
            records = apply_split(
                records, split=split, seed=effective_seed, train_frac=0.2
            )
        elif seed is not None:
            random.Random(seed).shuffle(records)
        if max_samples is not None:
            records = records[:max_samples]

        self._records = []
        for rec in records:
            question = (rec.get("question") or "").strip()
            if not question:
                LOGGER.warning("Skipping %s: empty question", rec.get("qid"))
                continue

            research_prompt = (
                "You are a deep research assistant. Conduct thorough research "
                "on the following task and produce a comprehensive, "
                "well-structured, citation-grounded report that addresses "
                "every aspect of the request.\n\n"
                f"## Research Task\n\n{question}"
            )

            self._records.append(
                EvalRecord(
                    record_id=f"liveresearchbench-{rec['qid']}",
                    problem=research_prompt,
                    reference="",  # checklist-based; no single reference answer
                    category="liveresearchbench",
                    subject=rec.get("category") or "",
                    metadata={
                        "qid": rec["qid"],
                        "question": question,
                        "checklist": rec["checklist"],
                        "hf_category": rec.get("category", ""),
                    },
                )
            )

        LOGGER.info(
            "LiveResearchBench: loaded %d tasks (avg %.1f checklist items/task)",
            len(self._records),
            (
                sum(len(r.metadata.get("checklist", [])) for r in self._records)
                / max(1, len(self._records))
            ),
        )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["LiveResearchBenchDataset"]
