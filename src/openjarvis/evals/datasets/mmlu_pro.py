"""MMLU-Pro dataset provider (TIGER-Lab/MMLU-Pro).

Adapted from IPW's mmlu_pro.py dataset loader.
"""

from __future__ import annotations

import random
from typing import Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord


def _format_options(options: Iterable[str]) -> str:
    rendered = []
    for idx, option in enumerate(options):
        letter = chr(ord("A") + idx)
        rendered.append(f"{letter}. {option}")
    return "\n".join(rendered)


class MMLUProDataset(DatasetProvider):
    """MMLU-Pro multiple-choice benchmark dataset."""

    dataset_id = "mmlu-pro"
    dataset_name = "MMLU-Pro"

    _hf_path = "TIGER-Lab/MMLU-Pro"
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
        question = str(raw.get("question") or "").strip()
        options_raw = raw.get("options") or []
        options = [str(o).strip() for o in options_raw if str(o).strip()]
        answer_letter = str(raw.get("answer") or "").strip().upper()

        subject = str(raw.get("category") or "general").strip() or "general"

        if not question or not options or not answer_letter:
            return None

        prompt_parts = [
            question,
            "",
            "Options:",
            _format_options(options),
            "",
            "Respond with the correct letter.",
        ]
        problem = "\n".join(part for part in prompt_parts if part).strip()

        metadata = {
            "question_id": raw.get("question_id"),
            "answer_index": raw.get("answer_index"),
            "src": raw.get("src"),
            "options": options,
        }

        return EvalRecord(
            record_id=f"mmlu-pro-{idx}",
            problem=problem,
            reference=answer_letter,
            category="reasoning",
            subject=subject,
            metadata=metadata,
        )


__all__ = ["MMLUProDataset"]
