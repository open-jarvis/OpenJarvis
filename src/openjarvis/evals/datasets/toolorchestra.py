"""ToolScale (nvidia) — external tool-use corpus.

NOT USED FOR EVALUATION. Surfaces tool-use trajectories from
``nvidia/ToolScale`` (the dataset underlying the ToolOrchestra paper) to
the LLM-guided spec search proposer via
``openjarvis.learning.spec_search.external_adapter`` so the diagnose
phase can reason over a broad pool of tool-use traces.

The ``dataset_id`` is kept as ``"toolorchestra"`` (matching the published
paper name) even though the HuggingFace dataset is published as
``nvidia/ToolScale``.

HF dataset: nvidia/ToolScale — single ``train`` split.
Schema:
  - ``id``: record identifier (string)
  - ``description``: task/policy metadata dict (or string repr)
  - ``user_scenario``: dict with ``persona`` and ``instructions``
    - ``instructions.task_instructions``: the user's tool-use request (problem)
    - ``instructions.reason_for_call``:   optional context / motivation
  - ``initial_state``: environment state at task start (may be None/empty)
  - ``evaluation_criteria``: dict with ``actions`` list — the expected
    sequence of tool calls (used as reference)

Conversion to EvalRecord:
  - ``problem``  : ``user_scenario.instructions.task_instructions``
  - ``reference``: string representation of ``evaluation_criteria.actions``,
                   truncated to 2000 chars
"""

from __future__ import annotations

import ast
import random
from typing import Any, Iterable, List, MutableMapping, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.splits import apply_split
from openjarvis.evals.core.types import EvalRecord

HF_DATASET_ID = "nvidia/ToolScale"
HF_SPLIT = "train"


def _parse_field(raw: object) -> Any:
    """Parse a field that may be a dict, a string repr of a dict, or None."""
    if raw is None or (isinstance(raw, str) and raw.strip().lower() in ("none", "")):
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            pass
    return raw


def _extract_problem_reference(
    row: MutableMapping[str, object],
) -> tuple[Optional[str], str]:
    """Return (problem, reference) from a ToolScale row.

    problem   = user_scenario.instructions.task_instructions
    reference = str(evaluation_criteria.actions) truncated to 2000 chars
    """
    problem: Optional[str] = None
    user_scenario = _parse_field(row.get("user_scenario"))
    if isinstance(user_scenario, dict):
        instructions = user_scenario.get("instructions")
        if isinstance(instructions, dict):
            task_inst = instructions.get("task_instructions")
            if isinstance(task_inst, str) and task_inst.strip():
                problem = task_inst.strip()
        # Fallback: top-level string in user_scenario
        if not problem:
            for key in ("task_instructions", "task", "query", "request"):
                v = user_scenario.get(key)
                if isinstance(v, str) and v.strip():
                    problem = v.strip()
                    break

    reference = ""
    eval_criteria = _parse_field(row.get("evaluation_criteria"))
    if isinstance(eval_criteria, dict):
        actions = eval_criteria.get("actions")
        if actions is not None:
            reference = str(actions)[:2000]
    if not reference and eval_criteria is not None:
        reference = str(eval_criteria)[:2000]

    return problem, reference


class ToolOrchestraDataset(DatasetProvider):
    """ToolScale (nvidia/ToolScale) external corpus for LLM-guided spec search.

    Published as part of the ToolOrchestra paper. ``dataset_id`` is kept
    as ``"toolorchestra"`` (the paper's name).
    """

    dataset_id = "toolorchestra"
    dataset_name = "ToolScale (nvidia) — ToolOrchestra paper"

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

        ds = load_dataset(HF_DATASET_ID, split=HF_SPLIT)
        rows: List[MutableMapping[str, object]]
        if hasattr(ds, "to_list"):
            rows = ds.to_list()
        else:
            rows = list(ds)

        effective_seed = 42 if seed is None else seed
        if split in ("train", "test", "all"):
            rows = apply_split(
                rows,
                split=split,
                seed=effective_seed,
                train_frac=0.2,
            )
        elif seed is not None:
            rng = random.Random(seed)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        records: List[EvalRecord] = []
        for i, r in enumerate(rows):
            problem, reference = _extract_problem_reference(r)
            if not problem:
                continue
            row_id = r.get("id")
            record_id = str(row_id) if row_id is not None else f"toolorchestra-{i}"
            metadata: dict[str, object] = {"source": "toolorchestra"}
            desc = _parse_field(r.get("description"))
            if isinstance(desc, dict):
                for key in ("purpose", "notes"):
                    val = desc.get(key)
                    if val is not None:
                        metadata[key] = val
            records.append(
                EvalRecord(
                    record_id=record_id,
                    problem=problem,
                    reference=reference,
                    category="",
                    subject="",
                    metadata=metadata,
                )
            )
        self._records = records

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["ToolOrchestraDataset"]
