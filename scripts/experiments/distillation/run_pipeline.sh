#!/usr/bin/env bash
# End-to-end distillation pipeline. Each step is a standalone script — you can
# run any one of them directly. This wrapper just runs them in order.
#
# Steps (numeric prefix = run order):
#   1_gather_consensus_edits.py    → consensus_edits.json
#   2_apply_consensus_edits.py     → distilled TOML configs
#   3_run_evals.py --mode baseline → baseline summaries
#   3_run_evals.py --mode distilled → distilled summaries
#   4_compare_results.py           → comparison.json
#
# Usage:
#   bash run_pipeline.sh                                 # full pipeline
#   bash run_pipeline.sh --skip-baseline                 # baseline already run
#   bash run_pipeline.sh --tallies-file data/m1_vote_tallies.json
#                                                        # use M1 snapshot
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

SKIP_BASELINE=0
SKIP_DISTILLED=0
TALLIES_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-baseline)  SKIP_BASELINE=1; shift ;;
        --skip-distilled) SKIP_DISTILLED=1; shift ;;
        --tallies-file)   TALLIES_FILE="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,/^set/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

echo "═══ 1/5  Gathering consensus edits ═══"
if [[ -n "$TALLIES_FILE" ]]; then
    "$PYTHON" "$HERE/1_gather_consensus_edits.py" --tallies-file "$TALLIES_FILE"
else
    "$PYTHON" "$HERE/1_gather_consensus_edits.py"
fi

echo
echo "═══ 2/5  Applying consensus edits → distilled configs ═══"
"$PYTHON" "$HERE/2_apply_consensus_edits.py"

if [[ "$SKIP_BASELINE" -eq 0 ]]; then
    echo
    echo "═══ 3/5  Running baseline evals ═══"
    "$PYTHON" "$HERE/3_run_evals.py" --mode baseline
else
    echo
    echo "═══ 3/5  Skipping baseline evals (--skip-baseline) ═══"
fi

if [[ "$SKIP_DISTILLED" -eq 0 ]]; then
    echo
    echo "═══ 4/5  Running distilled evals ═══"
    "$PYTHON" "$HERE/3_run_evals.py" --mode distilled
else
    echo
    echo "═══ 4/5  Skipping distilled evals (--skip-distilled) ═══"
fi

echo
echo "═══ 5/5  Comparing results ═══"
"$PYTHON" "$HERE/4_compare_results.py"
