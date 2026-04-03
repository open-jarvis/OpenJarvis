"""TerminalBench Native dataset — loads from the terminal-bench pip package (v2 API).

Agentic benchmark using the native terminal-bench SDK for task loading
and test-based evaluation.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

try:
    from terminal_bench.dataset import Dataset as _TBDataset

    _HAS_TERMINALBENCH = True
except ImportError:
    _HAS_TERMINALBENCH = False


def _load_task_yaml(task_dir: Path) -> Dict[str, Any]:
    """Load task.yaml from a task directory."""
    task_file = task_dir / "task.yaml"
    if not task_file.exists():
        return {}
    try:
        import yaml

        return yaml.safe_load(task_file.read_text()) or {}
    except ImportError:
        # Fallback: parse instruction manually
        text = task_file.read_text()
        result: Dict[str, Any] = {}
        # Extract instruction block
        if "instruction:" in text:
            idx = text.index("instruction:")
            after = text[idx + len("instruction:") :]
            # Handle YAML block scalar (|-) or plain string
            after = after.lstrip()
            if after.startswith("|-"):
                after = after[2:].lstrip("\n")
                lines = []
                for line in after.split("\n"):
                    if line and not line.startswith(" ") and not line.startswith("\t"):
                        break
                    lines.append(line)
                result["instruction"] = "\n".join(lines).strip()
            else:
                result["instruction"] = after.split("\n")[0].strip()
        for field in ("category", "difficulty", "author_email"):
            if f"{field}:" in text:
                idx = text.index(f"{field}:")
                val = text[idx + len(field) + 1 :].split("\n")[0].strip()
                result[field] = val
        return result


class TerminalBenchNativeDataset(DatasetProvider):
    """TerminalBench using the native terminal-bench pip package (v2 API)."""

    dataset_id = "terminalbench-native"
    dataset_name = "TerminalBench Native"

    def __init__(
        self,
        name: str = "terminal-bench-core",
        version: str = "0.1.1",
        path: Optional[str] = None,
        task_ids: Optional[List[str]] = None,
        n_tasks: Optional[int] = None,
    ) -> None:
        self._name = name
        self._version = version
        self._path = Path(path) if path else None
        self._task_ids = task_ids
        self._n_tasks = n_tasks
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        if not _HAS_TERMINALBENCH:
            raise ImportError(
                "The 'terminal-bench' package is required for "
                "TerminalBenchNativeDataset. "
                "Install it with: pip install terminal-bench"
            )

        tb_kwargs: Dict[str, Any] = {}
        if self._name is not None:
            tb_kwargs["name"] = self._name
        if self._version is not None:
            tb_kwargs["version"] = self._version
        if self._path is not None:
            tb_kwargs["path"] = self._path
        if self._task_ids is not None:
            tb_kwargs["task_ids"] = self._task_ids
        if self._n_tasks is not None:
            tb_kwargs["n_tasks"] = self._n_tasks

        tb_dataset = _TBDataset(**tb_kwargs)

        # v2 API: tasks is a list of Path objects (task directories)
        task_dirs: List[Path] = list(tb_dataset.tasks)

        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(task_dirs)

        if max_samples is not None:
            task_dirs = task_dirs[:max_samples]

        self._records = []
        for idx, task_dir in enumerate(task_dirs):
            record = self._convert_task(task_dir, idx)
            if record is not None:
                self._records.append(record)

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def _convert_task(
        self,
        task_dir: Path,
        idx: int,
    ) -> Optional[EvalRecord]:
        task_data = _load_task_yaml(task_dir)

        instruction = task_data.get("instruction", "").strip()
        if not instruction:
            return None

        task_id = task_dir.name or f"tbn_{idx}"
        category_val = task_data.get("category", "terminal")

        metadata: Dict[str, Any] = {
            "task_id": task_id,
            "task_dir": str(task_dir),
            "category": category_val,
            "difficulty": task_data.get("difficulty"),
            "tags": task_data.get("tags"),
            "timeout": task_data.get("timeout"),
        }

        return EvalRecord(
            record_id=f"terminalbench-native-{task_id}",
            problem=instruction,
            reference="",
            category="agentic",
            subject=category_val,
            metadata=metadata,
        )

    def create_task_env(self, record):
        """Return a TerminalBenchTaskEnv for the given record."""
        try:
            from openjarvis.evals.execution.terminalbench_env import (
                TerminalBenchTaskEnv,
            )

            return TerminalBenchTaskEnv(record.metadata)
        except ImportError:
            return None

    def verify_requirements(self):
        """Check that terminal-bench and docker are available."""
        issues = []
        if not _HAS_TERMINALBENCH:
            issues.append("terminal-bench package not installed")
        import shutil

        if not shutil.which("docker"):
            issues.append("docker not found in PATH")
        return issues


__all__ = ["TerminalBenchNativeDataset"]
