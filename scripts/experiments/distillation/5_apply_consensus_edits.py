#!/usr/bin/env python3
"""Render distilled eval configs from the matrix + a consensus_edits.json.

For every (application, experiment) pair in pipeline_matrix.toml, this writes
one TOML config to the matrix's `distilled_configs_dir`. The distilled config
is a clone of the baseline with the consensus edits applied:

  - set_agent_param(temperature)  → [defaults].temperature
  - set_agent_param(max_turns)    → recorded in the comment (applied at runtime
                                    via OPENJARVIS_CONFIG; see _eval_runner.py)
  - remove_tool_from_agent        → drop from [[benchmarks]].tools
  - add_tool_to_agent             → append to [[benchmarks]].tools

Control experiments (`is_control = true`) are written but with the consensus
edits *not* applied — so direct/coding/reasoning benchmarks act as a
no-distillation control. A consensus edit also has no effect on a non-agent
benchmark.

Inputs:
    --matrix    pipeline_matrix.toml   (default: alongside this script)
    --consensus consensus_edits.json   (default: results/.../consensus/consensus_edits.json)

Outputs:
    Distilled TOMLs written to matrix.paths.distilled_configs_dir/
    A summary printed to stdout (which configs were generated, what changed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# tomllib is stdlib on 3.11+. On older runtimes, install tomli.
try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

REPO_ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DEFAULT_MATRIX = HERE / "pipeline_matrix.toml"
DEFAULT_CONSENSUS = (
    REPO_ROOT
    / "results"
    / "neurips-2026"
    / "distillation-m2"
    / "consensus"
    / "consensus_edits.json"
)


# ── Consensus extraction helpers ─────────────────────────────────────────────


def extract_temperature(consensus: dict) -> float | None:
    for e in consensus.get("scalar_edits", []):
        if e["op"] == "set_agent_param" and e["target"].endswith(".temperature"):
            return float(e["value"])
    return None


def extract_max_turns(consensus: dict) -> int | None:
    for e in consensus.get("scalar_edits", []):
        if e["op"] == "set_agent_param" and e["target"].endswith(".max_turns"):
            return int(e["value"])
    return None


def extract_remove_tools(consensus: dict) -> set[str]:
    return {t["tool_name"] for t in consensus.get("remove_tools", [])}


def extract_add_tools(consensus: dict) -> set[str]:
    return {t["tool_name"] for t in consensus.get("add_tools", [])}


# ── TOML rendering ───────────────────────────────────────────────────────────


def render_config(
    *,
    comment: str,
    meta_name: str,
    description: str,
    temperature: float,
    max_tokens: int,
    judge_model: str,
    judge_engine: str,
    output_dir: str,
    model_name: str,
    model_engine: str,
    num_gpus: int,
    benchmark_name: str,
    backend: str,
    agent: str | None = None,
    tools: list[str] | None = None,
    max_samples: int | None = None,
    extra_benchmark: dict | None = None,
    seed: int = 42,
) -> str:
    lines: list[str] = [f"# {comment}"]
    lines += [
        "[meta]",
        f'name = "{meta_name}"',
        f'description = "{description}"',
        "",
        "[defaults]",
        f"temperature = {temperature}",
        f"max_tokens = {max_tokens}",
        "",
        "[judge]",
        f'model = "{judge_model}"',
        "temperature = 0.0",
    ]
    if judge_engine:
        lines.append(f'engine = "{judge_engine}"')
    lines += [
        "max_tokens = 4096",
        "",
        "[run]",
        "max_workers = 1",
        f'output_dir = "{output_dir}"',
        f"seed = {seed}",
        "",
        "[[models]]",
        f'name = "{model_name}"',
        f'engine = "{model_engine}"',
        f"num_gpus = {num_gpus}",
        "",
        "[[benchmarks]]",
        f'name = "{benchmark_name}"',
        f'backend = "{backend}"',
    ]
    if agent:
        lines.append(f'agent = "{agent}"')
    if max_samples:
        lines.append(f"max_samples = {max_samples}")
    if tools is not None:
        tools_str = ", ".join(f'"{t}"' for t in tools)
        lines.append(f"tools = [{tools_str}]")
    if extra_benchmark:
        for k, v in extra_benchmark.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            else:
                lines.append(f"{k} = {v}")
    lines.append("")
    return "\n".join(lines)


# ── Per-(app, experiment) distilled config ───────────────────────────────────


def make_distilled_config(
    *,
    app: dict,
    exp: dict,
    paths: dict,
    consensus_temp: float | None,
    consensus_max_turns: int | None,
    remove_tools: set[str],
    add_tools: set[str],
) -> tuple[Path, str, list[str]]:
    """Render one distilled TOML and return (path, content, change_log)."""
    bench_name = exp.get("benchmark_name", exp["name"])
    is_agent = bool(exp.get("is_agent", False))
    is_control = bool(exp.get("is_control", False))
    apply_distillation = is_agent and not is_control

    # Temperature: distilled gets consensus value if eligible, else baseline
    temperature = exp["baseline_temp"]
    if apply_distillation and consensus_temp is not None:
        temperature = consensus_temp

    # Tools: drop removed, append added
    tools: list[str] | None = list(exp.get("baseline_tools", [])) or None
    if apply_distillation and tools is not None:
        tools = [t for t in tools if t not in remove_tools]
        for t in add_tools:
            if t not in tools:
                tools.append(t)

    # Build human-readable change log
    changes: list[str] = []
    if apply_distillation:
        if consensus_temp is not None and consensus_temp != exp["baseline_temp"]:
            changes.append(f"temp {exp['baseline_temp']}→{consensus_temp}")
        baseline_tool_set = set(exp.get("baseline_tools", []))
        removed_here = baseline_tool_set & remove_tools
        if removed_here:
            changes.append(f"removed {sorted(removed_here)}")
        added_here = add_tools - baseline_tool_set
        if added_here:
            changes.append(f"added {sorted(added_here)}")
        if consensus_max_turns is not None:
            changes.append(
                f"max_turns→{consensus_max_turns} (via OPENJARVIS_CONFIG; set by run_evals)"
            )
    change_str = (
        "; ".join(changes) if changes else "CONTROL (no consensus edits applied)"
    )

    out_path = (
        REPO_ROOT
        / paths["distilled_configs_dir"]
        / f"{exp['name']}-{app['slug']}-distilled.toml"
    )
    output_dir = f"{paths['distilled_results_dir']}/{app['slug']}/{exp['name']}/"
    content = render_config(
        comment=f"DISTILLED: {exp['name']} × {app['hf_name']} — {change_str}",
        meta_name=f"{exp['name']}-{app['slug']}-distilled",
        description=f"Distilled {exp['name']} on {app['hf_name']}",
        temperature=temperature,
        max_tokens=int(exp["max_tokens"]),
        judge_model=exp["judge_model"],
        judge_engine=exp.get("judge_engine", "cloud"),
        output_dir=output_dir,
        model_name=app["hf_name"],
        model_engine=app["engine"],
        num_gpus=int(app["num_gpus"]),
        benchmark_name=bench_name,
        backend=exp["backend"],
        agent=exp.get("agent"),
        tools=tools,
        max_samples=exp.get("max_samples") or None,
        extra_benchmark=exp.get("extra_benchmark_fields"),
    )
    return out_path, content, changes


# ── Entry point ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    p.add_argument("--consensus", type=Path, default=DEFAULT_CONSENSUS)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching disk.",
    )
    args = p.parse_args(argv)

    if not args.matrix.exists():
        print(f"ERROR: matrix file not found: {args.matrix}", file=sys.stderr)
        return 1
    if not args.consensus.exists():
        print(f"ERROR: consensus file not found: {args.consensus}", file=sys.stderr)
        print("       Run 4_gather_consensus_edits.py first.", file=sys.stderr)
        return 1

    matrix = tomllib.loads(args.matrix.read_text())
    consensus_doc = json.loads(args.consensus.read_text())
    consensus = consensus_doc.get("consensus", consensus_doc)

    paths = matrix["paths"]
    apps = matrix["applications"]
    exps = matrix["experiments"]

    consensus_temp = extract_temperature(consensus)
    consensus_max_turns = extract_max_turns(consensus)
    remove_tools = extract_remove_tools(consensus)
    add_tools = extract_add_tools(consensus)

    print("Consensus edits being applied:")
    print(f"  temperature → {consensus_temp}")
    print(f"  max_turns   → {consensus_max_turns}")
    print(f"  remove_tools → {sorted(remove_tools) or '—'}")
    print(f"  add_tools    → {sorted(add_tools) or '—'}")
    print()

    out_dir = REPO_ROOT / paths["distilled_configs_dir"]
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    n_written = 0
    print(f"{'experiment':22} {'application':12} {'changes':50}")
    print("-" * 90)
    for app in apps:
        for exp in exps:
            out_path, content, changes = make_distilled_config(
                app=app,
                exp=exp,
                paths=paths,
                consensus_temp=consensus_temp,
                consensus_max_turns=consensus_max_turns,
                remove_tools=remove_tools,
                add_tools=add_tools,
            )
            if not args.dry_run:
                out_path.write_text(content)
                n_written += 1
            change_str = "; ".join(changes) if changes else "(control)"
            print(f"{exp['name']:22} {app['slug']:12} {change_str:50}")

    print()
    print(f"Wrote {n_written} configs → {out_dir}/")
    if args.dry_run:
        print("(dry-run: no files written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
