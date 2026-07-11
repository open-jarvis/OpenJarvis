#!/usr/bin/env python
"""Carve train / holdout / overfit100 splits from a clean orchestrator-SFT pool.

Replaces make_tranches.py + make_gemma_tranches.py, which carved 1k/2k/4k/8k
data-scaling tranches from the June pool. That lineage is dead: the tranches it
produced trained checkpoints that evaluated at base ~= 1k ~= 2k (the pool taught
the orchestrator to re-derive answers itself instead of routing), and the pool
was deleted. The lesson is in data/orchestrator/README.md — it was a data-QUALITY
ceiling, so re-running the old scaling ladder buys nothing.

Reads a clean pool (reject-sampled from data/orchestrator/raw/) and writes the
SFT splits to data/orchestrator/sft/. Naming is uniform — ``{name}_{split}_{date}``
with name in {qwen, gemma, pooled}; pass several pools to merge-and-restratify
into `pooled`.

The holdout is domain-stratified so val-loss is leak-free, and `overfit100` is a
strict prefix of train (it is a memorisation sanity check — the model must be
able to fit 100 rows it *has* seen, else the format/masking is broken).
Deterministic (seed 42).

    # one pool -> qwen_{train,holdout,overfit100}_0711.jsonl
    python scripts/orchestrator/make_splits.py --name qwen \
        --pool data/orchestrator/sft/qwen_clean_0711.jsonl

    # merge both -> pooled_{train,holdout,overfit100}_0711.jsonl
    python scripts/orchestrator/make_splits.py --name pooled \
        --pool data/orchestrator/sft/qwen_clean_0711.jsonl \
        --pool data/orchestrator/sft/gemma_clean_0711.jsonl
"""

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

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
        "--date",
        default=datetime.now().strftime("%m%d"),
        help="date tag in the filename (default: today, MMDD)",
    )
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    rows = []
    for p in args.pool:
        path = Path(p)
        if not path.exists():
            print(f"!! pool not found: {path}", file=sys.stderr)
            return 1
        # Infer the source orchestrator from the filename so merged pools stay
        # attributable; don't clobber a stamp the pool already carries.
        stem = path.name.split("_", 1)[0]
        loaded = [json.loads(line) for line in path.open() if line.strip()]
        for r in loaded:
            r.setdefault("orchestrator_model", ORCH_MODEL.get(stem, stem))
        rows.extend(loaded)
        print(f"loaded {len(loaded):>5} rows from {path}")
    print(f"pool total: {len(rows)}")

    # Stratified holdout: per-domain, proportional to domain size.
    by_dom = defaultdict(list)
    for i, r in enumerate(rows):
        by_dom[r.get("domain", "misc")].append(i)
    rng = random.Random(SEED)
    holdout_idx: set = set()
    for dom, idxs in sorted(by_dom.items()):
        k = round(args.holdout_frac * len(idxs))
        pick = rng.sample(idxs, min(k, len(idxs)))
        holdout_idx.update(pick)
        print(f"  {dom:<9} pool={len(idxs):>4} holdout={len(pick)}")

    holdout = [rows[i] for i in sorted(holdout_idx)]
    train = [r for i, r in enumerate(rows) if i not in holdout_idx]  # order preserved
    overfit = train[:OVERFIT_N]
    print(f"train={len(train)}  holdout={len(holdout)}  overfit={len(overfit)}")

    args.out.mkdir(parents=True, exist_ok=True)
    written = {}
    for split, data in (
        ("train", train),
        ("holdout", holdout),
        (f"overfit{OVERFIT_N}", overfit),
    ):
        f = args.out / f"{args.name}_{split}_{args.date}.jsonl"
        f.write_text("".join(json.dumps(r) + "\n" for r in data))
        written[split] = f
        print(f"wrote {f} ({len(data)})")

    # ---- auto-upload train + holdout to Braintrust ----
    # Gated by OJ_BRAINTRUST_AUTOUPLOAD (default ON); a total no-op / never raises
    # if the key/pkg is missing or the upload errors (see upload_to_braintrust).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from upload_to_braintrust import autoupload

        autoupload(
            [
                f"{written['train']}={args.name}_train_{args.date}",
                f"{written['holdout']}={args.name}_holdout_{args.date}",
            ],
            run_label=os.getenv("OJ_RUN_LABEL", f"{args.name}_splits_{args.date}"),
            description=f"{args.name} orchestrator-SFT splits (make_splits.py)",
        )
    except Exception as exc:  # telemetry must never break the data pipeline
        print(f"[braintrust] autoupload hook skipped ({exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
