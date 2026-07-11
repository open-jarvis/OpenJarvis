#!/usr/bin/env python
"""Upload orchestrator-SFT JSONL datasets to Braintrust so they're browsable/
filterable in the UI (by area / difficulty / dataset / routed-model / correct).

Datasets land in the SAME Braintrust project as the rollout TRACES (the
``research`` project) so a run's data + traces sit side by side. The target is
resolved from ``OJ_BRAINTRUST_PROJECT_ID`` (default: the research project id);
``--project`` overrides by NAME if you want a different project.

Each record -> a Braintrust dataset row:
  input    = the problem/question
  expected = the FINAL_ANSWER value
  tags     = [gen_model, domain, correct|incorrect, clean|dirty, kept|dropped]
  metadata = domain, area, difficulty, dataset, subsector, task_id, correct,
             clean, kept, reward, gen_model, orchestrator_model, num_tool_calls,
             n_turns, routed_models (real names)
  (the full conversation is kept under metadata.conversation for inspection)

The dataset itself carries run-level metadata (run_label, specific gen_model,
git sha, config knobs, counts, domain distribution) so future experiments are
distinguishable in the UI.

Usage (CLI):
  .venv/bin/python scripts/orchestrator/upload_to_braintrust.py \
      data/orchestrator/sft/qwen_train_0707.jsonl=qwen_train_0707 \
      data/orchestrator/sft/qwen_holdout_0707.jsonl=qwen_holdout_0707

  # name is optional; defaults to {model_short}_{split}_{date}
  .venv/bin/python scripts/orchestrator/upload_to_braintrust.py \
      data/orchestrator/sft/qwen_holdout_0707.jsonl

Programmatic (used by the pipeline auto-upload hook in make_splits.py):
  from upload_to_braintrust import autoupload
  autoupload(["data/orchestrator/sft/qwen_train_0707.jsonl=qwen_train_0707"],
             run_label="...")
"""

import argparse
import json
import logging
import os
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# The `research` project — datasets go here, same place the rollout traces land.
DEFAULT_PROJECT_ID = "c707124e-ce9d-4187-ad11-f49f19f777ad"

_FA = re.compile(r"(?im)FINAL[_\s]?ANSWER\s*:?")


def _ordered_turns(convs, anon_map, orchestrator):
    """Rebuild each turn as role/model/content, in that display order.

    Braintrust sorts object keys alphabetically on write, which would push the
    (very long) `content` to the top. We prefix the keys (`1_role`, `2_model`,
    `3_content`) so they sort into role -> model -> content and the content
    renders last. `model` is the model behind the turn:
      * assistant turns  -> the orchestrator model
      * tool turns       -> the expert model that answered (de-anonymized)
      * system/user      -> None
    """
    out = []
    for c in convs:
        role = c.get("role")
        if role == "tool":
            model = anon_map.get(c.get("name")) or c.get("name")
        elif role == "assistant":
            model = orchestrator
        else:
            model = None
        out.append({"1_role": role, "2_model": model, "3_content": c.get("content")})
    return out


def _dataset_desc(dataset):
    """Fallback dataset blurb for records generated before the field existed."""
    try:
        from openjarvis.learning.intelligence.orchestrator.sft_data.reject_sample import (
            dataset_description,
        )

        return dataset_description(dataset)
    except Exception:
        return ""


def _git_sha():
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path(__file__).resolve().parent,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
            or None
        )
    except Exception:
        return None


def _model_short(rows, path):
    """Short family tag for the default dataset name (qwen / gemma / ...)."""
    stem = Path(path).stem.lower()
    for fam in ("qwen", "gemma"):
        if stem.startswith(fam) or fam in stem:
            return fam
    gm = next((r.get("gen_model") for r in rows if r.get("gen_model")), "") or ""
    gm = gm.lower()
    for fam in ("qwen", "gemma"):
        if fam in gm:
            return fam
    return "orch"


def _split_of(path):
    stem = Path(path).stem.lower()
    for s in (
        "holdout",
        "train",
        "clean",
        "overfit",
        "partial",
        "8k",
        "4k",
        "2k",
        "1k",
    ):
        if s in stem:
            return s
    return "data"


def _default_name(rows, path):
    return f"{_model_short(rows, path)}_{_split_of(path)}_{datetime.now():%m%d}"


def _config_from_env():
    """Config knobs from the run env (set by build_orchestrator_sft.py). Omit unset."""
    cfg = {}
    for env_key, meta_key, cast in [
        ("OJ_CFG_TEMPERATURE", "temperature", float),
        ("OJ_CFG_MAX_TURNS", "max_turns", int),
        (
            "OJ_CFG_ANONYMIZE",
            "anonymize",
            lambda v: v.strip().lower() in ("1", "true", "yes"),
        ),
        (
            "OJ_CFG_REJECTION_ONLY",
            "rejection_only",
            lambda v: v.strip().lower() in ("1", "true", "yes"),
        ),
    ]:
        v = os.getenv(env_key)
        if v not in (None, ""):
            try:
                cfg[meta_key] = cast(v)
            except Exception:
                cfg[meta_key] = v
    return cfg


