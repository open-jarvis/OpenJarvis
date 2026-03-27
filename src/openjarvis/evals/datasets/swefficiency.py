"""SWEfficiency dataset (swefficiency/swefficiency).

Agentic benchmark for software performance optimization.
"""

from __future__ import annotations

import json
import random
from typing import Any, Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_HF_PATH = "swefficiency/swefficiency"

_DEFAULT_PROMPT = """You are a software performance engineer working on the repository **{repo}**.

## Problem Statement

{problem_statement}

## Workload

{workload}

## Expected Speedup

Target speedup: **{expected_speedup}x**

## Instructions

- Analyze the performance bottleneck described above.
- Produce an optimized patch (unified diff format) that achieves at least the target speedup.
- The patch must apply cleanly against commit `{base_commit}`.
- Focus on algorithmic improvements, data structure changes, or computation optimizations.
- Return ONLY the patch — no explanation, no markdown fences."""


def _parse_test_list(value: object) -> List[str]:
    """Parse a test list that may be JSON string, plain list, or single string."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(t) for t in value]
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(t) for t in parsed]
            return [str(parsed)]
        except (json.JSONDecodeError, TypeError):
            return [value]
    return []


class SWEfficiencyDataset(DatasetProvider):
    """SWEfficiency agentic performance optimization benchmark."""

    dataset_id = "swefficiency"
    dataset_name = "SWEfficiency"

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
        instance_id = str(raw.get("instance_id") or "")
        repo = str(raw.get("repo") or "")
        problem_statement = str(raw.get("problem_statement") or "").strip()
        workload = str(raw.get("workload") or "").strip()
        patch = str(raw.get("patch") or "").strip()

        if not problem_statement:
            return None

        # Try both field name variants for speedup
        speedup_raw = raw.get("speedup", raw.get("expected_speedup"))
        try:
            expected_speedup = float(speedup_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            expected_speedup = 1.0

        base_commit = str(raw.get("base_commit") or "")

        problem = _DEFAULT_PROMPT.format(
            repo=repo,
            problem_statement=problem_statement,
            workload=workload or "(not specified)",
            expected_speedup=expected_speedup,
            base_commit=base_commit,
        )

        # Parse test lists (try multiple field name variants)
        covering_tests = _parse_test_list(
            raw.get("covering_tests", raw.get("COVERING_TESTS"))
        )
        pass_to_pass = _parse_test_list(
            raw.get("pass_to_pass", raw.get("PASS_TO_PASS"))
        )

        metadata: dict[str, Any] = {
            "instance_id": instance_id,
            "repo": repo,
            "base_commit": base_commit,
            "expected_speedup": expected_speedup,
            "workload": workload,
            "test_patch": raw.get("test_patch"),
            "test_cmd": raw.get("test_cmd"),
            "rebuild_cmd": raw.get("rebuild_cmd"),
            "image_name": raw.get("image_name"),
            "covering_tests": covering_tests,
            "pass_to_pass": pass_to_pass,
        }

        return EvalRecord(
            record_id=f"swefficiency-{instance_id or idx}",
            problem=problem,
            reference=patch,
            category="agentic",
            subject=repo,
            metadata=metadata,
        )


__all__ = ["SWEfficiencyDataset"]
