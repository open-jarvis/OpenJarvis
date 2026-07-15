#!/usr/bin/env python
"""Carve train / holdout / overfit100 splits from a clean orchestrator-SFT pool.

Replaces make_tranches.py + make_gemma_tranches.py, which carved 1k/2k/4k/8k
data-scaling tranches from the June pool. That lineage is dead: the tranches it
produced trained checkpoints that evaluated at base ~= 1k ~= 2k (the pool taught
the orchestrator to re-derive answers itself instead of routing), and the pool
was deleted. The lesson is in data/orchestrator/README.md — it was a data-QUALITY
ceiling, so re-running the old scaling ladder buys nothing.

Reads a clean pool (reject-sampled from raw/) and writes the SFT splits to sft/.
Naming is uniform — ``{name}-{split}-{stamp}`` with name in {qwen, gemma, pooled};
pass several pools to merge-and-restratify into `pooled`. The splits INHERIT the
pool's stamp, so they stay tied to the run that generated the data.

The holdout is domain-stratified so val-loss is leak-free, and `overfit100` is a
strict prefix of train (it is a memorisation sanity check — the model must be
able to fit 100 rows it *has* seen, else the format/masking is broken).
Deterministic (seed 42).

    # one pool -> qwen-{train,holdout,overfit100}-july-7-2026-0553pm.jsonl
    python scripts/orchestrator/make_splits.py --name qwen \
        --pool .../sft/qwen-clean-july-7-2026-0553pm.jsonl

    # merge both -> pooled-{train,holdout,overfit100}-july-7-2026-0553pm.jsonl
    python scripts/orchestrator/make_splits.py --name pooled \
        --pool .../sft/qwen-clean-july-7-2026-0553pm.jsonl \
        --pool .../sft/gemma-clean-july-7-2026-0553pm.jsonl
"""

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

from openjarvis.learning.intelligence.orchestrator.sft_data.naming import (
    dataset_name,
    run_stamp,
    stamp_from,
)

# Where the orchestrator data tree lives. Repo-relative by default so a fresh
# clone works out of the box; set OJ_DATA_ROOT to keep the data OUT of the git
# checkout (this workspace points it at ~/experiments/orchestrator/data, so a
# stray `git reset` can't touch hundreds of GB of generations).
DATA_ROOT = Path(os.getenv("OJ_DATA_ROOT", "data/orchestrator"))
OUT = DATA_ROOT / "sft"
SEED = 42
OVERFIT_N = 100
# Orchestrator that generated each pool — stamped onto every row so provenance
# survives a merge (the filename encodes it too, but the field is cheap insurance
# and is what the `pooled` splits rely on to stay attributable).
ORCH_MODEL = {"qwen": "qwen3.5-9b", "gemma": "gemma-4-26b"}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--name",
        required=True,
        help="split family: qwen | gemma | pooled (drives the filename)",
    )
    ap.add_argument(
        "--pool",
        action="append",
        required=True,
        metavar="PATH",
        help="clean pool jsonl; repeat to merge (use with --name pooled)",
    )
    ap.add_argument(
        "--holdout-frac",
        type=float,
        default=0.15,
        help="fraction held out, domain-stratified (default 0.15)",
    )
    ap.add_argument(
        "--stamp",
        default=None,
        help="Stamp for the output names, e.g. july-7-2026-0553pm. Defaults to the "
        "POOL's stamp (read off its filename) so a split stays tied to the run "
        "that generated it, NOT to the day it happened to be carved. Falls back "
        "to now only if no pool name carries a stamp.",
    )
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    # A split belongs to the generation run, not to the day it was carved — so
    # inherit the pool's stamp unless told otherwise.
    stamp = args.stamp or next(
        (s for p in args.pool if (s := stamp_from(Path(p).name))), None
    ) or run_stamp()

    rows = []
    for p in args.pool:
        path = Path(p)
        if not path.exists():
            print(f"!! pool not found: {path}", file=sys.stderr)
            return 1
        # Infer the source orchestrator from the filename so merged pools stay
        # attributable; don't clobber a stamp the pool already carries.
        stem = path.name.split("-", 1)[0]
        loaded = [json.loads(line) for line in path.open() if line.strip()]
        for r in loaded:
            r.setdefault("orchestrator_model", ORCH_MODEL.get(stem, stem))
        rows.extend(loaded)
        print(f"loaded {len(loaded):>5} rows from {path}")
    print(f"pool total: {len(rows)}")

    # GROUPED stratified holdout: split by task_id, never by row.
    #
    # The pool keeps SEVERAL rollouts per question (different attempts at the same
    # task, same gold answer). Splitting by row therefore leaks: attempt A of a
    # question lands in train and attempt B of the SAME question lands in holdout,
    # so val-loss is measured on questions the model trained on. That is exactly
    # what happened to the 0707 splits — 80% of qwen's holdout tasks were also in
    # train, making every val-loss number optimistically biased.
    #
    # So: group rows by task_id, stratify the TASKS by domain, and assign whole
    # tasks to one side. A question is never split across train and holdout.
    by_task = defaultdict(list)
    for i, r in enumerate(rows):
        by_task[r.get("task_id")].append(i)

    task_dom = {t: rows[idxs[0]].get("domain", "misc") for t, idxs in by_task.items()}
    by_dom = defaultdict(list)
    for t, dom in task_dom.items():
        by_dom[dom].append(t)

    rng = random.Random(SEED)
    holdout_tasks: set = set()
    for dom, tasks in sorted(by_dom.items()):
        tasks = sorted(tasks)  # deterministic before sampling
        k = round(args.holdout_frac * len(tasks))
        pick = rng.sample(tasks, min(k, len(tasks)))
        holdout_tasks.update(pick)
        print(f"  {dom:<9} tasks={len(tasks):>4} holdout={len(pick)}")

    holdout_idx = {i for t in holdout_tasks for i in by_task[t]}
    holdout = [rows[i] for i in sorted(holdout_idx)]
    train = [r for i, r in enumerate(rows) if i not in holdout_idx]  # order preserved
    overfit = train[:OVERFIT_N]

    # Assert the leak is actually gone — this is the whole point of the grouping.
    tr_tasks = {r.get("task_id") for r in train}
    ho_tasks = {r.get("task_id") for r in holdout}
    overlap = tr_tasks & ho_tasks
    if overlap:
        raise SystemExit(f"!! LEAK: {len(overlap)} task_ids in BOTH train and holdout")
    print(
        f"train={len(train)} rows / {len(tr_tasks)} tasks  "
        f"holdout={len(holdout)} rows / {len(ho_tasks)} tasks  "
        f"overfit={len(overfit)}  (0 tasks shared)"
    )

    args.out.mkdir(parents=True, exist_ok=True)
    written = {}
    for split, data in (
        ("train", train),
        ("holdout", holdout),
        (f"overfit{OVERFIT_N}", overfit),
    ):
        f = args.out / f"{dataset_name(args.name, split, stamp)}.jsonl"
        f.write_text("".join(json.dumps(r) + "\n" for r in data))
        written[split] = f
        print(f"wrote {f} ({len(data)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
