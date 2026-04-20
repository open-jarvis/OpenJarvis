#!/usr/bin/env python3
"""M3: Empirical hill-climbing with an LLM proposer.

Replaces M1's open-loop "aggregate consensus across sessions" with a closed
loop:

    For each target (student, benchmark, agent):
        for round in 1..N:
            edit = teacher.propose_one(history_with_measured_deltas)
            score_new = eval_subsample(apply(edit))
            if score_new > current_score: accept

Every proposal is empirically verified before the next is proposed, and the
teacher sees measured deltas (not just traces) in its context.

Usage:
    python scripts/experiments/m3_hill_climb.py \\
        --student 9b --benchmark liveresearch \\
        --rounds 4 --k-subsample 8 --k-final 30
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import CloudEngine


# ═══════════════════════════════════════════════════════════════════════════
# Config & constants
# ═══════════════════════════════════════════════════════════════════════════

STUDENT = {
    "2b": {"name": "Qwen/Qwen3.5-2B", "port": 8000, "gpu": 4},
    "9b": {"name": "Qwen/Qwen3.5-9B", "port": 8001, "gpu": 5},
    "27b": {"name": "Qwen/Qwen3.5-27B-FP8", "port": 8002, "gpu": 6},
}

# Per-benchmark defaults (backend, baseline config)
BENCHMARK = {
    "liveresearch": {
        "backend": "jarvis-agent",
        "agent": "monitor_operative",
        "baseline_temp": 0.6,
        "baseline_max_tokens": 16384,
        "baseline_max_turns": 10,
        "baseline_tools": ["web_search", "file_read", "file_write",
                           "code_interpreter", "think"],
        "max_samples_final": 50,  # final eval
        "judge": "gpt-5-mini-2025-08-07",
    },
    "gaia": {
        "backend": "jarvis-agent",
        "agent": "monitor_operative",
        "baseline_temp": 0.6,
        "baseline_max_tokens": 8192,
        "baseline_max_turns": 10,
        "baseline_tools": ["think", "calculator", "code_interpreter",
                           "web_search", "file_read"],
        "max_samples_final": 50,
        "judge": "gpt-5-mini-2025-08-07",
    },
    "pinchbench": {
        "backend": "jarvis-agent",
        "agent": "native_openhands",
        "baseline_temp": 0.6,
        "baseline_max_tokens": 8192,
        "baseline_max_turns": 10,
        "baseline_tools": ["think", "file_read", "file_write", "web_search",
                           "shell_exec", "code_interpreter", "browser_navigate",
                           "image_generate", "calculator", "http_request",
                           "pdf_extract"],
        "max_samples_final": 23,
        "judge": "claude-opus-4-5",
    },
}

AVAILABLE_TOOLS = [
    "think", "file_read", "file_write", "web_search", "shell_exec",
    "code_interpreter", "browser_navigate", "image_generate", "calculator",
    "http_request", "pdf_extract", "pdf_reader", "list_directory",
]


# ═══════════════════════════════════════════════════════════════════════════
# Proposer (LLM)
# ═══════════════════════════════════════════════════════════════════════════


PROPOSER_SYSTEM = """\
You are optimizing an OpenJarvis agent configuration for maximum accuracy on \
a benchmark. You propose ONE config edit per round. After each proposal, the \
edit is applied and the benchmark is run on a subsample; you then see the \
measured score delta and decide the next edit.

Your job is to find the config that maximizes measured accuracy.

EDIT GRAMMAR — return JSON with "op" and the parameter fields at top level:

{"op": "<op_name>", <param_fields>, "rationale": "<one sentence>"}

Valid ops and their parameter fields:

1. set_temperature: "value" (float, 0.0..1.0)
2. set_max_turns:   "value" (int, 1..100)
3. set_max_tokens:  "value" (int, 512..32768)
4. add_tool:        "tool_name" (string; must be in AVAILABLE_TOOLS, not already active)
5. remove_tool:     "tool_name" (string; must be in current tools)
6. noop:            (no params; propose only if you believe no further edit will help)

