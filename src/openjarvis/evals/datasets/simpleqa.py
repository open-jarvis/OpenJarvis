"""SimpleQA dataset provider (basicv8vc/SimpleQA).

Short-answer factual QA benchmark for evaluating factual accuracy.
"""

from __future__ import annotations

import ast
import random
from typing import Any, Dict, Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """Please answer the following question with a short, factual response.
Your answer should be a word, phrase, name, number, or date.
Do not include explanations or additional context.

Question: {question}"""


class SimpleQADataset(DatasetProvider):
    """SimpleQA short-answer factual QA benchmark."""

    dataset_id = "simpleqa"
    dataset_name = "SimpleQA"

    _hf_path = "basicv8vc/SimpleQA"
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
        question = str(raw.get("problem") or raw.get("question") or "").strip()
        answer = str(raw.get("answer") or raw.get("gold_answer") or "").strip()

        if not question or not answer:
            return None

        # Parse metadata — may be a JSON string or a dict
        meta_raw = raw.get("metadata")
        parsed_meta = _parse_metadata(meta_raw)

        # Extract topic for subject field
        subject = str(parsed_meta.get("topic", "")).strip() or "general"

        problem = _PROMPT_TEMPLATE.format(question=question)

        metadata: Dict[str, Any] = {
            "answer_type": parsed_meta.get("answer_type", ""),
        }
        # Preserve all parsed metadata keys
        for key, value in parsed_meta.items():
            if key not in metadata:
                metadata[key] = value

        return EvalRecord(
            record_id=f"simpleqa-{idx}",
            problem=problem,
            reference=answer,
            category="chat",
            subject=subject,
            metadata=metadata,
        )


def _parse_metadata(meta_raw: object) -> Dict[str, Any]:
    """Parse metadata which may be a dict, a JSON-like string, or None."""
    if meta_raw is None:
        return {}
    if isinstance(meta_raw, dict):
        return dict(meta_raw)
    if isinstance(meta_raw, str):
        text = meta_raw.strip()
        if not text:
            return {}
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError):
            pass
    return {}


__all__ = ["SimpleQADataset"]
