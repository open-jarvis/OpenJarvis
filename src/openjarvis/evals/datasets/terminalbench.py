"""TerminalBench dataset (terminal-bench/terminal-bench).

Agentic benchmark for terminal / command-line tasks.
"""

from __future__ import annotations

import random
from typing import Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

try:
    from datasets import load_dataset as _load_dataset  # noqa: F401

    _HAS_DATASETS = True
except ImportError:
    _HAS_DATASETS = False

_HF_PATH = "terminal-bench/terminal-bench"


class TerminalBenchDataset(DatasetProvider):
    """TerminalBench agentic terminal benchmark (HuggingFace variant)."""

    dataset_id = "terminalbench"
    dataset_name = "TerminalBench"

    _hf_path = _HF_PATH
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
        if not _HAS_DATASETS:
            raise ImportError(
                "The 'datasets' package is required for TerminalBenchDataset. "
                "Install it with: pip install datasets"
            )
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
        # Try multiple field name variants for question
        question = str(
            raw.get("prompt") or raw.get("question") or raw.get("instruction") or ""
        ).strip()

        # Try multiple field name variants for answer
        answer = str(
            raw.get("answer")
            or raw.get("expected_output")
            or raw.get("gold_answer")
            or ""
        ).strip()

        if not question:
            return None

        # Category / type
        category_raw = raw.get("category", raw.get("type", "terminal"))
        category_str = str(category_raw) if category_raw else "terminal"

        # Task identifier
        task_id_raw = raw.get("id", raw.get("task_id"))
        task_id = str(task_id_raw) if task_id_raw else f"tb_{idx}"

        metadata = {
            "task_id": task_id,
            "original_category": category_str,
        }

        return EvalRecord(
            record_id=f"terminalbench-{task_id}",
            problem=question,
            reference=answer,
            category="agentic",
            subject=category_str,
            metadata=metadata,
        )


__all__ = ["TerminalBenchDataset"]
