#!/usr/bin/env python3
"""Publish OpenJarvis eval results to a Hugging Face dataset.

Dataset structure:
  Config (subset) = benchmark  (e.g. "liveresearch", "toolcall15")
  Split           = model slug  (e.g. "claude-opus-4-6", "gpt-5-4-2026-03-05")

Usage:
  # Publish a single result file
  python scripts/publish_results.py results/neurips-2026/baselines/claude-opus/liveresearch/liveresearch_claude-opus-4-6.jsonl

  # Publish all neurips baseline results at once
  python scripts/publish_results.py --all results/neurips-2026/baselines/

  # Dry run (prints what would be uploaded without pushing)
  python scripts/publish_results.py --dry-run results/neurips-2026/baselines/claude-opus/toolcall15/toolcall15_claude-opus-4-6.jsonl

  # Override repo
  python scripts/publish_results.py --repo my-org/my-results results/...

Login first:  hf auth login
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_HF_REPO = "akenginorhun/neurips-2026-evals"   # change to your org/repo

# Columns to include in the published dataset (order preserved)
KEEP_COLUMNS = [
    "record_id",
    "benchmark",
    "model",
    "backend",
    "problem",
    "reference",
    "model_answer",
    "is_correct",
    "score",
    "latency_seconds",
    "prompt_tokens",
    "completion_tokens",
    "cost_usd",
    "throughput_tok_per_sec",
    "energy_joules",
    "power_watts",
    "gpu_utilization_pct",
    "estimated_flops",
    "scoring_metadata",
    "error",
    "trace_data",  # Include trace data for analysis
]

# ── Helpers ───────────────────────────────────────────────────────────────────


def _model_to_split(model: str) -> str:
    """Turn a model name into a valid HF split name (alphanumeric + underscores)."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", model).strip("_")


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    """Select and normalise columns for publishing."""
    out: dict[str, Any] = {}
    for col in KEEP_COLUMNS:
        val = row.get(col)
        # Serialise dicts/lists to JSON strings so HF doesn't complain about
        # nested schemas varying across benchmarks.
        if isinstance(val, (dict, list)):
            val = json.dumps(val, ensure_ascii=False)
        out[col] = val
    # Ensure string columns never have None (causes schema mismatch across splits)
    for col in ("error", "model_answer", "reference", "problem", "scoring_metadata",
                "record_id", "benchmark", "model", "backend", "trace_data"):
        if out.get(col) is None:
            out[col] = ""
    return out


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def publish_file(path: Path, repo_id: str, token: str | None = None, dry_run: bool = False) -> None:
    rows = load_jsonl(path)
    if not rows:
        print(f"  [skip] {path} — empty file")
        return

    benchmark = rows[0].get("benchmark", "")
    model = rows[0].get("model", "")

    if not benchmark or not model:
        print(f"  [skip] {path} — missing benchmark or model field")
        return

    split = _model_to_split(model)
    cleaned = [_clean_row(r) for r in rows]

    print(f"  benchmark={benchmark!r}  model={model!r}  split={split!r}  rows={len(cleaned)}")

    if dry_run:
        print(f"  [dry-run] would push to {repo_id} / config={benchmark} / split={split}")
        return

    try:
        from datasets import Dataset, Features, Value
    except ImportError:
        print("  [error] Install datasets:  pip install datasets")
        sys.exit(1)

    # Explicit schema so all splits share the same types regardless of null content
    features = Features({
        "record_id": Value("string"),
        "benchmark": Value("string"),
        "model": Value("string"),
        "backend": Value("string"),
        "problem": Value("string"),
        "reference": Value("string"),
        "model_answer": Value("string"),
        "is_correct": Value("bool"),
        "score": Value("float64"),
        "latency_seconds": Value("float64"),
        "prompt_tokens": Value("int64"),
        "completion_tokens": Value("int64"),
        "cost_usd": Value("float64"),
        "throughput_tok_per_sec": Value("float64"),
        "energy_joules": Value("float64"),
        "power_watts": Value("float64"),
        "gpu_utilization_pct": Value("float64"),
        "estimated_flops": Value("float64"),
        "scoring_metadata": Value("string"),
        "error": Value("string"),
        "trace_data": Value("string"),  # JSON-serialized trace data
    })
    ds = Dataset.from_list(cleaned, features=features)
    ds.push_to_hub(
        repo_id,
        config_name=benchmark,
        split=split,
        token=token,
        commit_message=f"results: {benchmark} / {model} ({len(cleaned)} samples)",
    )
    print(f"  [ok] pushed → {repo_id} / {benchmark} / {split}")


def publish_all(baselines_dir: Path, repo_id: str, token: str | None = None, dry_run: bool = False) -> None:
    files = sorted(baselines_dir.rglob("*.jsonl"))
    files = [f for f in files if "traces" not in f.parts]
    if not files:
        print(f"No JSONL files found under {baselines_dir}")
        return
    print(f"Found {len(files)} result file(s) under {baselines_dir}\n")
    for f in files:
        print(f"Publishing: {f}")
        publish_file(f, repo_id=repo_id, token=token, dry_run=dry_run)
        print()


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish eval results to Hugging Face.")
    parser.add_argument(
        "path",
        type=Path,
        help="Path to a single JSONL result file, or a baselines/ directory when --all is set.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Recursively publish all JSONL files under the given directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be uploaded without actually pushing.",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_HF_REPO,
        help=f"HF repo ID to push to (default: {DEFAULT_HF_REPO})",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="HuggingFace API token (overrides HUGGINGFACE_HUB_TOKEN env var)",
    )
    args = parser.parse_args()

    token = args.token or os.environ.get("HUGGINGFACE_HUB_TOKEN")

    if args.dry_run:
        print("[dry-run mode — nothing will be pushed]\n")

    if args.all:
        publish_all(args.path, repo_id=args.repo, token=token, dry_run=args.dry_run)
    else:
        if not args.path.is_file():
            print(f"Error: {args.path} is not a file. Use --all for directories.")
            sys.exit(1)
        print(f"Publishing: {args.path}")
        publish_file(args.path, repo_id=args.repo, token=token, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
