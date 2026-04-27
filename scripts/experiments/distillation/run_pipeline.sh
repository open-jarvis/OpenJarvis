#!/usr/bin/env bash
# End-to-end distillation pipeline. Each numbered script is standalone — you
# can run any one of them directly. This wrapper just runs them in order.
#
# Steps (numeric prefix = run order):
#   1_run_baseline_eval.py          → results/<run>/{summary.json, traces.db}
#   2_seed_feedback.py              → updates traces.db with judge feedback
#   3_run_teacher.py                → ~/.openjarvis/learning/sessions/*/plan.json
#   4_gather_consensus_edits.py     → consensus_edits.json
#   5_apply_consensus_edits.py      → distilled TOML configs
#   6_run_distilled_eval.py         → results/<run>/{summary.json, traces.db}
#   7_compare_results.py            → comparison.json
#
# Prerequisite (one-time):
#   jarvis learning init
#
# Usage:
#   bash run_pipeline.sh                                  # full pipeline
#   bash run_pipeline.sh --skip-baseline                  # baseline already run
#   bash run_pipeline.sh --skip-baseline --skip-teacher   # plan.json files exist
#   bash run_pipeline.sh --skip-distilled                 # stop before distilled eval
#   bash run_pipeline.sh --tallies-file data/m1_vote_tallies.json
#                                                         # use M1 vote snapshot
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

SKIP_BASELINE=0
SKIP_FEEDBACK=0
SKIP_TEACHER=0
SKIP_DISTILLED=0
TALLIES_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-baseline)  SKIP_BASELINE=1; shift ;;
        --skip-feedback)  SKIP_FEEDBACK=1; shift ;;
        --skip-teacher)   SKIP_TEACHER=1; shift ;;
        --skip-distilled) SKIP_DISTILLED=1; shift ;;
        --tallies-file)   TALLIES_FILE="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,/^set/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

step() { echo; echo "═══ $1 ═══"; }

if [[ "$SKIP_BASELINE" -eq 0 ]]; then
    step "1/7  Running baseline evals"
    "$PYTHON" "$HERE/1_run_baseline_eval.py"
else
    step "1/7  Skipping baseline evals (--skip-baseline)"
fi

if [[ "$SKIP_FEEDBACK" -eq 0 ]]; then
    step "2/7  Seeding feedback on baseline traces"
    "$PYTHON" "$HERE/2_seed_feedback.py"
else
    step "2/7  Skipping feedback seeding (--skip-feedback)"
fi

if [[ "$SKIP_TEACHER" -eq 0 ]]; then
    step "3/7  Running M1 teacher (producing plan.json files)"
    "$PYTHON" "$HERE/3_run_teacher.py"
else
    step "3/7  Skipping M1 teacher (--skip-teacher)"
fi

step "4/7  Gathering consensus edits"
if [[ -n "$TALLIES_FILE" ]]; then
    "$PYTHON" "$HERE/4_gather_consensus_edits.py" --tallies-file "$TALLIES_FILE"
else
    "$PYTHON" "$HERE/4_gather_consensus_edits.py"
fi

step "5/7  Applying consensus edits → distilled configs"
"$PYTHON" "$HERE/5_apply_consensus_edits.py"

if [[ "$SKIP_DISTILLED" -eq 0 ]]; then
    step "6/7  Running distilled evals"
    "$PYTHON" "$HERE/6_run_distilled_eval.py"
else
    step "6/7  Skipping distilled evals (--skip-distilled)"
fi

step "7/7  Comparing baseline vs distilled"
"$PYTHON" "$HERE/7_compare_results.py"