CONCRETE EXAMPLES:
  {"op": "set_temperature", "value": 0.3, "rationale": "Reduce loop risk."}
  {"op": "set_max_turns", "value": 20, "rationale": "More turns for research tasks."}
  {"op": "add_tool", "tool_name": "pdf_extract", "rationale": "Tasks require PDF reading."}
  {"op": "remove_tool", "tool_name": "shell_exec", "rationale": "Tool is broken in this env."}
  {"op": "noop", "rationale": "Current config seems optimal."}

EXPLORATION BIAS:
  The config space has 5 distinct axes: temperature, max_turns, max_tokens,
  tool additions (add_tool), tool removals (remove_tool). Before proposing a
  second edit on an axis you've already tried, consider whether an untried
  axis might reveal a larger gain. Tool-list edits (add/remove) often matter
  more than numeric hyperparameters on benchmarks where the agent uses tools.

Return ONLY the JSON object, no preamble, no code fences."""


def build_user_prompt(
    *, benchmark: str, student: str, agent: str,
    baseline_score: float, current_score: float, current_config: dict,
    edit_history: list[dict], available_tools: list[str],
    sample_queries: list[str],
) -> str:
    hist_lines = []
    for i, e in enumerate(edit_history, 1):
        delta = e["score_after"] - e["score_before"]
        status = "ACCEPTED" if e["accepted"] else "REJECTED"
        hist_lines.append(
            f"  Round {i}: {json.dumps(e['edit'])} "
            f"→ score {e['score_before']:.1f}% → {e['score_after']:.1f}% "
            f"(Δ {delta:+.1f}, {status})"
        )
    hist = "\n".join(hist_lines) if hist_lines else "  (no edits yet — baseline is the starting point)"

    samples = "\n".join(f"  - {q[:150]}..." for q in sample_queries[:3])

    unused_tools = [t for t in available_tools if t not in current_config["tools"]]

    return f"""\
TARGET:
  student: {student}  (vLLM-served Qwen3.5)
  benchmark: {benchmark}
  agent: {agent}  (uses OpenAI-format structured tool calls)

CURRENT CONFIG:
  temperature = {current_config['temperature']}
  max_turns   = {current_config['max_turns']}
  max_tokens  = {current_config['max_tokens']}
  tools       = {current_config['tools']}

TOOLS NOT CURRENTLY ACTIVE (available to add):
  {unused_tools}

BASELINE (unedited) SCORE: {baseline_score:.1f}%
CURRENT BEST SCORE:        {current_score:.1f}%

EDIT HISTORY (with measured deltas):
{hist}

SAMPLE TASKS FROM THIS BENCHMARK:
{samples}

Propose ONE edit that you predict will improve the measured accuracy. Consider \
the edit history — do not repeat proposals that were rejected. If you believe \
further edits will not help, propose noop.

Return JSON only."""


def call_proposer(
    engine: CloudEngine, system: str, user: str, model: str = "claude-sonnet-4-6"
) -> dict:
    resp = engine.generate(
        messages=[
            Message(role=Role.SYSTEM, content=system),
            Message(role=Role.USER, content=user),
        ],
        model=model, max_tokens=600, temperature=0.3,
    )
    content = (resp.get("content") or "").strip()
    # Be forgiving about code fences
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```\s*$", "", content)
    # Find the JSON object
    m = re.search(r"\{[\s\S]*\}", content)
    if not m:
        raise ValueError(f"No JSON object found in proposer output: {content[:200]}")
    return json.loads(m.group(0))


# ═══════════════════════════════════════════════════════════════════════════
# Edit application & evaluation
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class Config:
    temperature: float
    max_turns: int
    max_tokens: int
    tools: list[str]


def apply_edit(cfg: Config, edit: dict) -> Config:
    """Apply an edit. Tolerant of both flat and nested (params) forms."""
    op = edit["op"]
    # Merge top-level edit fields with params for flat-or-nested tolerance
    p = {**edit.get("params", {}), **{k: v for k, v in edit.items()
                                      if k not in ("op", "params", "rationale")}}
    new = Config(
        temperature=cfg.temperature, max_turns=cfg.max_turns,
        max_tokens=cfg.max_tokens, tools=list(cfg.tools),
    )
    if op == "noop":
        return new
    if op == "set_temperature":
        new.temperature = float(p["value"])
    elif op == "set_max_turns":
        new.max_turns = int(p["value"])
    elif op == "set_max_tokens":
        new.max_tokens = int(p["value"])
    elif op == "add_tool":
        tool = p["tool_name"]
        if tool not in new.tools:
            new.tools.append(tool)
    elif op == "remove_tool":
        tool = p["tool_name"]
        new.tools = [t for t in new.tools if t != tool]
    else:
        raise ValueError(f"unknown edit op: {op}")
    return new


def write_eval_toml(
    *, bench: str, bench_spec: dict, student: dict, cfg: Config,
    k_samples: int, output_dir: Path,
) -> Path:
    agent_line = f'agent = "{bench_spec["agent"]}"' if bench_spec.get("agent") else ""
    tools_str = "[" + ", ".join(f'"{t}"' for t in cfg.tools) + "]"
    toml = f"""\
