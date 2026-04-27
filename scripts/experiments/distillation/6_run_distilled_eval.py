#!/usr/bin/env python3
"""Step 6/7 — Run distilled evals across the matrix.

Thin wrapper around _eval_runner.py with --mode distilled pre-applied. Reads
pipeline_matrix.toml, walks every (application × experiment) cell, and
writes a summary.json + traces.db per cell under matrix.paths.distilled_results_dir.

Reads the distilled TOML configs produced by step 5
(5_apply_consensus_edits.py); pair the outputs against the baseline tree in
step 7 (7_compare_results.py).

Usage (forwarded args go to _eval_runner.py):
    python 6_run_distilled_eval.py
    python 6_run_distilled_eval.py --apps 9b --experiments gaia
    python 6_run_distilled_eval.py --force          # rerun completed cells
    python 6_run_distilled_eval.py --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _eval_runner  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_eval_runner.main(["--mode", "distilled", *sys.argv[1:]]))
