#!/usr/bin/env python3
"""Step 0: Validate the distillation pipeline environment.

Prints every path and env var the pipeline cares about, whether each
exists, and exits non-zero if anything critical is missing. Pure
read-only — never mutates state. Run this before step 1.

    python 0_check_env.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

HERE = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX = HERE / "pipeline_matrix.toml"


def color(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


OK = color("0;32", "[ OK ]")
WARN = color("1;33", "[WARN]")
FAIL = color("0;31", "[FAIL]")
INFO = color("0;34", "[INFO]")


def section(title: str) -> None:
    print()
    print(title)
    print("-" * 72)


def main() -> int:
    if not MATRIX.exists():
        print(f"{FAIL} matrix not found at {MATRIX}", file=sys.stderr)
        return 1

    matrix = tomllib.loads(MATRIX.read_text())
    paths = matrix.get("paths", {})
    runner = matrix.get("runner", {})
    apps = matrix.get("applications", [])

    print("=" * 72)
    print("  Distillation pipeline environment check")
    print("=" * 72)
    print(f"  matrix    : {MATRIX}")
    print(f"  repo root : {REPO_ROOT}")

    critical_failures = 0

    # ── Required env vars ──────────────────────────────────────────────────
    section("Environment variables")
    if os.environ.get("ANTHROPIC_API_KEY"):
        n = len(os.environ["ANTHROPIC_API_KEY"])
        print(f"  {OK} ANTHROPIC_API_KEY   set (len={n}) — used by step 2 judge")
    else:
        print(f"  {FAIL} ANTHROPIC_API_KEY   not set — step 2 will fail")
        critical_failures += 1

    home_override = os.environ.get("OPENJARVIS_HOME")
    if home_override:
        p = Path(home_override)
        marker = OK if p.exists() else WARN
        print(f"  {marker} OPENJARVIS_HOME     {p}  (forces step 2 single-db mode)")
    else:
        print(
            f"  {INFO} OPENJARVIS_HOME     unset — step 2 walks per-cell dbs "
            f"under matrix results dirs"
        )

    # ── Matrix [paths] ─────────────────────────────────────────────────────
    section("Matrix [paths]  (relative to repo root)")
    path_descriptions = [
        ("configs_dir", "step 1 reads baseline TOMLs from"),
        ("distilled_configs_dir", "step 5 writes / step 6 reads distilled TOMLs"),
        ("baseline_results_dir", "step 1 writes summary.json + traces.db"),
        ("distilled_results_dir", "step 6 writes summary.json + traces.db"),
        ("comparison_dir", "step 7 writes comparison.json"),
    ]
    for key, purpose in path_descriptions:
        rel = paths.get(key, "")
        if not rel:
            print(f"  {WARN} {key:24} (unset)")
            continue
        full = (REPO_ROOT / rel).resolve()
        kind = "exists" if full.exists() else "will be created"
        marker = OK if full.exists() else INFO
        print(f"  {marker} {key:24} {full}  ({kind})")
        print(f"           ↳ {purpose}")

    # ── Matrix [runner] ────────────────────────────────────────────────────
    section("Matrix [runner]")
    oj_dir = (runner.get("oj_config_dir") or "").strip()
    if oj_dir:
        full = Path(oj_dir)
        marker = OK if full.exists() else WARN
        kind = (
            "exists"
            if full.exists()
            else "missing — runner will warn and skip override"
        )
        print(f"  {marker} oj_config_dir       {full}  ({kind})")
    else:
        print(f"  {INFO} oj_config_dir       (empty — no OPENJARVIS_CONFIG override)")

    py = runner.get("python_bin", ".venv/bin/python")
    py_path = Path(py) if Path(py).is_absolute() else (REPO_ROOT / py)
    if py_path.exists():
        print(f"  {OK} python_bin          {py_path}")
    else:
        sys_py = shutil.which("python") or sys.executable
        print(
            f"  {WARN} python_bin          {py_path}  (missing — runner will fall "
            f"back to {sys_py})"
        )

    print(
        f"  {INFO} evals_module        {runner.get('evals_module', 'openjarvis.evals')}"
    )

    # ── Learning artifacts (step 3 prereq) ─────────────────────────────────
    section("Learning artifacts  (`jarvis learning init` writes these)")
    learn_root = Path.home() / ".openjarvis" / "learning"
    if learn_root.exists():
        sessions_dir = learn_root / "sessions"
        sessions = list(sessions_dir.glob("*")) if sessions_dir.exists() else []
        plans = list(sessions_dir.glob("*/plan.json")) if sessions_dir.exists() else []
        print(f"  {OK} {learn_root}")
        print(
            f"           ↳ {len(sessions)} session(s), {len(plans)} plan.json file(s)"
        )
    else:
        print(f"  {FAIL} {learn_root} missing — run: jarvis learning init")
        critical_failures += 1

    # ── Discovered traces.db files ─────────────────────────────────────────
    section("Per-cell traces.db files  (what step 2 will judge by default)")
    found: list[Path] = []
    for key in ("baseline_results_dir", "distilled_results_dir"):
        rel = paths.get(key, "")
        if not rel:
            continue
        root = (REPO_ROOT / rel).resolve()
        if root.exists():
            found.extend(sorted(root.rglob("traces.db")))
    if found:
        for p in found:
            try:
                rel_p = p.relative_to(REPO_ROOT)
            except ValueError:
                rel_p = p
            size_kb = p.stat().st_size / 1024
            print(f"  {OK} {rel_p}  ({size_kb:.0f} KB)")
    else:
        fb = Path.home() / ".openjarvis" / "traces.db"
        print(f"  {INFO} no per-cell traces.db yet — step 2 will fall back to {fb}")

    # ── vLLM hosts (best-effort) ───────────────────────────────────────────
    if apps:
        section("vLLM hosts declared in matrix [[applications]]  (not probed here)")
        for app in apps:
            print(
                f"  {INFO} {app.get('size', '?'):>3}  slug={app.get('slug', '?'):14} "
                f"port={app.get('vllm_port', '?')}  hf={app.get('hf_name', '?')}"
            )
        print(
            f"  {INFO} Step 1 / step 6 health-probe each port at run time; "
            f"see _eval_runner.py:check_vllm"
        )

    # ── Summary ────────────────────────────────────────────────────────────
    print()
    if critical_failures:
        print(
            f"{FAIL} {critical_failures} critical problem(s); fix before running step 1."
        )
        return 1
    print(f"{OK} environment looks good. Safe to run step 1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