def _row(rec):
    convs = rec.get("conversations", [])
    user = next((c["content"] for c in convs if c["role"] == "user"), "")
    question = re.sub(r"^\s*Problem:\s*", "", user, count=1).strip()
    asst = [c["content"] for c in convs if c["role"] == "assistant"]
    fa = asst[-1] if asst else ""
    m = list(_FA.finditer(fa))
    model_answer = fa[m[-1].end() :].strip() if m else fa.strip()
    # Gold reference the verifier graded against (stamped at generation time as
    # `gold_answer`). `expected` in Braintrust is the GOLD so the UI shows
    # gold-vs-model; the model's own answer goes to metadata.model_answer.
    gold = rec.get("gold_answer") or None
    has_gold = gold is not None
    am = (rec.get("metrics", {}) or {}).get("anon_map", {}) or {}
    routed = []
    for c in convs:
        if c["role"] == "assistant":
            for t in re.findall(
                r"<tool_call>(\{.*?\})</tool_call>", c["content"], re.DOTALL
            ):
                try:
                    real = am.get(json.loads(t).get("name"))
                    if real:
                        routed.append(real)
                except Exception:
                    pass
    metrics = rec.get("metrics", {}) or {}
    gen_model = rec.get("gen_model")
    domain = rec.get("domain")
    correct = rec.get("correct")
    clean = rec.get("clean")
    kept = rec.get("kept")
    tags = [
        t
        for t in [
            gen_model,
            f"domain:{domain}" if domain else None,
            "correct" if correct else "incorrect",
            "clean" if clean else "dirty",
            "kept" if kept else "dropped",
            "gold" if has_gold else "no_gold",
        ]
        if t
    ]
    return {
        "input": question,
        "expected": gold,
        "tags": tags,
        "metadata": {
            "gold_answer": gold,
            "model_answer": model_answer,
            "has_gold": has_gold,
            "domain": domain,
            "area": rec.get("area"),
            "difficulty": rec.get("difficulty") or None,
            "dataset": rec.get("dataset"),
            "dataset_description": rec.get("dataset_description")
            or _dataset_desc(rec.get("dataset")),
            "subsector": rec.get("subsector"),
            "task_id": rec.get("task_id"),
            "correct": correct,
            "clean": clean,
            "kept": kept,
            "reward": rec.get("reward"),
            "gen_model": gen_model,
            "orchestrator_model": rec.get("orchestrator_model"),
            "num_tool_calls": metrics.get("num_tool_calls"),
            "n_turns": metrics.get("num_turns"),
            "routed_models": routed,
            "conversation": _ordered_turns(convs, am, rec.get("orchestrator_model")),
        },
    }


def _dist(rows, key):
    """{value: count} for a record field, most-common first, None/'' dropped."""
    c = Counter(r.get(key) for r in rows if (r.get(key) or "") != "")
    return {str(k): v for k, v in sorted(c.items(), key=lambda x: -x[1])}


def _routed_dist(rows):
    """Distribution of real (de-anonymized) expert models routed to."""
    c = Counter()
    for r in rows:
        am = (r.get("metrics", {}) or {}).get("anon_map", {}) or {}
        for cc in r.get("conversations", []):
            if cc.get("role") != "assistant":
                continue
            for t in re.findall(
                r"<tool_call>(\{.*?\})</tool_call>", cc.get("content", ""), re.DOTALL
            ):
                try:
                    real = am.get(json.loads(t).get("name"))
                    if real:
                        c[real] += 1
                except Exception:
                    pass
    return {k: v for k, v in sorted(c.items(), key=lambda x: -x[1])}


def _avg(rows, *path):
    vals = []
    for r in rows:
        v = r.get("metrics", {}) or {}
        for p in path:
            v = (v or {}).get(p) if isinstance(v, dict) else None
        if isinstance(v, (int, float)):
            vals.append(v)
    return round(sum(vals) / len(vals), 2) if vals else None


