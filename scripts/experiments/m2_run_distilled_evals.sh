#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# M2: Run distilled eval configs — resumable, agent-benchmarks-first ordering
#
# Assumes vLLM already running: 2B:8000, 9B:8001, 27B-FP8:8002
#
# Usage:
#   bash m2_run_distilled_evals.sh            # all
#   bash m2_run_distilled_evals.sh 9b         # 9b only
#   bash m2_run_distilled_evals.sh 9b gaia    # 9b + gaia only
# ──────────────────────────────────────────────────────────────────────────────

set -uo pipefail

VENV=".venv/bin/python"
M2_CONFIGS="src/openjarvis/evals/configs/distillation/m2"
BASELINE_CONFIGS="src/openjarvis/evals/configs"
M2_HOME="/scratch/user/jonsaadfalcon/openjarvis-m2"
MODEL_FILTER=${1:-all}
BENCH_FILTER=${2:-all}
FORCE=${FORCE:-0}  # set FORCE=1 to re-run completed configs

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[m2]${NC} $*"; }
ok()   { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
skip() { echo -e "${YELLOW}[SKIP]${NC} $*"; }

declare -A MODEL_PORT=( [2b]=8000 [9b]=8001 [27b]=8002 )

# Agent benchmarks FIRST (where distillation impact is expected)
AGENT_BENCHMARKS="pinchbench gaia liveresearch"
DIRECT_BENCHMARKS="toolcall15 taubench taubench-telecom livecodebench liveresearchbench"
ALL_BENCHMARKS="${AGENT_BENCHMARKS} ${DIRECT_BENCHMARKS}"

check_vllm() {
    for size in 2b 9b 27b; do
        [ "$MODEL_FILTER" != "all" ] && [ "$MODEL_FILTER" != "$size" ] && continue
        local port=${MODEL_PORT[$size]}
        if ! curl -sf "http://localhost:${port}/v1/models" >/dev/null 2>&1; then
            fail "vLLM ${size} not responding on port ${port}"
            return 1
        fi
        ok "vLLM ${size} healthy on port ${port}"
    done
}

# Check if a run already completed (summary.json exists AND has a real accuracy).
# A summary with errors=total_samples (like my earlier broken-routing tests)
# is treated as incomplete and re-run.
is_complete() {
    local summary_path=$1
    [ -f "$summary_path" ] || return 1
    python3 -c "
import json, sys
try:
    d = json.load(open('$summary_path'))
    total = d.get('total_samples', 0)
    errors = d.get('errors', 0)
    scored = d.get('scored_samples', 0)
    # Complete if at least some samples were scored successfully
    sys.exit(0 if scored > 0 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null
}

run_eval() {
    local config_path=$1 label=$2 size=$3 summary_path=$4 use_distilled=${5:-false}

    if [ "$FORCE" != "1" ] && is_complete "$summary_path"; then
        skip "${label}  [already complete]"
        return 0
    fi

    local oj_config="${M2_HOME}/config-baseline-${size}.toml"
    [ "$use_distilled" = "true" ] && oj_config="${M2_HOME}/config-${size}.toml"

    log "Running: ${label}  [$(basename ${oj_config})]"
    env OPENJARVIS_CONFIG="${oj_config}" ${VENV} -m openjarvis.evals run -c "${config_path}" 2>&1
    local rc=$?
    if [ $rc -eq 0 ] && is_complete "$summary_path"; then
        ok "Done: ${label}"
    else
        warn "Failed: ${label} (rc=$rc)"
    fi
}

# Derive the expected summary.json path for a given distilled config
summary_for_distilled() {
    local bench=$1 size=$2
    # Output dir from the config template: results/neurips-2026/distilled/qwen-{size}/{bench}/
    # Summary file pattern: {bench}_Qwen-Qwen3.5-{size}.summary.json
    local model_slug
    if [ "$size" = "27b" ]; then model_slug="Qwen-Qwen3.5-27B-FP8"
    else model_slug="Qwen-Qwen3.5-${size}"; fi
    # Uppercase B for the model slug
    model_slug=$(echo "$model_slug" | sed 's/-\([0-9][0-9]*\)b/-\1B/g')
    # For taubench-telecom, the benchmark name in output is "taubench" not "taubench-telecom"
    local bench_fname=$bench
    [ "$bench" = "taubench-telecom" ] && bench_fname="taubench"
    echo "results/neurips-2026/distilled/qwen-${size}/${bench}/${bench_fname}_${model_slug}.summary.json"
}

summary_for_baseline() {
    local bench=$1 size=$2
    local model_slug
    if [ "$size" = "27b" ]; then model_slug="Qwen-Qwen3.5-27B-FP8"
    else model_slug="Qwen-Qwen3.5-${size}"; fi
    model_slug=$(echo "$model_slug" | sed 's/-\([0-9][0-9]*\)b/-\1B/g')
    local bench_fname=$bench
    [ "$bench" = "taubench-telecom" ] && bench_fname="taubench"
    echo "results/neurips-2026/baselines/qwen-${size}/${bench}/${bench_fname}_${model_slug}.summary.json"
}

log "M2 Distilled Eval Runner  (resumable, agent-first)"
log "Model filter: ${MODEL_FILTER}   Benchmark filter: ${BENCH_FILTER}   FORCE=${FORCE}"

check_vllm || exit 1

start_time=$(date +%s)

# Phase B1: DISTILLED agent benchmarks (highest-priority: PinchBench, GAIA, DeepResearchBench)
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "Phase B1: DISTILLED agent benchmarks (9 runs — the critical data)"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for size in 2b 9b 27b; do
    [ "$MODEL_FILTER" != "all" ] && [ "$MODEL_FILTER" != "$size" ] && continue
    for bench in ${AGENT_BENCHMARKS}; do
        [ "$BENCH_FILTER" != "all" ] && [ "$BENCH_FILTER" != "$bench" ] && continue
        cfg="${M2_CONFIGS}/${bench}-qwen-${size}-distilled.toml"
        sum=$(summary_for_distilled "$bench" "$size")
        [ -f "$cfg" ] && run_eval "$cfg" "DISTILLED ${bench}-qwen-${size}" "${size}" "$sum" true
    done
done

# Phase B2: DISTILLED direct benchmarks (controls — should show minimal delta)
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "Phase B2: DISTILLED direct benchmarks (15 runs — controls)"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for size in 2b 9b 27b; do
    [ "$MODEL_FILTER" != "all" ] && [ "$MODEL_FILTER" != "$size" ] && continue
    for bench in ${DIRECT_BENCHMARKS}; do
        [ "$BENCH_FILTER" != "all" ] && [ "$BENCH_FILTER" != "$bench" ] && continue
        cfg="${M2_CONFIGS}/${bench}-qwen-${size}-distilled.toml"
        sum=$(summary_for_distilled "$bench" "$size")
        [ -f "$cfg" ] && run_eval "$cfg" "DISTILLED ${bench}-qwen-${size}" "${size}" "$sum" true
    done
done

# Phase A: LiveResearchBench baselines (last, since Step 1 baselines exist for other benchmarks)
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "Phase A: LiveResearchBench baselines (3 runs — new benchmark only)"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for size in 2b 9b 27b; do
    [ "$MODEL_FILTER" != "all" ] && [ "$MODEL_FILTER" != "$size" ] && continue
    [ "$BENCH_FILTER" != "all" ] && [ "$BENCH_FILTER" != "liveresearchbench" ] && continue
    cfg="${BASELINE_CONFIGS}/liveresearchbench-qwen-${size}.toml"
    sum=$(summary_for_baseline "liveresearchbench" "$size")
    [ -f "$cfg" ] && run_eval "$cfg" "BASELINE liveresearchbench-qwen-${size}" "${size}" "$sum" false
done

# Phase C: Spot-check 2 baselines against Jon's Step 1 numbers
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "Phase C: Spot-check baselines (TC15-9B, GAIA-9B)"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$MODEL_FILTER" = "all" ] || [ "$MODEL_FILTER" = "9b" ]; then
    for bench in toolcall15 gaia; do
        [ "$BENCH_FILTER" != "all" ] && [ "$BENCH_FILTER" != "$bench" ] && continue
        cfg="${BASELINE_CONFIGS}/${bench}-qwen-9b.toml"
        sum=$(summary_for_baseline "$bench" "9b")
        [ -f "$cfg" ] && run_eval "$cfg" "SPOTCHECK ${bench}-qwen-9b" "9b" "$sum" false
    done
fi

end_time=$(date +%s)
elapsed=$((end_time - start_time))

log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ok "M2 complete in ${elapsed}s ($(( elapsed / 3600 ))h $(( (elapsed % 3600) / 60 ))m)"
log "Distilled results: results/neurips-2026/distilled/"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
