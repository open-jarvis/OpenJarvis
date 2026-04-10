#!/bin/bash
# Run the full Step 2a optimization experiment matrix.
#
# Prerequisite: vLLM servers running on the expected ports.
#   GPU 0: Qwen-9B on port 8000
#   GPUs 1-2: Qwen-27B on port 8003
#
# Experiment matrix per model:
#   GEPA × {PB, TC15, TB} × {C1, C2, C3}       =  9 runs
#   DSPy MIPROv2 × {PB, TC15, TB} × {C2}        =  3 runs
#   DSPy SIMBA × {PB, TC15, TB} × {C2}          =  3 runs
#   DSPy Bootstrap × {PB, TC15, TB} × {C2}      =  3 runs
#   Skills 4-condition × {PB, TC15, TB}          = 12 runs
#   Total per model:                              = 30 runs
#
# Usage:
#   bash scripts/optimization/run_all.sh [--dry-run] [--phase PHASE]
#   Phases: gepa, dspy, skills, all (default: all)

set -euo pipefail
cd "$(dirname "$0")/../.."

# ---- Config ----
RESULTS_BASE="results/neurips-2026/agent-optimization"
MODELS=("Qwen/Qwen3.5-9B")  # Add Qwen/Qwen3.5-27B-FP8 when ready
BENCHMARKS=("pinchbench" "toolcall15")  # Add "taubench" when TB bug is fixed
GEPA_DATA_CONFIGS=("C2")  # Start with C2, add C1 C3 later
DSPY_METHODS=("simba" "mipro" "bootstrap")

# GEPA params
MAX_METRIC_CALLS=50
POPULATION_SIZE=5
MAX_EVAL_SAMPLES=15
REFLECTION_LM="anthropic/claude-sonnet-4-6"

# DSPy params
NUM_CANDIDATE_PROGRAMS=5
TEACHER_LM="anthropic/claude-sonnet-4-6"

DRY_RUN=false
PHASE="all"
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=true; shift ;;
        --phase) PHASE="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ---- Helper ----
run_or_print() {
    if $DRY_RUN; then
        echo "[DRY RUN] $*"
    else
        echo "$(date '+%H:%M:%S') Running: $*"
        eval "$@"
    fi
}

echo "============================================="
echo "  Step 2a: Agent Optimization Experiment"
echo "  Phase: $PHASE"
echo "============================================="
echo "Models:        ${MODELS[*]}"
echo "Benchmarks:    ${BENCHMARKS[*]}"
echo "GEPA configs:  ${GEPA_DATA_CONFIGS[*]}"
echo "DSPy methods:  ${DSPY_METHODS[*]}"
echo "Dry run:       $DRY_RUN"
echo ""

total_runs=0

# ---- GEPA runs ----
if [[ "$PHASE" == "all" || "$PHASE" == "gepa" ]]; then
    echo "===== GEPA Optimization ====="
    echo "  (Evolutionary prompt evolution with live eval + Claude reflection)"
    for model in "${MODELS[@]}"; do
        model_slug=$(echo "$model" | tr '/' '-' | tr ':' '-')
        for bench in "${BENCHMARKS[@]}"; do
            for dc in "${GEPA_DATA_CONFIGS[@]}"; do
                out_dir="$RESULTS_BASE/gepa/$model_slug/$bench/$dc"
                total_runs=$((total_runs + 1))

                # Skip if already completed
                if [ -f "$out_dir/result.json" ]; then
                    echo "  [SKIP] GEPA $model_slug × $bench × $dc (already done)"
                    continue
                fi

                echo ""
                echo "--- GEPA: $model_slug × $bench × $dc ---"
                run_or_print uv run python scripts/optimization/run_gepa.py \
                    --model "$model" \
                    --benchmark "$bench" \
                    --data-config "$dc" \
                    --engine-key vllm \
                    --max-metric-calls "$MAX_METRIC_CALLS" \
                    --population-size "$POPULATION_SIZE" \
                    --reflection-lm "$REFLECTION_LM" \
                    --max-eval-samples "$MAX_EVAL_SAMPLES" \
                    --output-dir "$out_dir"
            done
        done
    done
fi

# ---- DSPy runs ----
if [[ "$PHASE" == "all" || "$PHASE" == "dspy" ]]; then
    echo ""
    echo "===== DSPy Optimization ====="
    echo "  MIPROv2: Bayesian opt over instructions + few-shot"
    echo "  SIMBA: Stochastic mini-batch + introspective failure analysis"
    echo "  Bootstrap: Teacher-bootstrapped demonstrations"
    for model in "${MODELS[@]}"; do
        model_slug=$(echo "$model" | tr '/' '-' | tr ':' '-')
        for bench in "${BENCHMARKS[@]}"; do
            for method in "${DSPY_METHODS[@]}"; do
                # DSPy runs always use C2 (queries only) — most comparable
                dc="C2"
                out_dir="$RESULTS_BASE/dspy/$method/$model_slug/$bench/$dc"
                total_runs=$((total_runs + 1))

                # Skip if already completed
                if [ -f "$out_dir/result.json" ]; then
                    echo "  [SKIP] DSPy $method $model_slug × $bench × $dc (already done)"
                    continue
                fi

                echo ""
                echo "--- DSPy $method: $model_slug × $bench × $dc ---"
                run_or_print uv run python scripts/optimization/run_dspy.py \
                    --model "$model" \
                    --benchmark "$bench" \
                    --data-config "$dc" \
                    --method "$method" \
                    --engine-key vllm \
                    --max-eval-samples "$MAX_EVAL_SAMPLES" \
                    --max-bootstrapped-demos 4 \
                    --max-labeled-demos 4 \
                    --num-candidate-programs "$NUM_CANDIDATE_PROGRAMS" \
                    --teacher-lm "$TEACHER_LM" \
                    --output-dir "$out_dir"
            done
        done
    done
fi

# ---- Skills runs ----
if [[ "$PHASE" == "all" || "$PHASE" == "skills" ]]; then
    echo ""
    echo "===== Skills Optimization ====="
    for model in "${MODELS[@]}"; do
        for bench in "${BENCHMARKS[@]}"; do
            total_runs=$((total_runs + 1))
            echo ""
            echo "--- Skills: $model × $bench ---"
            run_or_print uv run jarvis bench skills \
                -c all \
                -m "$model" \
                -e vllm \
                -n "$MAX_EVAL_SAMPLES" \
                -o "$RESULTS_BASE/skills/$(echo $model | tr '/' '-')/$bench/"
        done
    done
fi

echo ""
echo "============================================="
echo "  Total runs: $total_runs"
echo "============================================="