[meta]
name = "m3-{bench}-{student['name'].replace('/', '-')}"
description = "M3 hill-climb round"

[defaults]
temperature = {cfg.temperature}
max_tokens = {cfg.max_tokens}

[judge]
model = "{bench_spec['judge']}"
temperature = 0.0
max_tokens = 4096
engine = "cloud"

[run]
max_workers = 1
output_dir = "{output_dir}"
seed = 42

[[models]]
name = "{student['name']}"
engine = "vllm"
num_gpus = 1

[[benchmarks]]
name = "{bench}"
backend = "{bench_spec['backend']}"
{agent_line}
max_samples = {k_samples}
tools = {tools_str}
"""
    path = output_dir / "eval.toml"
    output_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(toml)
    return path


def write_openjarvis_config(home: Path, port: int, max_turns: int) -> Path:
    p = home / "global-config.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"""\
[agent]
max_turns = {max_turns}

[engine]
default = "vllm"

[engine.vllm]
host = "http://localhost:{port}"
""")
    return p


def run_eval(eval_toml: Path, oj_config: Path) -> tuple[float, int, int]:
    """Run one eval. Returns (accuracy_pct, scored, total)."""
    env = {**os.environ, "OPENJARVIS_CONFIG": str(oj_config)}
    result = subprocess.run(
        [".venv/bin/python", "-m", "openjarvis.evals", "run", "-c", str(eval_toml)],
        capture_output=True, text=True, env=env, timeout=7200,
    )
    # Find the summary.json
    out_dir = eval_toml.parent
    sums = list(out_dir.glob("**/*.summary.json"))
    if not sums:
        print(f"[m3] WARNING: no summary.json in {out_dir}")
        print(f"[m3] stderr tail: {result.stderr[-500:]}")
        return 0.0, 0, 0
    d = json.loads(sums[0].read_text())
    acc = d.get("accuracy", 0.0)
    acc_pct = acc * 100 if acc <= 1.0 else acc
    return acc_pct, d.get("scored_samples", 0), d.get("total_samples", 0)


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark sample loader (for proposer context)
# ═══════════════════════════════════════════════════════════════════════════


def load_sample_queries(bench: str, n: int = 3) -> list[str]:
    try:
        if bench == "liveresearch":
            from openjarvis.evals.datasets.liveresearch import LiveResearchBenchDataset
            ds = LiveResearchBenchDataset()
            ds.load(max_samples=n)
        elif bench == "pinchbench":
            from openjarvis.evals.datasets.pinchbench import PinchBenchDataset
            ds = PinchBenchDataset()
        elif bench == "gaia":
            from openjarvis.evals.datasets.gaia import GAIADataset
            ds = GAIADataset()
            if hasattr(ds, "load"):
                ds.load(max_samples=n)
        else:
            return []
        return [r.problem for r in list(ds.iter_records())[:n]]
    except Exception as e:
        print(f"[m3] WARNING: could not load samples for {bench}: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# Main hill-climb loop
# ═══════════════════════════════════════════════════════════════════════════


def hill_climb(args) -> dict:
    bench_spec = BENCHMARK[args.benchmark]
    student = STUDENT[args.student]

    # State dir (resumable)
    base_dir = Path(args.out_dir) / f"{args.student}-{args.benchmark}"
    base_dir.mkdir(parents=True, exist_ok=True)
    state_path = base_dir / "state.json"

    # Load or initialize state
    if state_path.exists() and not args.fresh:
        state = json.loads(state_path.read_text())
        print(f"[m3] Resumed state from round {len(state['history'])}/{args.rounds}")
    else:
        baseline_cfg_dict = {
            "temperature": bench_spec["baseline_temp"],
            "max_turns": bench_spec["baseline_max_turns"],
            "max_tokens": bench_spec["baseline_max_tokens"],
            "tools": list(bench_spec["baseline_tools"]),
        }
        # ALWAYS measure the baseline today first (unless user provides --trust-baseline).
        # This prevents anchoring to an unreproducible Step 1 number.
        # We measure at k=k_final so the final delta is like-for-like.
        if args.trust_baseline and args.baseline_score is not None:
            measured_baseline = args.baseline_score
            measured_baseline_k = None
            print(f"[m3] Trusting provided baseline score: {measured_baseline:.1f}% "
                  f"(--trust-baseline set)")
        else:
            print(f"[m3] Measuring today's baseline with k={args.k_final} "
                  f"(matches k_final for clean like-for-like delta)...")
            bl_dir = base_dir / "baseline_measure"
            bl_toml = write_eval_toml(
                bench=args.benchmark, bench_spec=bench_spec, student=student,
                cfg=Config(**baseline_cfg_dict),
                k_samples=args.k_final, output_dir=bl_dir,
            )
            bl_oj = write_openjarvis_config(bl_dir, student["port"], baseline_cfg_dict["max_turns"])
            t0 = time.monotonic()
            measured_baseline, bl_scored, bl_total = run_eval(bl_toml, bl_oj)
            measured_baseline_k = bl_scored
            print(f"[m3] Measured baseline: {measured_baseline:.1f}% "
                  f"({bl_scored}/{bl_total}) in {(time.monotonic() - t0)/60:.1f} min")
            if args.baseline_score is not None:
                print(f"[m3] (reference: --baseline-score was {args.baseline_score:.1f}%, "
                      f"drift = {measured_baseline - args.baseline_score:+.1f})")

        state = {
            "args": vars(args),
            "benchmark": args.benchmark,
            "student": student["name"],
            "agent": bench_spec["agent"],
            "baseline_config": baseline_cfg_dict,
            "baseline_score": measured_baseline,
            "baseline_score_reference": args.baseline_score,
            "current_config": dict(baseline_cfg_dict),
            "current_score": measured_baseline,
            "history": [],
        }

    # Save state helper
    def save():
        state_path.write_text(json.dumps(state, indent=2, default=str))

    save()

    # Sample queries for proposer context
    sample_queries = load_sample_queries(args.benchmark)

    engine = CloudEngine()

    # Hill-climb rounds
    for round_num in range(len(state["history"]) + 1, args.rounds + 1):
        print(f"\n{'═' * 70}")
        print(f"[m3] Round {round_num}/{args.rounds}")
        print(f"[m3] current_score = {state['current_score']:.1f}%")
        print(f"[m3] current_config = {state['current_config']}")

        # Propose
        user_prompt = build_user_prompt(
            benchmark=args.benchmark, student=student["name"],
            agent=bench_spec["agent"],
            baseline_score=state["baseline_score"],
            current_score=state["current_score"],
            current_config=state["current_config"],
            edit_history=state["history"],
            available_tools=AVAILABLE_TOOLS,
            sample_queries=sample_queries,
        )
        try:
            edit = call_proposer(engine, PROPOSER_SYSTEM, user_prompt,
                                 model=args.proposer_model)
        except Exception as e:
            print(f"[m3] Proposer failed: {e}. Ending hill-climb.")
            break

        print(f"[m3] Proposed: {json.dumps(edit)}")

        if edit.get("op") == "noop":
            print(f"[m3] Teacher proposed noop; stopping.")
            break

        # Apply and evaluate subsample
        try:
            candidate = apply_edit(Config(**state["current_config"]), edit)
        except Exception as e:
            print(f"[m3] apply_edit failed: {e}. Recording as malformed edit.")
            # Record as a rejected malformed edit so teacher won't repeat
            state["history"].append({
                "round": round_num, "edit": edit,
                "config_after": None,
                "score_before": state["current_score"],
                "score_after": state["current_score"],  # no change
                "scored": 0, "total": 0, "elapsed_seconds": 0,
                "accepted": False,
                "error": f"malformed_edit: {e}",
            })
            save()
            continue

        round_dir = base_dir / f"round_{round_num}"
        eval_toml = write_eval_toml(
            bench=args.benchmark, bench_spec=bench_spec, student=student,
            cfg=candidate, k_samples=args.k_subsample,
            output_dir=round_dir,
        )
        oj_cfg = write_openjarvis_config(round_dir, student["port"], candidate.max_turns)

        print(f"[m3] Running k={args.k_subsample} subsample eval...")
        t0 = time.monotonic()
        acc, scored, total = run_eval(eval_toml, oj_cfg)
        elapsed = time.monotonic() - t0
        print(f"[m3] Subsample score: {acc:.1f}% ({scored}/{total}) in {elapsed/60:.1f} min")

        score_before = state["current_score"]
        delta = acc - score_before
        accepted = delta > args.accept_threshold

        # Record history
        state["history"].append({
            "round": round_num, "edit": edit,
            "config_after": asdict(candidate),
            "score_before": score_before, "score_after": acc,
            "scored": scored, "total": total, "elapsed_seconds": elapsed,
            "accepted": accepted,
        })

        if accepted:
            state["current_config"] = asdict(candidate)
            state["current_score"] = acc
            print(f"[m3] ACCEPTED (Δ={delta:+.1f})")
        else:
            print(f"[m3] REJECTED (Δ={delta:+.1f} ≤ {args.accept_threshold})")

        save()

    # Final eval with current config
    print(f"\n{'═' * 70}")
    print(f"[m3] Final eval with best config: {state['current_config']}")
    final_dir = base_dir / "final"
    final_cfg = Config(**state["current_config"])
    eval_toml = write_eval_toml(
        bench=args.benchmark, bench_spec=bench_spec, student=student,
        cfg=final_cfg, k_samples=args.k_final,
        output_dir=final_dir,
    )
    oj_cfg = write_openjarvis_config(final_dir, student["port"], final_cfg.max_turns)

    t0 = time.monotonic()
    final_acc, final_scored, final_total = run_eval(eval_toml, oj_cfg)
    elapsed = time.monotonic() - t0

    state["final_score"] = final_acc
    state["final_scored"] = final_scored
    state["final_total"] = final_total
    state["final_elapsed_seconds"] = elapsed
    save()

    print(f"\n{'═' * 70}")
    print(f"[m3] DONE")
    print(f"[m3] baseline = {state['baseline_score']:.1f}%")
    print(f"[m3] final    = {final_acc:.1f}% ({final_scored}/{final_total}) in {elapsed/60:.1f} min")
    print(f"[m3] Δ vs baseline = {final_acc - state['baseline_score']:+.1f}")
    print(f"[m3] state: {state_path}")

    return state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--student", required=True, choices=list(STUDENT))
    ap.add_argument("--benchmark", required=True, choices=list(BENCHMARK))
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--k-subsample", type=int, default=8)
    ap.add_argument("--k-final", type=int, default=30)
    ap.add_argument("--baseline-score", type=float, default=None,
                    help="Optional reference baseline (shown alongside measured). "
                         "Hill-climb always measures today's baseline unless --trust-baseline.")
    ap.add_argument("--trust-baseline", action="store_true",
                    help="Skip baseline re-measurement, trust --baseline-score.")
    ap.add_argument("--accept-threshold", type=float, default=0.0,
                    help="Accept edit if score Δ > this (default: 0)")
    ap.add_argument("--proposer-model", default="claude-sonnet-4-6")
    ap.add_argument("--out-dir", default="results/neurips-2026/distillation-m3")
    ap.add_argument("--fresh", action="store_true",
                    help="Overwrite existing state and start fresh")
    args = ap.parse_args()

    result = hill_climb(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
