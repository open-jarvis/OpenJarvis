#!/usr/bin/env python3
"""Shared eval-runner library used by steps 1 and 6 of the pipeline.

Reads pipeline_matrix.toml as the source of truth for what to run. Works in
two modes — `baseline` and `distilled` — selecting the config dir and
OPENJARVIS_CONFIG override accordingly. Resumable (skips cells whose
summary.json already reports scored_samples > 0; override with --force).
Runs in priority order (lower number first, so agent benchmarks come before
controls). Checks vLLM health for every size in the plan.

Day-to-day you should call the numbered wrappers, not this file:

    python 1_run_baseline_eval.py [--apps ...] [--experiments ...] [--force]
    python 6_run_distilled_eval.py [--apps ...] [--experiments ...] [--force]

Direct invocation also works:

    python _eval_runner.py --mode baseline
    python _eval_runner.py --mode distilled --apps 9b --experiments gaia
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

REPO_ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DEFAULT_MATRIX = HERE / "pipeline_matrix.toml"


# ── Console formatting ──────────────────────────────────────────────────────


def _color(code: str, msg: str) -> str:
    return f"\033[{code}m{msg}\033[0m" if sys.stdout.isatty() else msg


def log(msg: str) -> None:
    print(_color("0;34", "[run]"), msg)


def ok(msg: str) -> None:
    print(_color("0;32", "[ OK ]"), msg)


def warn(msg: str) -> None:
    print(_color("1;33", "[WARN]"), msg)


def fail(msg: str) -> None:
    print(_color("0;31", "[FAIL]"), msg)


def skip(msg: str) -> None:
    print(_color("1;33", "[SKIP]"), msg)


# ── Plan rows ───────────────────────────────────────────────────────────────


@dataclass
class PlanRow:
    app: dict
    exp: dict
    config_path: Path
    summary_path: Path
    label: str
    priority: int


def hf_to_summary_slug(hf_name: str) -> str:
    """Mirror the openjarvis evals naming: 'Qwen/Qwen3.5-9B' → 'Qwen-Qwen3.5-9B'."""
    return hf_name.replace("/", "-")


def expected_summary_path(*, results_root: Path, app: dict, exp: dict) -> Path:
    """Replicate the summary path the evals harness writes."""
    bench_for_filename = exp.get("benchmark_name", exp["name"])
    model_slug = hf_to_summary_slug(app["hf_name"])
    return (
        results_root
        / app["slug"]
        / exp["name"]
        / f"{bench_for_filename}_{model_slug}.summary.json"
    )


def build_plan(
    *,
    matrix: dict,
    mode: str,
    app_filter: set[str] | None,
    exp_filter: set[str] | None,
) -> list[PlanRow]:
    paths = matrix["paths"]
    if mode == "baseline":
        configs_dir = REPO_ROOT / paths["configs_dir"]
        results_root = REPO_ROOT / paths["baseline_results_dir"]
        config_suffix = ""
    elif mode == "distilled":
        configs_dir = REPO_ROOT / paths["distilled_configs_dir"]
        results_root = REPO_ROOT / paths["distilled_results_dir"]
        config_suffix = "-distilled"
    else:
        raise ValueError(f"Unknown mode: {mode!r}")

    plan: list[PlanRow] = []
    for app in matrix["applications"]:
        if (
            app_filter
            and app["size"] not in app_filter
            and app["slug"] not in app_filter
        ):
            continue
        for exp in matrix["experiments"]:
            if exp_filter and exp["name"] not in exp_filter:
                continue
            cfg = configs_dir / f"{exp['name']}-{app['slug']}{config_suffix}.toml"
            sp = expected_summary_path(
                results_root=results_root,
                app=app,
                exp=exp,
            )
            plan.append(
                PlanRow(
                    app=app,
                    exp=exp,
                    config_path=cfg,
                    summary_path=sp,
                    label=f"{mode.upper()} {exp['name']}-{app['slug']}",
                    priority=int(exp.get("priority", 99)),
                )
            )
    plan.sort(key=lambda r: (r.priority, r.app["size"], r.exp["name"]))
    return plan


# ── Health + completeness checks ─────────────────────────────────────────────


def check_vllm(apps: Iterable[dict]) -> bool:
    healthy = True
    for app in apps:
        url = f"http://localhost:{app['vllm_port']}/v1/models"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    ok(f"vLLM {app['size']:>3} healthy on port {app['vllm_port']}")
                    continue
        except (urllib.error.URLError, OSError) as e:
            fail(f"vLLM {app['size']:>3} unreachable on port {app['vllm_port']} ({e})")
            healthy = False
    return healthy


def is_complete(summary_path: Path) -> bool:
    if not summary_path.exists():
        return False
    try:
        d = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return int(d.get("scored_samples", 0)) > 0


# ── Per-row OPENJARVIS_HOME shadowing for TOML-resident overrides ────────────


def _render_tool_descriptions_toml(descs: dict[str, str]) -> str:
    """Match the tiny single-line parser in tools/description_loader.py."""
    lines: list[str] = []
    for tool, desc in descs.items():
        single_line = " ".join(str(desc).split())
        lines.append(f"[{tool}]")
        lines.append(f'description = "{single_line}"')
        lines.append("")
    return "\n".join(lines)


def _prepare_override_home(row: PlanRow) -> Path | None:
    """Materialize a temp ``OPENJARVIS_HOME`` for a row's TOML overrides.

    Reads ``[[benchmarks]].overrides`` from the row's config and writes
    ``agents/<name>/system_prompt.md``, ``agents/<name>/few_shot.json``, and
    ``tools/descriptions.toml`` into a fresh tempdir so the eval subprocess
    sees those overrides and nothing from the user's real ``~/.openjarvis``.

    Returns the tempdir path, or ``None`` when the config has no overrides
    (caller leaves env alone). Caller is responsible for cleanup.
    """
    try:
        cfg = tomllib.loads(row.config_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    benches = cfg.get("benchmarks") or []
    if not benches:
        return None
    overrides = benches[0].get("overrides") or {}
    if not overrides:
        return None

    home = Path(tempfile.mkdtemp(prefix="oj-eval-home-"))
    for agent_name, prompt in (overrides.get("system_prompt") or {}).items():
        p = home / "agents" / agent_name / "system_prompt.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(prompt), encoding="utf-8")
    for agent_name, fs in (overrides.get("few_shot") or {}).items():
        p = home / "agents" / agent_name / "few_shot.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(fs, indent=2), encoding="utf-8")
    descs = overrides.get("tool_descriptions") or {}
    if descs:
        p = home / "tools" / "descriptions.toml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_render_tool_descriptions_toml(descs), encoding="utf-8")
    return home


# ── Per-row execution ────────────────────────────────────────────────────────


def run_row(*, row: PlanRow, runner_cfg: dict, mode: str, force: bool) -> bool:
    if row.config_path.exists() is False:
        skip(f"{row.label}  [config not found: {row.config_path.name}]")
        return False
    if not force and is_complete(row.summary_path):
        skip(f"{row.label}  [already complete]")
        return True

    # Build the OPENJARVIS_CONFIG override path, if configured
    env = os.environ.copy()
    oj_dir = runner_cfg.get("oj_config_dir", "").strip()
    template = (
        runner_cfg.get(
            "distilled_oj_template" if mode == "distilled" else "baseline_oj_template",
            "",
        )
        or ""
    ).strip()
    if oj_dir and template:
        oj_path = Path(oj_dir) / template.format(size=row.app["size"])
        if oj_path.exists():
            env["OPENJARVIS_CONFIG"] = str(oj_path)
            log(f"OPENJARVIS_CONFIG → {oj_path.name}")
        else:
            warn(
                f"OPENJARVIS_CONFIG override missing: {oj_path} — running without override"
            )

    python_bin = runner_cfg.get("python_bin", ".venv/bin/python")
    if not Path(python_bin).exists():
        python_bin = shutil.which("python") or sys.executable
    evals_module = runner_cfg.get("evals_module", "openjarvis.evals")

    # Distilled rows may carry [[benchmarks]].overrides — materialize a
    # hermetic OPENJARVIS_HOME so the TOML is the only source of truth.
    override_home: Path | None = None
    if mode == "distilled":
        override_home = _prepare_override_home(row)
        if override_home is not None:
            env["OPENJARVIS_HOME"] = str(override_home)
            log(f"OPENJARVIS_HOME → {override_home} (TOML overrides)")

    cmd = [python_bin, "-m", evals_module, "run", "-c", str(row.config_path)]
    log(f"Running {row.label}  [{row.config_path.name}]")
    log(f"  cmd: {' '.join(cmd)}")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, env=env, cwd=str(REPO_ROOT))
    finally:
        if override_home is not None:
            shutil.rmtree(override_home, ignore_errors=True)
    elapsed = time.time() - t0

    if proc.returncode == 0 and is_complete(row.summary_path):
        ok(f"Done: {row.label}  ({elapsed:.0f}s)")
        return True
    warn(f"Failed: {row.label} (rc={proc.returncode}, {elapsed:.0f}s)")
    return False


# ── Entry point ──────────────────────────────────────────────────────────────


def parse_filter(value: str | None) -> set[str] | None:
    if not value or value.lower() == "all":
        return None
    return {part.strip() for part in value.split(",") if part.strip()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    p.add_argument(
        "--mode",
        choices=["baseline", "distilled"],
        default="distilled",
        help="Which config dir + results dir to use (default: distilled)",
    )
    p.add_argument(
        "--apps",
        default="all",
        help="Comma-separated application sizes/slugs to run, or 'all'",
    )
    p.add_argument(
        "--experiments",
        default="all",
        help="Comma-separated experiment names to run, or 'all'",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-run cells whose summary.json reports completion.",
    )
    p.add_argument(
        "--skip-vllm-check",
        action="store_true",
        help="Skip the vLLM health probe (e.g. for dry runs).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan and exit; do not invoke any evals.",
    )
    args = p.parse_args(argv)

    matrix = tomllib.loads(args.matrix.read_text())
    runner_cfg = matrix.get("runner", {})
    plan = build_plan(
        matrix=matrix,
        mode=args.mode,
        app_filter=parse_filter(args.apps),
        exp_filter=parse_filter(args.experiments),
    )
    if not plan:
        warn("Plan is empty (no rows match the filters).")
        return 0

    log(
        f"Mode: {args.mode}  apps={args.apps}  experiments={args.experiments}  "
        f"force={args.force}  rows={len(plan)}"
    )
    print()
    print(f"{'pri':>3}  {'application':12} {'experiment':22} {'config':50}")
    print("-" * 95)
    for row in plan:
        marker = "✓" if is_complete(row.summary_path) else " "
        print(
            f"{row.priority:>3}  {row.app['slug']:12} {row.exp['name']:22} "
            f"{row.config_path.name:50} {marker}"
        )
    print()

    if args.dry_run:
        return 0

    if not args.skip_vllm_check:
        apps_in_plan = {row.app["slug"]: row.app for row in plan}.values()
        if not check_vllm(apps_in_plan):
            fail(
                "vLLM health check failed; aborting. Pass --skip-vllm-check to bypass."
            )
            return 1

    t_start = time.time()
    n_ok = 0
    for row in plan:
        if run_row(row=row, runner_cfg=runner_cfg, mode=args.mode, force=args.force):
            n_ok += 1
    elapsed = time.time() - t_start

    print()
    log(
        f"Done: {n_ok}/{len(plan)} rows complete in {elapsed:.0f}s "
        f"({elapsed / 60:.1f}m)"
    )
    return 0 if n_ok == len(plan) else 2


if __name__ == "__main__":
    sys.exit(main())
