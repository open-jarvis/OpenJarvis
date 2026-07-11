#!/usr/bin/env python
"""Render graded orchestrator-eval JSONL records into clean, readable .txt files.

Companion to ``format_sft_sample.py`` (same banner/indent visual style), but
for the *scored* eval outputs written by ``eval_orchestrator.py``:

    results/orch-eval-<model>-<tranche>-<suite>/<benchmark>_orchestrator.jsonl

Each record has: record_id, benchmark, model, model_answer (the model's
FINAL_ANSWER string), is_correct, score, latency_seconds, cost_usd, error, and
scoring_metadata. The full step-by-step routing trace is NOT saved — only the
final answer + gold + score — so this renderer cannot show intermediate steps.

The QUESTION text is not in the result JSONL; it's loaded from the benchmark
dataset by ``record_id`` (via ``openjarvis.evals.cli._build_dataset``). If the
dataset can't be loaded / the id doesn't match, we render everything else and
show "(question unavailable)".

Gold answer lives in ``scoring_metadata`` (shape varies by scorer):
  * MCQ (mmlu-pro, supergpqa): ``reference_letter``.
  * LLM-judge (gaia): parsed from ``raw_judge_output`` (`gold target "..."`),
    plus the judge's ``reasoning``.
  * anything else: dumped verbatim under SCORING (raw).

Usage:
  .venv/bin/python scripts/orchestrator/format_eval_sample.py \
      --input results/orch-eval-gemma-2k-full/gaia_orchestrator.jsonl --n 2

  ... --input <file> --lines 1,5,42          # specific 1-indexed lines
  ... --input <file> --all                    # one .txt per record
  ... --input <file> --all --only-wrong       # only incorrect samples
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

WIDTH = 80

# Friendly aliases -> the registry keys _build_dataset expects (mirrors
# eval_orchestrator.BENCHMARK_ALIASES for the ones that write .jsonl here).
BENCHMARK_ALIASES = {
    "mmlu_pro": "mmlu-pro",
    "mmlu-pro": "mmlu-pro",
    "gaia": "gaia",
    "taubench": "taubench",
    "supergpqa": "supergpqa",
    "terminalbench_v2_1": "terminalbench-v2.1",
    "terminalbench-v2.1": "terminalbench-v2.1",
}


def _banner(label: str) -> str:
    """Full-width headline: ``━━━  LABEL  ━━━━━━…``."""
    prefix = f"━━━  {label}  "
    fill = "━" * max(3, WIDTH - len(prefix))
    return f"\n{prefix}{fill}\n"


def _indent(text: str, pad: str = "    ") -> str:
    text = (text or "").rstrip()
    return "\n".join(pad + ln if ln.strip() else ln for ln in text.splitlines())


def _normalize_benchmark(name: str) -> str:
    key = (name or "").strip()
    return BENCHMARK_ALIASES.get(key, BENCHMARK_ALIASES.get(key.lower(), key))


# ---------------------------------------------------------------------------
# Question map: record_id -> problem text, loaded from the benchmark dataset.
# ---------------------------------------------------------------------------
def build_question_map(benchmark: str, n: int, seed: int = 42) -> dict:
    """Best-effort {record_id: problem}. Returns {} if the dataset can't load."""
    try:
        from openjarvis.evals.cli import _build_dataset

        ds = _build_dataset(_normalize_benchmark(benchmark))
        ds.load(max_samples=n, seed=seed)
        return {r.record_id: r.problem for r in ds.iter_records()}
    except Exception as exc:  # noqa: BLE001 - never fail the render over this
        print(
            f"  [warn] could not load dataset for {benchmark!r}: "
            f"{type(exc).__name__}: {exc}"
        )
        return {}


# ---------------------------------------------------------------------------
# Gold / judge parsing out of scoring_metadata.
# ---------------------------------------------------------------------------
_GOLD_TARGET_RE = re.compile(r'gold target\s*"([^"]*)"', re.IGNORECASE)
_JUDGE_REASONING_RE = re.compile(
    r"reasoning:\s*(.*?)(?:\n\s*correct:|\Z)", re.IGNORECASE | re.DOTALL
)