def _dataset_metadata(rows, path, run_label, gen_model):
    n = len(rows)
    meta = {
        "model": _model_short(rows, path),
        "split": _split_of(path),
        "task": "orchestrator-SFT unified-tool routing traces",
        "date": "2026-07-07",
        "run_label": run_label,
        "gen_model": gen_model,
        "git_sha": _git_sha(),
        "source_file": str(path),
        "source_datasets": ["GeneralThought-430K-filtered", "OpenThoughts3-1.2M"],
        "task_mix": "balanced (GeneralThought + OpenThoughts code/math/science)",
        "filter": "correct + clean (rejects file-write echoes, garble, "
        "reasoning-degeneration, truncated tails, essays/markdown dumps)",
        "leak_free": "train/holdout disjoint by task_id",
        "n_total": n,
        "n_correct": sum(1 for r in rows if r.get("correct")),
        "n_clean": sum(1 for r in rows if r.get("clean")),
        "n_kept": sum(1 for r in rows if r.get("kept")),
        "n_with_gold": sum(1 for r in rows if (r.get("gold_answer") or "").strip()),
        "avg_tool_calls": _avg(rows, "num_tool_calls"),
        "avg_turns": _avg(rows, "num_turns"),
        "area_distribution": _dist(rows, "area"),
        "difficulty_distribution": _dist(rows, "difficulty"),
        "dataset_distribution": _dist(rows, "dataset"),
        "routed_model_distribution": _routed_dist(rows),
    }
    cfg = _config_from_env()
    if cfg:
        meta["config"] = cfg
    return {k: v for k, v in meta.items() if v is not None}


def upload_dataset(
    path,
    name=None,
    *,
    project_id=None,
    project=None,
    run_label=None,
    gen_model=None,
    description="",
):
    """Upload one JSONL file as a Braintrust dataset. Returns (name, n_rows, url).

    Target project: ``project`` (name) if given, else ``project_id`` /
    ``OJ_BRAINTRUST_PROJECT_ID`` / the research default.
    """
    import braintrust

    rows = [json.loads(l) for l in open(path) if l.strip()]
    name = name or _default_name(rows, path)
    gen_model = (
        gen_model
        or os.getenv("OJ_GEN_MODEL")
        or next((r.get("gen_model") for r in rows if r.get("gen_model")), None)
    )
    run_label = run_label or os.getenv("OJ_RUN_LABEL") or name

    init_kwargs = {
        "name": name,
        "description": description or None,
        "metadata": _dataset_metadata(rows, path, run_label, gen_model),
    }
    if project:
        init_kwargs["project"] = project
    else:
        init_kwargs["project_id"] = project_id or os.getenv(
            "OJ_BRAINTRUST_PROJECT_ID", DEFAULT_PROJECT_ID
        )

    ds = braintrust.init_dataset(**init_kwargs)
    for r in rows:
        ds.insert(**_row(r))
    ds.flush()
    summ = ds.summarize()
    url = getattr(summ, "dataset_url", None) or (
        project or init_kwargs.get("project_id")
    )
    return name, len(rows), url


def autoupload(specs, *, run_label=None, gen_model=None, description=""):
    """No-op-safe wrapper for pipeline hooks. Honors OJ_BRAINTRUST_AUTOUPLOAD
    (default ON) and never raises: any failure (missing key/pkg, network) is
    logged and swallowed so the data pipeline is never broken by telemetry."""
    if os.getenv("OJ_BRAINTRUST_AUTOUPLOAD", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
        "",
    ):
        logger.info("[braintrust] autoupload disabled (OJ_BRAINTRUST_AUTOUPLOAD)")
        return
    if not os.getenv("BRAINTRUST_API_KEY"):
        logger.info("[braintrust] autoupload skipped — BRAINTRUST_API_KEY unset")
        return
    try:
        import braintrust  # noqa: F401
    except Exception:
        logger.info("[braintrust] autoupload skipped — braintrust not installed")
        return
    for spec in specs:
        path, _, name = spec.partition("=")
        try:
            nm, n, url = upload_dataset(
                path,
                name or None,
                run_label=run_label,
                gen_model=gen_model,
                description=description,
            )
            logger.info("[braintrust] uploaded %s: %d rows -> %s", nm, n, url)
            print(f"[braintrust] uploaded {nm}: {n} rows -> {url}")
        except Exception as exc:
            logger.warning(
                "[braintrust] autoupload FAILED for %s (%s) — continuing", path, exc
            )
            print(
                f"[braintrust] autoupload FAILED for {path} ({exc}) — pipeline unaffected"
            )


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser()
    p.add_argument(
        "--project",
        default=None,
        help="Target project by NAME (overrides OJ_BRAINTRUST_PROJECT_ID).",
    )
    p.add_argument(
        "--project-id",
        default=None,
        help="Target project by id (default: OJ_BRAINTRUST_PROJECT_ID or research).",
    )
    p.add_argument("--run-label", default=None)
    p.add_argument("--gen-model", default=None, help="Specific gen model id override.")
    p.add_argument("--description", default="")
    p.add_argument("specs", nargs="+", help="path.jsonl[=dataset_name]")
    args = p.parse_args()
    for spec in args.specs:
        path, _, name = spec.partition("=")
        nm, n, url = upload_dataset(
            path,
            name or None,
            project_id=args.project_id,
            project=args.project,
            run_label=args.run_label,
            gen_model=args.gen_model,
            description=args.description,
        )
        print(f"[braintrust] {nm}: {n} rows -> {url}")


if __name__ == "__main__":
    raise SystemExit(main())
