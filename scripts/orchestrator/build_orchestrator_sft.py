#!/usr/bin/env python
"""Build orchestrator SFT cold-start data by **base Qwen3-8B self-sampling** (v1).

The orchestrator *is* the local Qwen3-8B. We roll the base (un-trained) model out
over the reasoning-SFT task pool (``load_sft_tasks``: GeneralThought + OpenThoughts
code/math/science), verify each trajectory's final answer against the gold
(``verify.make_verifier`` — math/code checkers + Gemini judge fallback), and keep
the cheapest-correct trajectory per task. Those passing trajectories become the
``conversations`` JSONL the SFT trainer consumes — i.e. the model learns from its
own successful rollouts (rejection-sampling cold-start, STaR-style).

This is **v1** (base self-sampling): point ``--orchestrator-endpoint`` at the vLLM
server hosting the *base* ``Qwen/Qwen3-8B``.

For **v2**, train on the v1 data, serve the v1 checkpoint with vLLM, then re-run
this exact driver with ``--orchestrator-endpoint`` pointed at the v1 checkpoint's
endpoint, ``--orchestrator-model`` set to the checkpoint name, and
``--samples-per-task 8`` — the (now stronger) policy self-samples a v2 dataset.

The math/coder specialist tools are only wired when ``--math-endpoint`` /
``--coder-endpoint`` are passed (those are separately-served vLLM specialists);
otherwise they're omitted so the orchestrator only sees the tools it can actually
call.

Example (v1, base self-sampling):
    .venv/bin/python scripts/orchestrator/build_orchestrator_sft.py \
        --out data/orchestrator_sft_v1.jsonl \
        --orchestrator-endpoint http://localhost:8001/v1 \
        --orchestrator-model qwen3-8b \
        --samples-per-task 8 --max-keep-per-task 1

Example (v2, re-point at the v1 checkpoint):
    .venv/bin/python scripts/orchestrator/build_orchestrator_sft.py \
        --out data/orchestrator_sft_v2.jsonl \
        --orchestrator-endpoint http://localhost:8010/v1 \
        --orchestrator-model orchestrator-sft-v1 \
        --samples-per-task 8
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Optional

from openjarvis.agents.hybrid.expert_registry import orchestrator_catalog
from openjarvis.agents.hybrid.toolorchestra.rollout import run_unified_rollout
from openjarvis.agents.hybrid.toolorchestra.unified import (
    make_call_orchestrator,
    make_dispatch,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.datasets import (
    load_sft_tasks,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.reject_sample import (
    generate_sft_dataset,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.verify import make_verifier


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--out", default="data/orchestrator_sft_v1.jsonl")
    # The orchestrator == the local Qwen3-8B self-sampling over its own rollouts.
    p.add_argument("--orchestrator-endpoint", default="http://localhost:8001/v1",
                   help="OpenAI-compatible vLLM base URL serving the orchestrator.")
    p.add_argument("--orchestrator-model", default="qwen3-8b")
    p.add_argument("--orchestrator-api-key", default="EMPTY")
    # Local OSS model endpoints; repeatable "model_id=base_url" (e.g.
    # "Qwen/Qwen3.5-9B=http://localhost:8001/v1"). Unmapped local models are
    # still listed but served unconfigured (base_url=None).
    p.add_argument("--local-endpoint", action="append", default=[],
                   metavar="MODEL_ID=URL",
                   help="Local model id -> vLLM base URL (repeatable).")
    p.add_argument("--max-tasks", type=int, default=None,
                   help="Cap on tasks (default: all of load_sft_tasks()).")
    p.add_argument("--samples-per-task", type=int, default=8)
    p.add_argument("--max-keep-per-task", type=int, default=1)
    p.add_argument("--max-turns", type=int, default=8)
    p.add_argument("--temperature", type=float, default=0.7)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    local_endpoints = {}
    for item in args.local_endpoint:
        model_id, _, url = item.partition("=")
        if model_id and url:
            local_endpoints[model_id] = url
    tools = orchestrator_catalog(local_endpoints=local_endpoints or None)
    logging.info("Tool catalog (%d): %s", len(tools), [t.name for t in tools])

    call_orch = make_call_orchestrator(
        args.orchestrator_model,
        base_url=args.orchestrator_endpoint,
        api_key=args.orchestrator_api_key,
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

    tasks = load_sft_tasks()
    if args.max_tasks is not None:
        tasks = tasks[: args.max_tasks]
    logging.info("Loaded %d SFT tasks", len(tasks))

    stats = generate_sft_dataset(
        args.out,
        tasks=tasks,
        tools=tools,
        rollout_fn=rollout_fn,
        verify_fn=make_verifier(),
        samples_per_task=args.samples_per_task,
        max_keep_per_task=args.max_keep_per_task,
        reward_fn=lambda r: -r.cost_usd,  # cheapest-correct gets highest reward
    )
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
