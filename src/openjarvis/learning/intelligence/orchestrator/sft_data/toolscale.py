"""Loader for NVIDIA ToolScale (``nvidia/ToolScale``) — the ToolOrchestra
RL/SFT task source (arXiv:2511.21689 §3.3).

Each row is a synthetic user-agent-tool task: an instruction ``I``, golden
function calls ``A`` (the ground-truth tool sequence), and short info ``o`` that
must be communicated. We normalize the raw HF row into :class:`ToolScaleTask`.

``load_toolscale`` streams via the HuggingFace ``datasets`` library; tests pass
``source=`` an iterable of raw row dicts so normalization is exercised offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional

DATASET_ID = "nvidia/ToolScale"


@dataclass
class GoldAction:
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    action_id: Optional[str] = None


@dataclass
class ToolScaleTask:
    task_id: str
    domain: str
    instruction: str
    gold_actions: List[GoldAction] = field(default_factory=list)
    required_info: List[str] = field(default_factory=list)
    nl_assertions: List[str] = field(default_factory=list)

    def gold_action_names(self) -> List[str]:
        return [a.name for a in self.gold_actions]


def _as_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _str_list(v: Any) -> List[str]:
    out: List[str] = []
    for item in _as_list(v):
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            # communicate_info entries are sometimes {"info": "..."} dicts.
            for key in ("info", "content", "text", "value"):
                if isinstance(item.get(key), str):
                    out.append(item[key])
                    break
    return out


def normalize_row(row: Dict[str, Any], *, index: int = 0) -> ToolScaleTask:
    """Turn one raw ToolScale row into a :class:`ToolScaleTask` (pure)."""
    scenario = row.get("user_scenario") or {}
    instructions = scenario.get("instructions") or {}
    instruction = (
        instructions.get("task_instructions")
        or instructions.get("reason_for_call")
        or row.get("task")
        or row.get("instruction")
        or ""
    )
    domain = scenario.get("domain") or row.get("domain") or "unknown"

    crit = row.get("evaluation_criteria") or {}
    gold: List[GoldAction] = []
    for a in _as_list(crit.get("actions")):
        if isinstance(a, dict) and a.get("name"):
            gold.append(
                GoldAction(
                    name=str(a["name"]),
                    arguments=a.get("arguments") or a.get("args") or {},
                    action_id=a.get("action_id"),
                )
            )

    required = _str_list(crit.get("communicate_info"))
    nl = _str_list(crit.get("nl_assertions"))

    task_id = str(row.get("id") or row.get("task_id") or f"toolscale-{index}")
    return ToolScaleTask(
        task_id=task_id,
        domain=str(domain),
        instruction=str(instruction),
        gold_actions=gold,
        required_info=required,
        nl_assertions=nl,
    )


def load_toolscale(
    *,
    max_tasks: Optional[int] = None,
    split: str = "train",
    source: Optional[Iterable[Dict[str, Any]]] = None,
) -> Iterator[ToolScaleTask]:
    """Yield normalized ToolScale tasks.

    ``source`` overrides the HF stream with an iterable of raw row dicts (tests).
    When ``source`` is None, streams ``nvidia/ToolScale`` via ``datasets``.
    """
    if source is None:
        from datasets import load_dataset  # lazy: optional dep / network

        source = load_dataset(DATASET_ID, split=split, streaming=True)

    n = 0
    for i, row in enumerate(source):
        if max_tasks is not None and n >= max_tasks:
            break
        task = normalize_row(dict(row), index=i)
        if not task.instruction.strip():
            continue
        yield task
        n += 1


__all__ = [
    "DATASET_ID",
    "GoldAction",
    "ToolScaleTask",
    "load_toolscale",
    "normalize_row",
]
