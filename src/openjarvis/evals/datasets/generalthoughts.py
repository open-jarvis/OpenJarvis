"""GeneralThought-430K (filtered) — external reasoning corpus.

NOT USED FOR EVALUATION. Provides the LLM-guided spec search proposer
with a large pool of reasoning trajectories to reason over (via
`openjarvis.learning.spec_search.external_adapter`) when the diagnose
phase wants signal from a broad reasoning corpus rather than the
per-cell student's own trace history.

HF dataset: natolambert/GeneralThought-430K-filtered (filtered variant of
GeneralReasoning/GeneralThought-430K — community/verifier-score filtered).
"""

from __future__ import annotations

import random
from typing import Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.splits import apply_split
from openjarvis.evals.core.types import EvalRecord

HF_DATASET_ID = "natolambert/GeneralThought-430K-filtered"
HF_SPLIT = "train"
# Schema (observed from load_dataset_builder + sample row):
#   question_id, question_url, question, reference_answer, prev_messages,
#   model_name, model_answer, model_reasoning, task, question_license,
#   question_source, community_answer_score, community_question_score,
#   verifier_score
PROBLEM_COLS = ("question",)
SOLUTION_COLS = ("model_answer", "reference_answer")


def _first_present(
    row: MutableMapping[str, object], keys: Sequence[str]
) -> Optional[str]:
    for k in keys:
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


class GeneralThoughtsDataset(DatasetProvider):
    """GeneralThought-430K (filtered) external reasoning corpus for LLM-guided spec search."""

    dataset_id = "generalthoughts"
    dataset_name = "GeneralThought-430K-filtered (natolambert)"

    def __init__(self) -> None:
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        from datasets import load_dataset

        ds = load_dataset(HF_DATASET_ID, split=HF_SPLIT)
        rows: List[MutableMapping[str, object]]
        if hasattr(ds, "to_list"):
            rows = ds.to_list()
        else:
            rows = list(ds)

        effective_seed = 42 if seed is None else seed
        if split in ("train", "test", "all"):
            rows = apply_split(
                rows,
                split=split,
                seed=effective_seed,
                train_frac=0.2,
            )
        elif seed is not None:
            rng = random.Random(seed)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        records: List[EvalRecord] = []
        for i, r in enumerate(rows):
            problem = _first_present(r, PROBLEM_COLS)
            if not problem:
                continue
            reference = _first_present(r, SOLUTION_COLS) or ""
            question_id = r.get("question_id")
            record_id = (
                str(question_id) if question_id is not None else f"generalthoughts-{i}"
            )
            # Gather lightweight metadata — skip large text fields to keep records lean
            metadata: dict[str, object] = {"source": "generalthoughts"}
            for key in ("task", "question_source", "model_name", "question_license"):
                val = r.get(key)
                if val is not None:
                    metadata[key] = val
            records.append(
                EvalRecord(
                    record_id=record_id,
                    problem=problem,
                    reference=reference,
                    category="reasoning",
                    subject=str(r.get("task") or "General"),
                    metadata=metadata,
                )
            )
        self._records = records

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["GeneralThoughtsDataset"]
