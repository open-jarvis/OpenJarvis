"""MATH-500 dataset provider (HuggingFaceH4/MATH-500).

Adapted from IPW's reasoning benchmark loaders.
"""

from __future__ import annotations

import random
from typing import Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = (
    "Solve the following math problem step by step. "
    "Provide your final answer clearly.\n\n{problem}"
)


class MATH500Dataset(DatasetProvider):
    """MATH-500 reasoning benchmark dataset."""

    dataset_id = "math500"
    dataset_name = "MATH-500"

    _hf_path = "HuggingFaceH4/MATH-500"
    _default_split = "test"

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
        # Extract problem text
        problem_text = str(raw.get("problem") or raw.get("question") or "").strip()
        if not problem_text:
            return None

        # Extract reference answer
        reference = str(raw.get("answer") or raw.get("solution") or "").strip()
        if not reference:
            return None

        # Extract subject
        subject = (
            str(raw.get("subject") or raw.get("type") or "Mathematics").strip()
            or "Mathematics"
        )

        # Build prompt
        problem = _PROMPT_TEMPLATE.format(problem=problem_text)

        # Metadata
        metadata: dict[str, object] = {}
        level = raw.get("level")
        if level is not None:
            metadata["level"] = level

        return EvalRecord(
            record_id=f"math500-{idx}",
            problem=problem,
            reference=reference,
            category="reasoning",
            subject=subject,
            metadata=metadata,
        )


__all__ = ["MATH500Dataset"]
