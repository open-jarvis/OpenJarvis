"""SuperGPQA dataset provider (m-a-p/SuperGPQA).

Adapted from IPW's supergpqa.py dataset loader.
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


class SuperGPQADataset(DatasetProvider):
    """SuperGPQA multiple-choice benchmark dataset."""

    dataset_id = "supergpqa"
    dataset_name = "SuperGPQA"

    _hf_path = "m-a-p/SuperGPQA"
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
        question = str(raw.get("question") or "").strip()
        options_raw = raw.get("options") or []
        options = [str(o).strip() for o in options_raw if str(o).strip()]
        answer_letter = str(raw.get("answer_letter") or "").strip().upper()
        answer_text = str(raw.get("answer") or "").strip()

        subject = (
            str(
                raw.get("subfield")
                or raw.get("field")
                or raw.get("discipline")
                or "general"
            ).strip()
            or "general"
        )

        if not question or not options or not answer_letter:
            return None

        prompt_parts = [
            question,
            "",
            "Options:",
            _format_options(options),
            "",
            "Respond with the correct letter only.",
        ]
        problem = "\n".join(part for part in prompt_parts if part).strip()

        metadata = {
            "uuid": raw.get("uuid"),
            "discipline": raw.get("discipline"),
            "field": raw.get("field"),
            "subfield": raw.get("subfield"),
            "difficulty": raw.get("difficulty"),
            "is_calculation": raw.get("is_calculation"),
            "answer_text": answer_text,
            "options": options,
        }

        return EvalRecord(
            record_id=f"supergpqa-{idx}",
            problem=problem,
            reference=answer_letter,
            category="reasoning",
            subject=subject,
            metadata=metadata,
        )


__all__ = ["SuperGPQADataset"]
