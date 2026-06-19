"""Rejection-sampling SFT-data generator (the ToolOrchestra cold-start).

For each ToolScale task: roll out a teacher orchestrator N times, verify each
trajectory, keep the passing ones (optionally just the cheapest), and serialize
them into the unified-tool ``conversations`` JSONL the SFT trainer consumes.

The expensive/network parts are injected so the orchestration is pure and
offline-testable:

* ``rollout_fn(task) -> UnifiedRollout`` — one teacher rollout (temperature>0).
* ``verify_fn(task, rollout) -> bool``   — did the trajectory solve the task?

:func:`gold_coverage_verify` is a dependency-free default verifier (checks the
trajectory's tool calls cover the task's golden action names); a real run should
compose it with an LLM judge on the final answer.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from typing import Any

from openjarvis.agents.hybrid.expert_registry import ExpertTool
from openjarvis.agents.hybrid.toolorchestra.rollout import UnifiedRollout
from openjarvis.learning.intelligence.orchestrator.sft_data.unified_serialize import (
    trajectory_to_record,
)

logger = logging.getLogger(__name__)

# The sampler only touches ``task.task_id`` / ``task.instruction`` / ``task.domain``
# (via ``trajectory_to_record``), so any task dataclass works — ToolScaleTask or the
# reasoning ``datasets.Task``. ``gold_coverage_verify`` additionally needs
# ``gold_action_names()`` (ToolScale-only), but callers using ``datasets.Task`` pass
# their own ``verify_fn`` (e.g. ``verify.make_verifier()``) instead.
TaskLike = Any
RolloutFn = Callable[[TaskLike], Optional[UnifiedRollout]]
VerifyFn = Callable[[TaskLike, UnifiedRollout], bool]


def gold_coverage_verify(task: TaskLike, rollout: UnifiedRollout) -> bool:
    """Dependency-free proxy verifier: trajectory must (a) produce a non-empty
    answer and (b) call tools covering every golden action name.

    This is the offline stand-in for ToolScale's execution-correctness checker
    (which needs the DB simulator). Compose with an LLM judge for real runs.
    """
    if not rollout.final_answer.strip():
        return False
    gold = set(task.gold_action_names())
    if not gold:
        return True
    called = {name for name, _ in rollout.tool_calls()}
    return gold.issubset(called)


def generate_sft_dataset(
    out_path: str,
    *,
    tasks: Iterable[TaskLike],
    tools: List[ExpertTool],
    rollout_fn: RolloutFn,
    verify_fn: VerifyFn = gold_coverage_verify,
    samples_per_task: int = 4,
    max_keep_per_task: int = 1,
    reward_fn: Optional[Callable[[UnifiedRollout], float]] = None,
) -> dict:
    """Run rejection sampling over ``tasks`` and write the SFT JSONL.

    ``max_keep_per_task`` caps records kept per task; when >1 the cheapest
    passing trajectories are kept first. Returns stats + writes a ``.stats.json``.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    seen = 0
    written = 0
    dropped = 0
    domain_counts: Counter[str] = Counter()

    with out.open("w") as fh:
        for task in tasks:
            seen += 1
            passing: List[UnifiedRollout] = []
            for _ in range(samples_per_task):
                roll = rollout_fn(task)
                if roll is None:
                    continue
                if verify_fn(task, roll):
                    passing.append(roll)
            if not passing:
                dropped += 1
                continue
            # Keep cheapest-first.
            passing.sort(key=lambda r: r.cost_usd)
            for roll in passing[:max_keep_per_task]:
                reward = reward_fn(roll) if reward_fn else 0.0
                record = trajectory_to_record(
                    task.task_id, task.instruction, tools, roll,
                    reward=reward, domain=task.domain,
                )
                fh.write(json.dumps(record) + "\n")
                written += 1
                domain_counts[task.domain] += 1

    stats = {
        "out_path": str(out),
        "tasks_seen": seen,
        "records_written": written,
        "tasks_dropped": dropped,
        "samples_per_task": samples_per_task,
        "domain_distribution": dict(domain_counts),
    }
    out.with_suffix(out.suffix + ".stats.json").write_text(json.dumps(stats, indent=2))
    logger.info("Wrote %d SFT records to %s", written, out)
    return stats


__all__ = ["generate_sft_dataset", "gold_coverage_verify"]
