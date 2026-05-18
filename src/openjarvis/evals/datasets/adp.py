"""Agent Data Collection (neulab) — external agent-trajectory corpus.

NOT USED FOR EVALUATION. Surfaces multi-turn agent trajectories to the
LLM-guided spec search proposer via
``openjarvis.learning.spec_search.external_adapter`` so the diagnose
phase can reason over a broad pool of agent traces without depending on
the per-cell student's own trace history.

HF dataset: neulab/agent-data-collection — a multi-config collection of
agent trajectory datasets (AgentTuning subsets, CodeAct, OpenHands, etc.).
Each config shares the same ``std`` split schema:
  - ``id``: trajectory identifier
  - ``content``: list-of-dicts with keys ``class_``, ``source``, ``content``
  - ``details``: per-config metadata dict

Conversion to EvalRecord:
  - ``problem``  : content of the first turn whose ``source == "user"``
  - ``reference``: content of the last turn whose ``class_ == "message_action"``
    (the agent's final response/action), truncated to 2000 chars
"""

from __future__ import annotations

import ast
import random
from typing import Iterable, List, MutableMapping, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.splits import apply_split
from openjarvis.evals.core.types import EvalRecord

HF_DATASET_ID = "neulab/agent-data-collection"
# Use 'std' split — the normalised, model-agnostic format present in every config.
HF_SPLIT = "std"

# All sub-configs available in the dataset. We concatenate them so the
# corpus is as diverse as possible for the proposer's diagnose phase.
_CONFIGS = [
    "agenttuning_alfworld",
    "agenttuning_db",
    "agenttuning_kg",
    "agenttuning_mind2web",
    "agenttuning_os",
    "agenttuning_webshop",
    "code_feedback",
    "codeactinstruct",
    "go-browse-wa",
    "mind2web",
    "nebius_SWE-agent-trajectories",
    "nnetnav-live",
    "nnetnav-wa",
    "openhands",
    "orca_agentinstruct",
    "swe-gym_openhands_sampled_trajectories",
    "swe-smith",
    "synatra",
]


def _parse_content(raw: object) -> List[MutableMapping[str, object]]:
    """Parse the ``content`` field, which may be a list or a string repr of one."""
    if isinstance(raw, list):
        return raw  # type: ignore[return-value]
    if isinstance(raw, str):
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return parsed  # type: ignore[return-value]
        except (ValueError, SyntaxError):
            pass
    return []


def _extract_problem_reference(
    turns: List[MutableMapping[str, object]],
) -> tuple[Optional[str], str]:
    """Return (problem, reference) from a list of trajectory turns.

    problem   = content of the first user-sourced turn
    reference = content of the last message_action turn (agent's final output),
                truncated to 2000 chars; falls back to the last non-user turn
    """
    problem: Optional[str] = None
    for turn in turns:
        if turn.get("source") == "user":
            text = str(turn.get("content") or "").strip()
            if text:
                problem = text
                break

    reference = ""
    # Prefer the last message_action (the agent's final response/finish action)
    for turn in reversed(turns):
        if turn.get("class_") == "message_action":
            text = str(turn.get("content") or "").strip()
            if text:
                reference = text[:2000]
                break
    if not reference:
        # Fallback: last non-user turn of any class
        for turn in reversed(turns):
            if turn.get("source") != "user":
                text = str(turn.get("content") or "").strip()
                if text:
                    reference = text[:2000]
                    break

    return problem, reference


class ADPDataset(DatasetProvider):
    """Agent Data Collection (neulab) external corpus for LLM-guided spec search."""

    dataset_id = "adp"
    dataset_name = "Agent Data Collection (neulab)"

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

        # We use streaming to avoid pulling entire datasets into Arrow memory
        # for each config — the GC of large Arrow tables causes intermittent
        # segfaults in this environment.
        #
        # Row collection cap:
        #  - When only max_samples is given (no split, no explicit seed) we stop
        #    after collecting max_samples rows from the configs.
        #  - When a split or shuffle is requested we need enough rows to make
        #    apply_split meaningful: collect at most max(max_samples * 50, 2000)
        #    rows so that even the test-split has sufficient samples, but we
        #    don't load the entire corpus.
        if split in ("train", "test", "all") or seed is not None:
            row_cap = max(max_samples * 50, 2000) if max_samples is not None else 5000
        else:
            row_cap = max_samples

        rows: List[MutableMapping[str, object]] = []
        for cfg in _CONFIGS:
            if row_cap is not None and len(rows) >= row_cap:
                break
            try:
                ds_stream = load_dataset(
                    HF_DATASET_ID, cfg, split=HF_SPLIT, streaming=True
                )
                for row in ds_stream:
                    rows.append(dict(row))  # type: ignore[arg-type]
                    if row_cap is not None and len(rows) >= row_cap:
                        break
            except Exception:
                # Skip configs that fail to load (gated, missing, etc.)
                continue

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
            turns = _parse_content(r.get("content"))
            problem, reference = _extract_problem_reference(turns)
            if not problem:
                continue
            row_id = r.get("id")
            record_id = str(row_id) if row_id is not None else f"adp-{i}"
            metadata: dict[str, object] = {"source": "adp"}
            details = r.get("details")
            if isinstance(details, dict):
                metadata["details"] = details
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


__all__ = ["ADPDataset"]
