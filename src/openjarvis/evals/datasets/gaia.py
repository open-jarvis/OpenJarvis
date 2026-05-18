"""GAIA benchmark dataset (gaia-benchmark/GAIA).

Adapted from IPW's gaia.py dataset loader.
"""

from __future__ import annotations

import os
import random
import shutil
from pathlib import Path
from typing import Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.splits import apply_split
from openjarvis.evals.core.types import EvalRecord

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "gaia_benchmark"

_DEFAULT_INPUT_PROMPT = """Please answer the question below. You should:

- Return only your answer, which should be a number, or a short phrase with as few words as possible, or a comma separated list of numbers and/or strings.
- If the answer is a number, return only the number without any units unless specified otherwise.
- If the answer is a string, don't include articles, and don't use abbreviations (e.g. for states).
- If the answer is a comma separated list, apply the above rules to each element in the list.

{file}

Here is the question:

{question}"""


class GAIADataset(DatasetProvider):
    """GAIA agentic benchmark dataset."""

    dataset_id = "gaia"
    dataset_name = "GAIA"

    _hf_path = "gaia-benchmark/GAIA"
    _default_subset = "2023_all"
    _default_split = "validation"

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        from datasets import load_dataset
        from huggingface_hub import snapshot_download

        use_split = (
            self._default_split
            if split in ("train", "test", "all") or split is None
            else split
        )

        # Ensure dataset is downloaded
        dataset_location = self._cache_dir / "GAIA"
        if not dataset_location.exists():
            dataset_location.mkdir(parents=True, exist_ok=True)
            try:
                snapshot_download(
                    repo_id=self._hf_path,
                    repo_type="dataset",
                    local_dir=str(dataset_location),
                )
            except Exception:
                shutil.rmtree(dataset_location, ignore_errors=True)
                raise

        dataset = load_dataset(
            str(dataset_location),
            name=self._default_subset,
            split=use_split,
        )

        rows: Sequence[MutableMapping[str, object]]
        if hasattr(dataset, "to_list"):
            rows = dataset.to_list()
        else:
            rows = list(dataset)

        effective_seed = 42 if seed is None else seed
        if split in ("train", "test", "all"):
            rows = list(rows)
            rows = apply_split(rows, split=split, seed=effective_seed, train_frac=0.2)
        elif seed is not None:
            rng = random.Random(seed)
            rows = list(rows)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        files_location = dataset_location / "2023" / use_split

        self._records = []
        for idx, raw in enumerate(rows):
            record = self._convert_row(raw, files_location, idx)
            if record is not None:
                self._records.append(record)

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def _convert_row(
        self,
        raw: MutableMapping[str, object],
        files_location: Path,
        idx: int,
    ) -> Optional[EvalRecord]:
        task_id = str(raw.get("task_id") or "")
        question = str(raw.get("Question") or "").strip()
        answer = str(raw.get("Final answer") or "").strip()
        level = raw.get("Level")

        if not question or not answer:
            return None

        # Discover associated files
        file_name: Optional[str] = None
        file_path: Optional[Path] = None
        if files_location.exists():
            files = [f for f in os.listdir(files_location) if task_id in f]
            if files:
                file_name = files[0]
                file_path = files_location / file_name

        # Format the prompt
        if file_name and file_path:
            file_info = (
                f"The following file is referenced in the question below and you will "
                f"likely need to use it in order to find the correct answer.\n"
                f"File name: {file_name}\n"
                f"File path: {file_path}\n"
                f"Use the file reading tools to access this file."
            )
        elif file_name:
            file_info = (
                f"The following file is referenced in the question: {file_name}\n"
                f"(Note: File path not available)"
            )
        else:
            file_info = ""

        problem = _DEFAULT_INPUT_PROMPT.format(file=file_info, question=question)

        subject = f"level_{level}" if level else "general"

        metadata = {
            "task_id": task_id,
            "question": question,
            "level": level,
            "file_name": file_name,
            "file_path": str(file_path) if file_path else None,
        }

        return EvalRecord(
            record_id=f"gaia-{task_id or idx}",
            problem=problem,
            reference=answer,
            category="agentic",
            subject=subject,
            metadata=metadata,
        )


__all__ = ["GAIADataset"]
