#!/usr/bin/env python3
"""Step 1/7 — Run baseline evals across the matrix.

Thin wrapper around _eval_runner.py with --mode baseline pre-applied. Reads
pipeline_matrix.toml, walks every (application × experiment) cell, and
writes a summary.json + traces.db per cell under matrix.paths.baseline_results_dir.

The traces.db files produced here are the inputs to step 2 (seed feedback)
and ultimately step 3 (run M1 teacher).

Usage (forwarded args go to _eval_runner.py):
    python 1_run_baseline_eval.py
    python 1_run_baseline_eval.py --apps 9b --experiments gaia
    python 1_run_baseline_eval.py --force          # rerun completed cells
    python 1_run_baseline_eval.py --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _eval_runner  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_eval_runner.main(["--mode", "baseline", *sys.argv[1:]]))
