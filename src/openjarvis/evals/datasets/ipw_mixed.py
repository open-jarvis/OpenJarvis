"""IPW mixed dataset provider.

Loads evaluation data from a local directory containing HuggingFace Arrow
datasets or JSONL files.  Does *not* download from HuggingFace — the data
must be present on disk (e.g. bundled from the IPW repository).
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_DEFAULT_DATASET_NAME = "mixed_1k_seed1_base"


class IPWDataset(DatasetProvider):
    """IPW mixed evaluation dataset loaded from a local directory."""

    dataset_id = "ipw"
    dataset_name = "IPW"

    def __init__(
        self,
        data_dir: Optional[str] = None,
        dataset_name: Optional[str] = None,
    ) -> None:
        self._data_dir = data_dir
        self._dataset_name = dataset_name or _DEFAULT_DATASET_NAME
        self._records: List[EvalRecord] = []

    # ------------------------------------------------------------------
    # DatasetProvider interface
    # ------------------------------------------------------------------

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        data_path = self._resolve_data_path()

        rows = self._load_rows(data_path)

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

        LOGGER.info(
            "IPW dataset loaded: %d records from %s",
            len(self._records),
            data_path,
        )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_data_path(self) -> Path:
        """Resolve the data directory, raising if it does not exist."""
        if self._data_dir is not None:
            path = Path(self._data_dir)
        else:
            # Try to locate bundled data via importlib.resources
            path = self._find_bundled_data()

        if not path.exists():
            raise FileNotFoundError(
                f"IPW data directory not found: {path}. "
                f"Please provide a valid 'data_dir' pointing to the IPW "
                f"dataset directory (Arrow format or JSONL files)."
            )
        return path

    @staticmethod
    def _find_bundled_data() -> Path:
        """Attempt to locate bundled IPW data via importlib.resources."""
        try:
            import importlib.resources as ir

            ref = ir.files("evals") / "data" / "ipw"
            # Traverse returns a Path for on-disk packages
            data_path = Path(str(ref))
            if data_path.exists():
                return data_path
        except (ImportError, TypeError, ModuleNotFoundError):
            pass

        # Fallback: look relative to this file
        fallback = Path(__file__).resolve().parent.parent / "data" / "ipw"
        return fallback

    def _load_rows(self, data_path: Path) -> Sequence[MutableMapping[str, Any]]:
        """Load rows from an Arrow dataset directory or JSONL files."""
        # Try HuggingFace Arrow dataset first
        dataset_path = data_path / self._dataset_name
        if dataset_path.is_dir():
            return self._load_arrow(dataset_path)

        # Try JSONL file with dataset name
        jsonl_path = data_path / f"{self._dataset_name}.jsonl"
        if jsonl_path.is_file():
            return self._load_jsonl(jsonl_path)

        # Try loading data_path directly as an Arrow dataset
        if (data_path / "dataset_info.json").exists() or (
            data_path / "state.json"
        ).exists():
            return self._load_arrow(data_path)

        # Try any JSONL file in the directory
        jsonl_files = sorted(data_path.glob("*.jsonl"))
        if jsonl_files:
            LOGGER.info("Loading first JSONL file found: %s", jsonl_files[0])
            return self._load_jsonl(jsonl_files[0])

        raise FileNotFoundError(
            f"No Arrow dataset or JSONL files found in {data_path}. "
            f"Expected either a '{self._dataset_name}' subdirectory "
            f"(Arrow format) or '{self._dataset_name}.jsonl'."
        )

    @staticmethod
    def _load_arrow(path: Path) -> Sequence[MutableMapping[str, Any]]:
        """Load a HuggingFace Arrow dataset from disk."""
        from datasets import load_from_disk

        dataset = load_from_disk(str(path))
        if hasattr(dataset, "to_list"):
            return dataset.to_list()
        return list(dataset)

    @staticmethod
    def _load_jsonl(path: Path) -> List[MutableMapping[str, Any]]:
        """Load records from a JSONL file."""
        rows: List[MutableMapping[str, Any]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    @staticmethod
    def _convert_row(
        raw: MutableMapping[str, Any],
        idx: int,
    ) -> Optional[EvalRecord]:
        problem = str(raw.get("problem") or raw.get("prompt") or "").strip()
        answer = str(raw.get("answer") or raw.get("expected_answer") or "").strip()
        subject = str(raw.get("subject") or "general").strip() or "general"

        # Require non-empty problem, answer, and subject
        if not problem or not answer or not subject:
            return None

        # Store the entire raw dict as metadata for downstream analysis
        metadata: Dict[str, Any] = dict(raw)

        return EvalRecord(
            record_id=f"ipw-{idx}",
            problem=problem,
            reference=answer,
            category="chat",
            subject=subject,
            metadata=metadata,
        )


__all__ = ["IPWDataset"]
