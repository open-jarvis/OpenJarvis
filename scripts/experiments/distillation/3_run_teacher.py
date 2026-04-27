#!/usr/bin/env python3
"""Step 3/7 — Run the M1 teacher on scored traces to produce plan.json files.

The M1 teacher reads scored traces (from step 1's traces.db, with feedback
seeded by step 2) and writes one plan.json per learning session under
``~/.openjarvis/learning/sessions/<session_id>/plan.json``. Step 4 then
walks those plan.json files to compute consensus edits.

Two ways to invoke the teacher today:

1. CLI (preferred when wired up):

       jarvis learning init   # one-time
       jarvis learning run    # triggers an on-demand session

   ``jarvis learning run`` is currently a CLI stub
   (src/openjarvis/learning/distillation/cli.py) — full orchestration is
   tracked in M1. When that lands, this wrapper will just shell out.

2. Programmatic (works today):

       from openjarvis.learning.distillation.orchestrator import (
           DistillationOrchestrator,
       )
       from openjarvis.learning.distillation.triggers import OnDemandTrigger

       orch = DistillationOrchestrator(home=Path.home() / ".openjarvis", ...)
       orch.run(OnDemandTrigger())

This script defaults to (1) and falls back to printing the (2) sketch if the
CLI is unavailable. Pass --dry-run to preview without invoking anything.

Usage:
    python 3_run_teacher.py                          # invoke jarvis learning run
    python 3_run_teacher.py --autonomy auto          # forward to the CLI
    python 3_run_teacher.py --dry-run                # print plan, don't run
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--autonomy",
        choices=["auto", "tiered", "manual"],
        default="tiered",
        help="Forwarded to `jarvis learning run --autonomy`.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command that would run; do nothing.",
    )
    args = parser.parse_args(argv)

    jarvis = shutil.which("jarvis")
    if jarvis is None:
        print(
            "ERROR: `jarvis` CLI not found on PATH.\n"
            "       Install the openjarvis package (e.g. `pip install -e .`) "
            "and re-run.\n"
            "       Alternatively, invoke DistillationOrchestrator directly "
            "(see this file's docstring).",
            file=sys.stderr,
        )
        return 1

    cmd = [jarvis, "learning", "run", "--autonomy", args.autonomy]
    print("[run]", " ".join(cmd))
    if args.dry_run:
        return 0
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
