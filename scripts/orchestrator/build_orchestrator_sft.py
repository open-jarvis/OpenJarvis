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
        --orchestrator-label qwen \
        --orchestrator-endpoint http://localhost:8001/v1 \
        --orchestrator-model qwen3-8b \
        --samples-per-task 8 --max-keep-per-task 1

Example (v2, re-point at the v1 checkpoint):
    .venv/bin/python scripts/orchestrator/build_orchestrator_sft.py \
        --orchestrator-label qwen \
        --orchestrator-endpoint http://localhost:8010/v1 \
        --orchestrator-model orchestrator-sft-v1 \
        --samples-per-task 8
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
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
from openjarvis.learning.intelligence.orchestrator.sft_data.naming import raw_dir_name
from openjarvis.learning.intelligence.orchestrator.sft_data.reject_sample import (
    generate_sft_dataset,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.verify import make_verifier


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # --out is a TAG, not a path. The run dir is always
    # <data-root>/raw/{label}-{month}-{day}-{year}-{hhmm}{am|pm}[-{tag}]/ and the
    # file inside is always data.jsonl — see the run_dir block below. Use --out
    # only to distinguish two runs of the same orchestrator (e.g. --out balanced50).
    p.add_argument(
        "--out",
        default=None,
        help="Optional tag appended to the run dir name (not a path).",
    )
    # The orchestrator == the local Qwen3-8B self-sampling over its own rollouts.
    p.add_argument(
        "--orchestrator-endpoint",
        default="http://localhost:8001/v1",
        help="OpenAI-compatible vLLM base URL serving the orchestrator.",
    )
    p.add_argument("--orchestrator-model", default="qwen3-8b")
    p.add_argument("--orchestrator-api-key", default="EMPTY")
    # Provenance stamps: when set, every written record carries these fields so
    # the JSONL is self-identifying once pooled across model families (gemma vs
    # qwen). Default None -> no stamping (existing qwen runs unaffected).
    p.add_argument(
        "--gen-model",
        default=None,
        help="Full HF id of the generating orchestrator, stamped as "
        "record['gen_model'] (e.g. google/gemma-4-26B-A4B-it).",
    )
    p.add_argument(
        "--orchestrator-label",
        default=None,
        help="Short label stamped as record['orchestrator_model'] (e.g. gemma-4-26b).",
    )
    # Local OSS model endpoints; repeatable "model_id=base_url" (e.g.
    # "Qwen/Qwen3.5-9B=http://localhost:8001/v1"). Unmapped local models are
    # still listed but served unconfigured (base_url=None).
    p.add_argument(
        "--local-endpoint",
        action="append",
        default=[],
        metavar="MODEL_ID=URL",
        help="Local model id -> vLLM base URL (repeatable).",
    )
    p.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="Cap on tasks (default: all of load_sft_tasks()).",
    )
    p.add_argument(
        "--skip-task-ids-from",
        action="append",
        default=[],
        metavar="GLOB",
        help="Glob of prior data.jsonl files; skip task_ids already "
        "generated there so this run only does unseen prompts "
        "(resume). Repeatable; applied before sharding.",
    )
    p.add_argument("--samples-per-task", type=int, default=8)
    p.add_argument("--max-keep-per-task", type=int, default=1)
    p.add_argument("--max-turns", type=int, default=8)
    p.add_argument("--temperature", type=float, default=0.7)
    # Orchestrator completion cap per turn. The library default (4096) intermittently
    # truncates the final answer mid-sentence on longer reasoning turns; bump it so
    # the trace ends cleanly. Raise further (e.g. 16384) if traces still cut off.
    p.add_argument(
        "--max-tokens",
        type=int,
        default=8192,
        help="Per-turn completion cap for the orchestrator (default 8192).",
    )
    # Number of tasks rolled out concurrently against vLLM. Each in-flight task
    # issues its samples sequentially, so ~concurrency requests hit the server at
    # once. ~30-50 is comfortable on 1xL40S (prefix caching + continuous batching).
    p.add_argument(
        "--concurrency",
        type=int,
        default=32,
        help="Tasks rolled out in parallel (default 32).",
    )
    # Balanced-smoke pull: cap//4 from each of GeneralThought + OpenThoughts
    # code/math/science instead of the GeneralThought-only fast cap path. Use for a
    # representative smoke; the real run omits --max-tasks for the full 8K balanced set.
    p.add_argument(
        "--balanced",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Draw an EVEN cross-domain sample (GeneralThought + "
        "OpenThoughts code/math/science). Default ON — pass "
        "--no-balanced for the old GeneralThought-only skew.",
    )
    # Data-parallel sharding: split the (deterministic, seed-42) task list across
    # N independent driver processes, each pointed at its own orchestrator vLLM
    # replica. Shard i takes tasks[i::N] (a strided slice, so every shard stays
    # domain-balanced). Each writes its own --out file; concatenate the shard
    # JSONLs afterward. Lets the GPU-bound orchestrator scale across idle GPUs.
    p.add_argument(
        "--shard-index",
        type=int,
        default=0,
        help="This shard's index in [0, shard-count).",
    )
    p.add_argument(
        "--shard-count",
        type=int,
        default=1,
        help="Total number of shards (default 1 = no sharding).",
    )
    # Throughput knob: stop sampling a task as soon as max-keep-per-task passing
    # trajectories are found, instead of always running all --samples-per-task.
    # ~3-4x faster when most tasks solve early, but keeps the *first* passers
    # rather than the *cheapest* of N (drops the cost-optimisation signal).
    p.add_argument(
        "--stop-at-keep",
        action="store_true",
        help="Short-circuit a task once max-keep passing samples found.",
    )
    # Anonymize model experts (opaque random labels, uniform description, no cost
    # line, shuffled order) so the policy can't route on a model's name/position/
    # cost. The anon->real map is saved per record (metrics.anon_map) for analysis.
    p.add_argument(
        "--anonymize-experts",
        action="store_true",
        help="Hide expert identity (random labels + shuffle) when routing.",
    )
    # By default we keep EVERY rolled-out trajectory (correct + incorrect), each
    # tagged with ``correct`` (verifier verdict) and ``kept`` (the cheapest-correct
    # sample the rejection sampler would pick). Lets you compute accuracy / inspect
    # failures from the JSONL directly. --rejection-only restores the old
    # drop-the-failures behaviour (only cheapest-correct written).
    p.add_argument(
        "--rejection-only",
        action="store_true",
        help="Drop incorrect rollouts; write only the cheapest-correct "
        "sample per task (the original behaviour).",
    )
    # Rollouts call shell_exec / file_write with model-chosen relative paths
    # (e.g. ``solution.py``), which otherwise land in the repo root. Run them
    # from a throwaway scratch dir so generated files never dirty the tree.
    # gitignored via the existing ``scratch/`` rule.
    p.add_argument(
        "--scratch-dir",
        default="scratch/sft-rollouts",
        help="CWD for rollouts; stray tool-written files go here.",
    )
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Quiet the per-request HTTP / dataset-stream spam so the run log stays
    # readable (rollout calls and dataset shards otherwise flood it).
    for _noisy in (
        "httpx",
        "httpcore",
        "urllib3",
        "datasets",
        "fsspec",
        "huggingface_hub",
        "openai",
    ):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    # Every run lands in its OWN folder under <data-root>/raw/, sharing its stamp
    # with every file later carved from it — only the stage word differs:
    #
    #   raw/qwen-july-7-2026-0553pm/data.jsonl        <- every rollout, incl. failures
    #   sft/qwen-clean-july-7-2026-0553pm.jsonl       <- reject-sampled from it
    #
    # so any curated file traces back to its generation run by eye. raw/ sits ABOVE
    # the sft/rl fork on purpose: SFT keeps only correct+clean rows, but GRPO needs
    # the failures, and both read the same pool. Naming lives in sft_data.naming.
    # --out is an optional extra TAG, not a path; the file inside is always data.jsonl.
    #
    # OJ_DATA_ROOT keeps the data OUT of the git checkout (repo-relative default so
    # a fresh clone still works); this workspace points it at the experiments tree.
    data_root = Path(os.getenv("OJ_DATA_ROOT", "data/orchestrator"))
    prefix = args.orchestrator_label or "orch"
    tag = Path(args.out).stem if args.out else ""
    base = data_root / "raw" / raw_dir_name(prefix, tag=tag)
    run_dir = base.resolve()
    n = 1
    while run_dir.exists():  # same name+minute (parallel shards) -> disambiguate
        n += 1
        run_dir = base.with_name(f"{base.name}-{n}").resolve()
    label = run_dir.name
    out_p = run_dir / "data.jsonl"
    lock_p = out_p.with_suffix(out_p.suffix + ".lock")
    out_p.parent.mkdir(parents=True, exist_ok=True)
    lock_p.write_text(f"{time.strftime('%m-%d-%I%M%p').lower()} pid={os.getpid()}")
    args.out = str(out_p)
    import atexit

    atexit.register(lambda: lock_p.exists() and lock_p.unlink())
    logging.info("Run dir: %s", run_dir)

    # Enrich Braintrust rollout traces with run-level provenance (no-op-safe;
    # tracing.run_context() reads these). setdefault so an explicit env wins.
    os.environ.setdefault("OJ_RUN_LABEL", label)
    os.environ.setdefault("OJ_GEN_MODEL", args.gen_model or args.orchestrator_model)
    os.environ.setdefault("OJ_RUN_STAGE", "smoke" if args.max_tasks else "prod")
    os.environ["OJ_CFG_TEMPERATURE"] = str(args.temperature)
    os.environ["OJ_CFG_MAX_TURNS"] = str(args.max_turns)
    os.environ["OJ_CFG_ANONYMIZE"] = str(bool(args.anonymize_experts))
    os.environ["OJ_CFG_REJECTION_ONLY"] = str(bool(args.rejection_only))

    # Sandbox the rollouts: chdir into a scratch dir so any file a rollout writes
    # (shell_exec redirects, file_write with a relative path) lands there instead
    # of the repo root. (--out is already absolute via run_dir.resolve() above.)
    scratch = Path(args.scratch_dir).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    os.chdir(scratch)
    logging.info("Rollout scratch dir (cwd): %s", scratch)

    local_endpoints = {}
    for item in args.local_endpoint:
        model_id, _, url = item.partition("=")
        if model_id and url:
            local_endpoints[model_id] = url
    tools = orchestrator_catalog(local_endpoints=local_endpoints or None)
    # Drop the no-op ``think`` scratchpad tool: it adds turns/cost and is a
    # harness-leakage vector (the model narrates the routing rule inside a think
    # call, which the reasoning-scrub can't reach). The model still reasons in
    # its own <think> blocks — it just can't emit reasoning AS a tool call.
    tools = [t for t in tools if t.name != "think"]
    logging.info("Tool catalog (%d): %s", len(tools), [t.name for t in tools])

    call_orch = make_call_orchestrator(
        args.orchestrator_model,
        base_url=args.orchestrator_endpoint,
        api_key=args.orchestrator_api_key,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    dispatch = make_dispatch({})

    # Build the provenance stamp once (None if neither flag given).
    record_extra = {}
    if args.gen_model:
        record_extra["gen_model"] = args.gen_model
    if args.orchestrator_label:
        record_extra["orchestrator_model"] = args.orchestrator_label
    record_extra = record_extra or None

    def rollout_fn(task):
        try:
            return run_unified_rollout(
                task.instruction,
                tools,
                call_orchestrator=call_orch,
                dispatch=dispatch,
                max_turns=args.max_turns,
                anonymize=args.anonymize_experts,
            )
        except Exception as exc:  # network/key failures shouldn't kill the run
            logging.warning("rollout failed for %s: %s", task.task_id, exc)
            return None

    # cap= caps the task count for smoke runs; --balanced makes that small sample
    # cross-domain (GeneralThought + OpenThoughts code/math/science) instead of the
    # GeneralThought-only fast path. The real run omits --max-tasks (full 8K balanced).
    tasks = load_sft_tasks(cap=args.max_tasks, balanced=args.balanced)
    # Resume on unseen prompts: drop task_ids already generated in prior runs
    # (per-track seen set via --skip-task-ids-from). Filter BEFORE sharding so the
    # remaining unseen tasks stride evenly and never re-cover finished prompts.
    if args.skip_task_ids_from:
        import glob as _glob

        skip_ids = set()
        for pattern in args.skip_task_ids_from:
            for fp in _glob.glob(pattern):
                try:
                    with open(fp) as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                tid = json.loads(line).get("task_id")
                            except Exception:
                                continue
                            if tid:
                                skip_ids.add(tid)
                except OSError:
                    continue
        if skip_ids:
            n_before = len(tasks)
            tasks = [t for t in tasks if t.task_id not in skip_ids]
            logging.info(
                "Resume: %d done task_ids -> skipping; %d of %d tasks remain",
                len(skip_ids),
                len(tasks),
                n_before,
            )
    if args.shard_count > 1:
        n_all = len(tasks)
        tasks = tasks[args.shard_index :: args.shard_count]
        logging.info(
            "Shard %d/%d -> %d of %d tasks",
            args.shard_index,
            args.shard_count,
            len(tasks),
            n_all,
        )
    from collections import Counter as _Counter

    _dom = _Counter(getattr(t, "domain", "unknown") for t in tasks)
    logging.info(
        "Loaded %d SFT tasks | balanced=%s | domain split: %s",
        len(tasks),
        args.balanced,
        ", ".join(f"{d}={n}" for d, n in sorted(_dom.items())),
    )

    stats = generate_sft_dataset(
        args.out,
        tasks=tasks,
        tools=tools,
        rollout_fn=rollout_fn,
        verify_fn=make_verifier(),
        samples_per_task=args.samples_per_task,
        max_keep_per_task=args.max_keep_per_task,
        reward_fn=lambda r: -r.cost_usd,  # cheapest-correct gets highest reward
        concurrency=args.concurrency,
        stop_at_keep=args.stop_at_keep,
        keep_all=not args.rejection_only,
        record_extra=record_extra,
    )
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
