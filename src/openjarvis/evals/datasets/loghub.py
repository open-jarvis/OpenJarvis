"""LogHub log anomaly detection dataset.

Supports HDFS, BGL, and Thunderbird log datasets from
https://github.com/logpai/loghub for evaluating log analysis agents.
"""

from __future__ import annotations

import csv
import logging
import random
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a log analysis expert. Analyze the following log session "
    "and determine if it indicates an anomaly or is normal behavior.\n\n"
    "Respond with exactly one of: ANOMALY or NORMAL\n"
    "Then provide a brief explanation of your reasoning."
)

_DATASETS = {
    "hdfs": {
        "hf_path": "logpai/loghub-HDFS-v1",
        "log_file": "HDFS.log",
        "label_file": "anomaly_label.csv",
        "mode": "session",  # group by block_id
    },
    "bgl": {
        "hf_path": "logpai/loghub-BGL",
        "log_file": "BGL.log",
        "mode": "window",  # fixed-size windows
        "window_size": 100,
    },
    "thunderbird": {
        "hf_path": "logpai/loghub-Thunderbird",
        "log_file": "Thunderbird.log",
        "mode": "window",
        "window_size": 100,
    },
}


class LogHubDataset(DatasetProvider):
    """LogHub log anomaly detection benchmark."""

    dataset_id = "loghub"
    dataset_name = "LogHub"

    def __init__(
        self,
        subset: str = "hdfs",
        cache_dir: Optional[str] = None,
    ) -> None:
        if subset not in _DATASETS:
            raise ValueError(
                f"Unknown LogHub subset: {subset}. "
                f"Choose from: {list(_DATASETS.keys())}"
            )
        self._subset = subset
        self._cache_dir = (
            Path(cache_dir) if cache_dir else Path.home() / ".cache" / "loghub"
        )
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        meta = _DATASETS[self._subset]
        data_dir = self._cache_dir / self._subset

        if not data_dir.exists():
            self._download(meta, data_dir)

        if meta["mode"] == "session":
            records = self._load_session_mode(data_dir, meta)
        else:
            records = self._load_window_mode(data_dir, meta)

        if seed is not None:
            random.Random(seed).shuffle(records)
        if max_samples is not None:
            records = records[:max_samples]

        self._records = records

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def _download(self, meta: Dict[str, Any], data_dir: Path) -> None:
        """Download dataset from HuggingFace."""
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            raise ImportError(
                "huggingface_hub required for LogHub download. "
                "Install with: pip install huggingface_hub"
            )
        data_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=meta["hf_path"],
            repo_type="dataset",
            local_dir=str(data_dir),
        )

    def _load_session_mode(
        self,
        data_dir: Path,
        meta: Dict[str, Any],
    ) -> List[EvalRecord]:
        """Load HDFS-style session-based records (group by block_id)."""
        log_path = data_dir / meta["log_file"]
        label_path = data_dir / meta["label_file"]

        # Load labels: block_id -> "Anomaly" / "Normal"
        labels: Dict[str, str] = {}
        if label_path.exists():
            with open(label_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    bid = row.get("BlockId", "")
                    lbl = row.get("Label", "Normal")
                    labels[bid] = lbl

        # Group log lines by block_id
        block_pattern = re.compile(r"blk_[-]?\d+")
        sessions: Dict[str, List[str]] = {}

        with open(log_path, errors="replace") as f:
            for line in f:
                match = block_pattern.search(line)
                if match:
                    bid = match.group()
                    sessions.setdefault(bid, []).append(line.rstrip())

        records: List[EvalRecord] = []
        for bid, lines in sessions.items():
            label = labels.get(bid, "Normal")
            reference = "anomaly" if label == "Anomaly" else "normal"
            log_text = "\n".join(lines[:200])  # Cap at 200 lines per session

            problem = (
                f"{_SYSTEM_PROMPT}\n\n"
                f"Log session for block {bid} "
                f"({len(lines)} lines):\n```\n{log_text}\n```"
            )

            records.append(
                EvalRecord(
                    record_id=f"loghub-{self._subset}-{bid}",
                    problem=problem,
                    reference=reference,
                    category="agentic",
                    subject=self._subset,
                    metadata={
                        "block_id": bid,
                        "num_lines": len(lines),
                        "dataset": self._subset,
                        "label": label,
                    },
                )
            )

        return records

    def _load_window_mode(
        self,
        data_dir: Path,
        meta: Dict[str, Any],
    ) -> List[EvalRecord]:
        """Load BGL/Thunderbird-style windowed records."""
        log_path = data_dir / meta["log_file"]
        window_size = meta.get("window_size", 100)

        records: List[EvalRecord] = []
        window: List[str] = []
        has_anomaly = False
        window_idx = 0

        with open(log_path, errors="replace") as f:
            for line in f:
                stripped = line.rstrip()
                # BGL/Thunderbird: first token is "-" (normal) or fault category
                is_anomalous = not stripped.startswith("-")
                if is_anomalous:
                    has_anomaly = True
                window.append(stripped)

                if len(window) >= window_size:
                    reference = "anomaly" if has_anomaly else "normal"
                    log_text = "\n".join(window)

                    problem = (
                        f"{_SYSTEM_PROMPT}\n\n"
                        f"Log window {window_idx} "
                        f"({len(window)} lines):\n```\n{log_text}\n```"
                    )

                    records.append(
                        EvalRecord(
                            record_id=f"loghub-{self._subset}-w{window_idx}",
                            problem=problem,
                            reference=reference,
                            category="agentic",
                            subject=self._subset,
                            metadata={
                                "window_idx": window_idx,
                                "num_lines": len(window),
                                "dataset": self._subset,
                                "has_anomaly": has_anomaly,
                            },
                        )
                    )

                    window = []
                    has_anomaly = False
                    window_idx += 1

        # Flush remaining lines in partial window
        if window:
            reference = "anomaly" if has_anomaly else "normal"
            log_text = "\n".join(window)
            problem = (
                f"{_SYSTEM_PROMPT}\n\n"
                f"Log window {window_idx} "
                f"({len(window)} lines):\n```\n{log_text}\n```"
            )
            records.append(
                EvalRecord(
                    record_id=f"loghub-{self._subset}-w{window_idx}",
                    problem=problem,
                    reference=reference,
                    category="agentic",
                    subject=self._subset,
                    metadata={
                        "window_idx": window_idx,
                        "num_lines": len(window),
                        "dataset": self._subset,
                        "has_anomaly": has_anomaly,
                    },
                )
            )

        return records


__all__ = ["LogHubDataset"]
