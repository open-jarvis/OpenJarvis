"""GPQA dataset provider (Idavidrein/gpqa).

Adapted from IPW's gpqa.py dataset loader.
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


class GPQADataset(DatasetProvider):
    """GPQA (Graduate-Level Google-Proof Q&A) multiple-choice benchmark."""

    dataset_id = "gpqa"
    dataset_name = "GPQA"

    _hf_path = "Idavidrein/gpqa"
    _default_subset = "gpqa_diamond"
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
        dataset = load_dataset(self._hf_path, self._default_subset, split=use_split)

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
        # Field names vary across dataset versions.
        question = str(
            raw.get("Question") or raw.get("question") or "",
        ).strip()

        correct_answer = str(
            raw.get("Correct Answer") or raw.get("correct_answer") or "",
        ).strip()

        # Gather distractor answers.
        distractors: List[str] = []
        for key in (
            "Incorrect Answer 1",
            "incorrect_answer_1",
            "Incorrect Answer 2",
            "incorrect_answer_2",
            "Incorrect Answer 3",
            "incorrect_answer_3",
        ):
            val = raw.get(key)
            if val is not None:
                text = str(val).strip()
                if text:
                    distractors.append(text)

        if not question or not correct_answer or not distractors:
            return None

        # Correct answer is always option A; distractors fill B/C/D.
        options = [correct_answer] + distractors[:3]

        subdomain = str(
            raw.get("Subdomain") or raw.get("subdomain") or "",
        ).strip()
        domain = str(
            raw.get("High-level domain") or raw.get("domain") or "",
        ).strip()
        subject = subdomain or domain or "general"

        prompt_parts = [
            question,
            "",
            "Options:",
            _format_options(options),
            "",
            "Provide only the letter of the correct answer (A, B, C, or D).",
        ]
        problem = "\n".join(part for part in prompt_parts if part).strip()

        metadata = {
            "correct_option": "A",
            "answer_text": correct_answer,
            "options": options,
            "subdomain": subdomain,
            "domain": domain,
        }

        return EvalRecord(
            record_id=f"gpqa-{idx}",
            problem=problem,
            reference="A",
            category="reasoning",
            subject=subject,
            metadata=metadata,
        )


__all__ = ["GPQADataset"]
