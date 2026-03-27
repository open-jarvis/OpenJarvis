"""HLE dataset provider (cais/hle).

Adapted from IPW's reasoning benchmark loaders.
"""

from __future__ import annotations

import random
from typing import Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

# Fields whose presence signals a multimodal row.
_MULTIMODAL_FIELDS = frozenset(
    {"image", "image_path", "images", "audio", "audio_path", "audios"}
)


class HLEDataset(DatasetProvider):
    """HLE (Humanity's Last Exam) benchmark dataset."""

    dataset_id = "hle"
    dataset_name = "HLE"

    _hf_path = "cais/hle"
    _default_split = "test"

    def __init__(self, *, text_only: bool = True) -> None:
        self._text_only = text_only
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

        self._records = []
        for idx, raw in enumerate(rows):
            record = self._convert_row(raw, idx)
            if record is not None:
                self._records.append(record)
                if max_samples is not None and len(self._records) >= max_samples:
                    break

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def _is_multimodal(self, raw: MutableMapping[str, object]) -> bool:
        """Return True if the row contains multimodal content."""
        for field in _MULTIMODAL_FIELDS:
            value = raw.get(field)
            if value is not None and value != "" and value != []:
                return True
        return False

    def _convert_row(
        self,
        raw: MutableMapping[str, object],
        idx: int,
    ) -> Optional[EvalRecord]:
        # Skip multimodal rows when text_only is enabled
        if self._text_only and self._is_multimodal(raw):
            return None

        # Extract question text
        question_text = str(
            raw.get("question") or raw.get("instruction") or raw.get("prompt") or ""
        ).strip()
        if not question_text:
            return None

        # Extract reference answer
        reference = str(
            raw.get("answer") or raw.get("gold_answer") or raw.get("response") or ""
        ).strip()
        if not reference:
            return None

        # Extract category
        category_value = (
            str(
                raw.get("category")
                or raw.get("subject")
                or raw.get("type")
                or "general"
            ).strip()
            or "general"
        )

        # Extract task_id for the record_id
        task_id = str(raw.get("id") or raw.get("task_id") or f"hle_{idx}").strip()

        # Use question directly (no wrapper template)
        problem = question_text

        # Metadata
        metadata: dict[str, object] = {}
        difficulty = raw.get("difficulty") or raw.get("level")
        if difficulty is not None:
            metadata["difficulty"] = difficulty
        metadata["task_id"] = task_id

        return EvalRecord(
            record_id=f"hle-{idx}",
            problem=problem,
            reference=reference,
            category="reasoning",
            subject=category_value,
            metadata=metadata,
        )


__all__ = ["HLEDataset"]
