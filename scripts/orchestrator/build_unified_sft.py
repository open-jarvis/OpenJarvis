#!/usr/bin/env python
"""Build ToolOrchestra SFT data by rejection sampling over ToolScale.

For each ToolScale task, a teacher orchestrator is rolled out N times over the
faithful unified tool catalog (one tool per model); passing trajectories are
serialized into the conversations JSONL the SFT trainer consumes.

Needs API access for the teacher + expert models (set the usual env keys).

Example:
    uv run python scripts/orchestrator/build_unified_sft.py \
        --out data/orchestrator_unified_sft.jsonl \
        --teacher-model gpt-5 --max-tasks 200 --samples-per-task 4 \
        --local-model qwen3:8b --local-endpoint http://localhost:8001/v1
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Optional

from openjarvis.agents.hybrid.expert_registry import default_catalog
from openjarvis.agents.hybrid.toolorchestra.unified import (
    make_call_orchestrator,
    make_dispatch,
)
from openjarvis.agents.hybrid.toolorchestra.rollout import run_unified_rollout
from openjarvis.learning.intelligence.orchestrator.sft_data.reject_sample import (
    generate_sft_dataset,
    gold_coverage_verify,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.toolscale import (
    load_toolscale,
)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="data/orchestrator_unified_sft.jsonl")
    p.add_argument("--teacher-model", default="claude-sonnet-4-6")
    p.add_argument("--teacher-base-url", default="https://api.anthropic.com/v1/",
                   help="OpenAI-compatible base URL; pass '' for OpenAI cloud.")
    p.add_argument("--max-tasks", type=int, default=200)
    p.add_argument("--samples-per-task", type=int, default=4)
    p.add_argument("--max-keep-per-task", type=int, default=1)
    p.add_argument("--max-turns", type=int, default=50)
    p.add_argument("--temperature", type=float, default=1.0)
    p.add_argument("--local-model", default=None)
    p.add_argument("--local-endpoint", default=None)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    tools = default_catalog(
        local_model=args.local_model, local_endpoint=args.local_endpoint,
    )
    logging.info("Tool catalog (%d): %s", len(tools), [t.name for t in tools])

    base_url = args.teacher_base_url or None
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        if base_url and "anthropic" in base_url
        else os.environ.get("OPENAI_API_KEY")
    )
    call_orch = make_call_orchestrator(
        args.teacher_model,
        base_url=base_url,
        api_key=api_key,
        temperature=args.temperature,
    )
    dispatch = make_dispatch({})

    def rollout_fn(task):
        try:
            return run_unified_rollout(
                task.instruction, tools,
                call_orchestrator=call_orch, dispatch=dispatch,
                max_turns=args.max_turns,
            )
        except Exception as exc:  # network/key failures shouldn't kill the run
            logging.warning("rollout failed for %s: %s", task.task_id, exc)
            return None

    tasks = load_toolscale(max_tasks=args.max_tasks)
    stats = generate_sft_dataset(
        args.out,
        tasks=tasks,
        tools=tools,
        rollout_fn=rollout_fn,
        verify_fn=gold_coverage_verify,
        samples_per_task=args.samples_per_task,
        max_keep_per_task=args.max_keep_per_task,
        reward_fn=lambda r: -r.cost_usd,  # cheapest-correct gets highest reward
    )
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