def parse_scoring(meta: dict) -> dict:
    """Return {gold, judge, kind, clean}. ``clean`` False => dump raw block.

    kind is one of 'mcq' | 'judge' | 'unknown'.
    """
    if not isinstance(meta, dict):
        return {"gold": None, "judge": None, "kind": "unknown", "clean": False}

    # MCQ scorer (mmlu-pro / supergpqa).
    if "reference_letter" in meta:
        return {
            "gold": meta.get("reference_letter"),
            "judge": None,
            "kind": "mcq",
            "clean": True,
        }

    # LLM-judge scorer (gaia).
    raw = meta.get("raw_judge_output")
    if raw:
        gold_m = _GOLD_TARGET_RE.search(raw)
        reason_m = _JUDGE_REASONING_RE.search(raw)
        return {
            "gold": gold_m.group(1) if gold_m else None,
            "judge": (reason_m.group(1).strip() if reason_m else raw.strip()),
            "kind": "judge",
            "clean": True,
        }

    # Unknown shape (e.g. {"reason": "no_choice_letter_extracted"}).
    return {"gold": None, "judge": None, "kind": "unknown", "clean": False}


# ---------------------------------------------------------------------------
# Render one record.
# ---------------------------------------------------------------------------
def format_record(rec: dict, question: str | None) -> str:
    parsed = parse_scoring(rec.get("scoring_metadata"))
    is_correct = rec.get("is_correct")
    verdict = (
        "CORRECT"
        if is_correct
        else ("INCORRECT" if is_correct is False else "UNSCORED")
    )

    def _fmt(v, fmt):
        try:
            return fmt.format(v)
        except (ValueError, TypeError):
            return str(v)

    top = "  ·  ".join(
        [
            str(rec.get("record_id", "?")),
            str(rec.get("benchmark", "?")),
            verdict,
            f"score {_fmt(rec.get('score'), '{:.3f}')}",
            f"lat {_fmt(rec.get('latency_seconds'), '{:.1f}')}s",
            f"cost ${_fmt(rec.get('cost_usd'), '{:.4f}')}",
        ]
    )
    parts = [top]

    err = rec.get("error")
    if err:
        parts.append(f"    error: {err}")

    parts.append(_banner("QUESTION"))
    parts.append(_indent(question if question else "(question unavailable)"))

    parts.append(_banner("MODEL ANSWER"))
    parts.append(_indent(str(rec.get("model_answer") or "(empty)")))

    parts.append(_banner("GOLD"))
    gold = parsed["gold"]
    parts.append(
        _indent(
            str(gold)
            if gold not in (None, "")
            else "(gold unavailable — see SCORING below)"
        )
    )

    if parsed["kind"] == "judge" and parsed["judge"]:
        parts.append(_banner("JUDGE"))
        parts.append(_indent(parsed["judge"]))

    if not parsed["clean"]:
        parts.append(_banner("SCORING (raw)"))
        parts.append(
            _indent(json.dumps(rec.get("scoring_metadata"), indent=2, default=str))
        )

    return "\n".join(parts).rstrip() + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--input", required=True, help="Graded *_orchestrator.jsonl file.")
    p.add_argument(
        "--out-dir", default="results/formatted", help="Where the .txt files go."
    )
    p.add_argument(
        "--seed", type=int, default=42, help="Subset seed used at eval time."
    )
    p.add_argument(
        "--only-wrong",
        action="store_true",
        help="Render only incorrect/unscored samples.",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--n", type=int, default=1, help="Format the first N records.")
    g.add_argument("--lines", help="Comma-separated 1-indexed line numbers.")
    g.add_argument("--all", action="store_true", help="Format every record.")
    args = p.parse_args(argv)

    src = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records = [json.loads(l) for l in src.open() if l.strip()]
    if not records:
        print("no records in input")
        return 1

    # Pick indices first (so we only load the dataset once, sized to the file).
    if args.lines:
        idxs = [int(x) - 1 for x in args.lines.split(",") if x.strip()]
    elif args.all:
        idxs = list(range(len(records)))
    else:
        idxs = list(range(min(args.n, len(records))))
    idxs = [i for i in idxs if 0 <= i < len(records)]

    if args.only_wrong:
        idxs = [i for i in idxs if not records[i].get("is_correct")]

    benchmark = _normalize_benchmark(
        records[0].get("benchmark", src.stem.split("_")[0])
    )
    # Load the whole subset so any selected id resolves (the eval-time subset is
    # the first len(records) of seed=42).
    qmap = build_question_map(benchmark, n=len(records), seed=args.seed)

    written = []
    for i in idxs:
        rec = records[i]
        rid = str(rec.get("record_id", i))
        bench = rec.get("benchmark", benchmark)
        fname = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{bench}__{rid}")[:120] + ".txt"
        out = out_dir / fname
        out.write_text(format_record(rec, qmap.get(rid)))
        written.append(out)

    for w in written:
        print(w)
    print(
        f"\nwrote {len(written)} file(s) to {out_dir}/"
        + ("  (dataset unavailable — questions omitted)" if not qmap else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
