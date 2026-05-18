"""SWE-bench dataset (princeton-nlp/SWE-bench_Verified).

Agentic coding benchmark — patches for real-world GitHub issues.
"""

from __future__ import annotations

import json
import random
from typing import Any, Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_HF_PATHS = {
    "verified": "princeton-nlp/SWE-bench_Verified",
    "verified_mini": "MariusHobbhahn/swe-bench-verified-mini",
}

_DEFAULT_PROMPT = """You are a software engineer working on the repository **{repo}**.

## Problem Statement

{problem_statement}

{hints_section}

## Instructions

- Analyze the issue described above.
- Produce a patch (unified diff format) that resolves the issue.
- The patch must apply cleanly against commit `{base_commit}`.
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
        # Try JSON first
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(t) for t in parsed]
            return [str(parsed)]
        except (json.JSONDecodeError, TypeError):
            return [value]
    return []


class SWEBenchDataset(DatasetProvider):
    """SWE-bench agentic coding benchmark."""

    dataset_id = "swebench"
    dataset_name = "SWE-bench"

    _default_split = "test"

    def __init__(self, variant: str = "verified_mini") -> None:
        if variant not in _HF_PATHS:
            raise ValueError(
                f"Unknown SWE-bench variant {variant!r}; "
                f"choose from {sorted(_HF_PATHS)}"
            )
        self._variant = variant
        self._hf_path = _HF_PATHS[variant]
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
        patch = str(raw.get("patch") or "").strip()

        if not problem_statement:
            return None

        base_commit = str(raw.get("base_commit") or "")
        hints_text = str(raw.get("hints_text") or "").strip()

        hints_section = ""
        if hints_text:
            hints_section = f"## Hints\n\n{hints_text}"

        problem = _DEFAULT_PROMPT.format(
            repo=repo,
            problem_statement=problem_statement,
            hints_section=hints_section,
            base_commit=base_commit,
        )

        fail_to_pass = _parse_test_list(raw.get("FAIL_TO_PASS"))
        pass_to_pass = _parse_test_list(raw.get("PASS_TO_PASS"))

        metadata: dict[str, Any] = {
            "instance_id": instance_id,
            "problem_statement": problem_statement,
            "repo": repo,
            "base_commit": base_commit,
            "hints_text": hints_text,
            "version": raw.get("version"),
            "test_patch": raw.get("test_patch"),
            "created_at": raw.get("created_at"),
            "environment_setup_commit": raw.get("environment_setup_commit"),
            "difficulty": raw.get("difficulty"),
            "FAIL_TO_PASS": fail_to_pass,
            "PASS_TO_PASS": pass_to_pass,
            "variant": self._variant,
        }

        return EvalRecord(
            record_id=f"swebench-{instance_id or idx}",
            problem=problem,
            reference=patch,
            category="agentic",
            subject=repo,
            metadata=metadata,
        )


__all__ = ["SWEBenchDataset"]
