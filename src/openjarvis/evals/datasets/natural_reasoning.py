"""Natural Reasoning dataset provider (facebook/natural_reasoning).

Adapted from IPW's reasoning benchmark loaders.
"""

from __future__ import annotations

import random
from typing import Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = (
    "Please solve the following reasoning problem. "
    "Think step by step and provide your final answer clearly.\n\n{question}"
)


class NaturalReasoningDataset(DatasetProvider):
    """Natural Reasoning benchmark dataset."""

    dataset_id = "natural-reasoning"
    dataset_name = "Natural Reasoning"

    _hf_path = "facebook/natural_reasoning"
    _default_split = "train"

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

        use_split = split or self._default_split
        dataset = load_dataset(self._hf_path, split=use_split)

        rows: Sequence[MutableMapping[str, object]]
        if hasattr(dataset, "to_list"):
            rows = dataset.to_list()
        else:
            rows = list(dataset)

        if seed is not None:
            rng = random.Random(seed)
            rows = list(rows)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        self._records = []
        for idx, raw in enumerate(rows):
            record = self._convert_row(raw, idx)
            if record is not None:
                self._records.append(record)

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def _convert_row(
        self,
        raw: MutableMapping[str, object],
        idx: int,
    ) -> Optional[EvalRecord]:
        # Extract question text
        question_text = str(raw.get("question") or raw.get("problem") or "").strip()
        if not question_text:
            return None

        # Extract reference answer
        reference = str(raw.get("answer") or raw.get("solution") or "").strip()
        if not reference:
            return None

        # Extract subject/category
        subject = (
            str(
                raw.get("category")
                or raw.get("field")
                or raw.get("source")
                or "General"
            ).strip()
            or "General"
        )

        # Build prompt
        problem = _PROMPT_TEMPLATE.format(question=question_text)

        # Metadata
        metadata: dict[str, object] = {}
        difficulty = raw.get("difficulty") or raw.get("level")
        if difficulty is not None:
            metadata["difficulty"] = difficulty

        return EvalRecord(
            record_id=f"natural-reasoning-{idx}",
            problem=problem,
            reference=reference,
            category="reasoning",
            subject=subject,
            metadata=metadata,
        )


__all__ = ["NaturalReasoningDataset"]
