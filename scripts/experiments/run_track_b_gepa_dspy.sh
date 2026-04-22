#!/usr/bin/env bash
# =============================================================================
# Track B: GEPA/DSPy Agent Optimization
# NeurIPS 2026 — Agent Optimization Experiments
#
# Runs GEPA and DSPy BootstrapFewShot across:
#   Models:     qwen-9b, qwen-27b, qwen-35b
#   Benchmarks: toolcall15, pinchbench, taubench
#
# Usage:
#   bash scripts/experiments/run_track_b_gepa_dspy.sh
#   bash scripts/experiments/run_track_b_gepa_dspy.sh --model qwen-9b --benchmark pinchbench
#   bash scripts/experiments/run_track_b_gepa_dspy.sh --optimizer gepa
#   bash scripts/experiments/run_track_b_gepa_dspy.sh --optimizer dspy
#
# Expected runtime: ~2-4 hours per GEPA run, ~1-2 hours per DSPy run
# Total wall-clock: ~12-18 hours (parallelized across GPUs)
# Estimated API cost: ~$90 GEPA + ~$90 DSPy = ~$180 total
#
# =============================================================================
# vLLM Serving Commands (run these BEFORE this script on the GPU node)
# =============================================================================
#
# GPU 0 — Qwen-9B (1x GPU):
#   CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen2.5-7B-Instruct \
#       --model Qwen/Qwen2.5-7B-Instruct \
#       --served-model-name qwen-9b \
#       --port 8001 --host 0.0.0.0 \
#       --max-model-len 32768 --gpu-memory-utilization 0.9 &
#
# GPU 1 — Qwen-27B (1-2x GPU):
#   CUDA_VISIBLE_DEVICES=1,2 vllm serve Qwen/Qwen2.5-32B-Instruct \
#       --model Qwen/Qwen2.5-32B-Instruct \
#       --served-model-name qwen-27b \
#       --port 8002 --host 0.0.0.0 \
#       --tensor-parallel-size 2 \
#       --max-model-len 32768 --gpu-memory-utilization 0.9 &
#
# GPU 3 — Qwen-35B (1-2x GPU):
#   CUDA_VISIBLE_DEVICES=3,4 vllm serve Qwen/Qwen2.5-72B-Instruct \
#       --model Qwen/Qwen2.5-72B-Instruct \
#       --served-model-name qwen-35b \
#       --port 8003 --host 0.0.0.0 \
#       --tensor-parallel-size 2 \
#       --max-model-len 32768 --gpu-memory-utilization 0.9 &
#
# Wait for all servers to be healthy:
#   sleep 60 && curl -s http://localhost:8001/health && \
#               curl -s http://localhost:8002/health && \
#               curl -s http://localhost:8003/health
#
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RESULTS_BASE="${REPO_ROOT}/results/neurips-2026/agent-optimization"
LOG_DIR="${REPO_ROOT}/results/neurips-2026/logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

ALL_MODELS=(qwen-9b qwen-27b qwen-35b)
ALL_BENCHMARKS=(toolcall15 pinchbench taubench)
ALL_OPTIMIZERS=(gepa dspy)

# Override defaults with CLI flags
FILTER_MODEL=""
FILTER_BENCHMARK=""
FILTER_OPTIMIZER=""

# GEPA settings
GEPA_TRIALS=20
GEPA_MAX_SAMPLES=50
GEPA_OPTIMIZER_MODEL="claude-sonnet-4-6"

# DSPy settings
DSPY_OPTIMIZER="BootstrapFewShotWithRandomSearch"
DSPY_TEACHER_LM="claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Parse CLI flags
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)
            FILTER_MODEL="$2"; shift 2 ;;
        --benchmark)
            FILTER_BENCHMARK="$2"; shift 2 ;;
        --optimizer)
            FILTER_OPTIMIZER="$2"; shift 2 ;;
        --gepa-trials)
            GEPA_TRIALS="$2"; shift 2 ;;
        --gepa-max-samples)
            GEPA_MAX_SAMPLES="$2"; shift 2 ;;
        --dspy-optimizer)
            DSPY_OPTIMIZER="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,30p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        *)
            echo "Unknown flag: $1"; exit 1 ;;
    esac
done

# Apply filters
if [[ -n "$FILTER_MODEL" ]]; then
    ALL_MODELS=("$FILTER_MODEL")
fi
if [[ -n "$FILTER_BENCHMARK" ]]; then
    ALL_BENCHMARKS=("$FILTER_BENCHMARK")
fi
if [[ -n "$FILTER_OPTIMIZER" ]]; then
    ALL_OPTIMIZERS=("$FILTER_OPTIMIZER")
fi

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/track_b_${TIMESTAMP}.log"

log() {
    local level="$1"; shift
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

log_info()  { log "INFO " "$@"; }
log_ok()    { log "OK   " "$@"; }
log_warn()  { log "WARN " "$@"; }
log_error() { log "ERROR" "$@"; }

# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------
setup_env() {
    log_info "=== Track B: GEPA/DSPy Optimization ==="
    log_info "Repo: $REPO_ROOT"
    log_info "Log:  $LOG_FILE"
    log_info "Models:     ${ALL_MODELS[*]}"
    log_info "Benchmarks: ${ALL_BENCHMARKS[*]}"
    log_info "Optimizers: ${ALL_OPTIMIZERS[*]}"
    echo ""

    # Check we are in the repo root
    if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
        log_error "pyproject.toml not found — is REPO_ROOT set correctly? ($REPO_ROOT)"
        exit 1
    fi

    # Install/sync dependencies
    log_info "Running uv sync..."
    cd "$REPO_ROOT"
    uv sync --extra dev 2>&1 | tail -5
    log_ok "uv sync complete"

    # Check required API keys
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
        log_error "ANTHROPIC_API_KEY is not set. Required for the optimizer teacher model."
        log_error "  export ANTHROPIC_API_KEY=sk-ant-..."
        exit 1
    fi
    log_ok "ANTHROPIC_API_KEY is set"

    # Optional: OpenAI key (used if teacher_lm is an OpenAI model)
    if [[ -z "${OPENAI_API_KEY:-}" ]]; then
        log_warn "OPENAI_API_KEY not set (only needed if using OpenAI teacher models)"
    fi

    echo ""
    log_info "Model-to-port mapping (vLLM must be pre-started on these ports):"
    log_info "  qwen-9b  -> http://localhost:8001"
    log_info "  qwen-27b -> http://localhost:8002"
    log_info "  qwen-35b -> http://localhost:8003"
    echo ""
}

# ---------------------------------------------------------------------------
# Model port lookup
# ---------------------------------------------------------------------------
model_port() {
    case "$1" in
        qwen-9b)  echo 8001 ;;
        qwen-27b) echo 8002 ;;
        qwen-35b) echo 8003 ;;
        *)
            log_error "Unknown model: $1"
            exit 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Health check: verify the vLLM server for a model is reachable
# ---------------------------------------------------------------------------
check_server_health() {
    local model="$1"
    local port
    port="$(model_port "$model")"
    local url="http://localhost:${port}/health"
    if curl -sf "$url" > /dev/null 2>&1; then
        log_ok "vLLM server for $model is healthy at port $port"
        return 0
    else
        log_error "vLLM server for $model NOT reachable at $url"
        log_error "Start it with the vLLM commands in the script header."
        return 1
    fi
}

# ---------------------------------------------------------------------------
# GEPA optimization for one (model, benchmark) pair
# ---------------------------------------------------------------------------
run_gepa() {
    local model="$1"
    local bench="$2"
    local port
    port="$(model_port "$model")"
    local out_dir="${RESULTS_BASE}/gepa/${model}/${bench}"

    log_info "--- GEPA: $model × $bench ---"
    log_info "  Output dir: $out_dir"
    log_info "  Trials: $GEPA_TRIALS  Max-samples: $GEPA_MAX_SAMPLES"
    mkdir -p "$out_dir"

    # Record start time
    local t0
    t0="$(date +%s)"

    OPENAI_API_BASE="http://localhost:${port}/v1" \
    uv run jarvis optimize run \
        --benchmark "$bench" \
        --model "$model" \
        --optimizer-model "$GEPA_OPTIMIZER_MODEL" \
        --trials "$GEPA_TRIALS" \
        --max-samples "$GEPA_MAX_SAMPLES" \
        --output-dir "$out_dir" \
        2>&1 | tee -a "$LOG_FILE"

    local exit_code=${PIPESTATUS[0]}
    local t1
    t1="$(date +%s)"
    local elapsed=$(( t1 - t0 ))

    if [[ $exit_code -eq 0 ]]; then
        log_ok "GEPA $model/$bench done in ${elapsed}s"
    else
        log_error "GEPA $model/$bench FAILED (exit $exit_code) after ${elapsed}s"
        return $exit_code
    fi
}

# ---------------------------------------------------------------------------
# DSPy optimization for one (model, benchmark) pair
# ---------------------------------------------------------------------------
run_dspy() {
    local model="$1"
    local bench="$2"
    local port
    port="$(model_port "$model")"
    local out_dir="${RESULTS_BASE}/dspy/${model}/${bench}"

    log_info "--- DSPy: $model × $bench ---"
    log_info "  Output dir: $out_dir"
    log_info "  Teleprompter: $DSPY_OPTIMIZER  Teacher: $DSPY_TEACHER_LM"
    mkdir -p "$out_dir"

    local t0
    t0="$(date +%s)"

    OPENAI_API_BASE="http://localhost:${port}/v1" \
    uv run python - <<PYEOF 2>&1 | tee -a "$LOG_FILE"
import sys
from openjarvis.learning.agents.dspy_optimizer import DSPyAgentOptimizer
from openjarvis.core.config import DSPyOptimizerConfig
from openjarvis.traces.store import TraceStore

store = TraceStore()
config = DSPyOptimizerConfig(
    optimizer="${DSPY_OPTIMIZER}",
    teacher_lm="${DSPY_TEACHER_LM}",
    config_dir="${out_dir}",
    benchmark="${bench}",
    agent_filter="${model}",
)
result = DSPyAgentOptimizer(config).optimize(store)
print(f"DSPy result for ${model}/${bench}: {result}")
if result.get("status") not in ("ok", "success", "done"):
    sys.exit(1)
PYEOF

    local exit_code=${PIPESTATUS[0]}
    local t1
    t1="$(date +%s)"
    local elapsed=$(( t1 - t0 ))

    if [[ $exit_code -eq 0 ]]; then
        log_ok "DSPy $model/$bench done in ${elapsed}s"
    else
        log_error "DSPy $model/$bench FAILED (exit $exit_code) after ${elapsed}s"
        return $exit_code
    fi
}

# ---------------------------------------------------------------------------
# Summary: print result file locations
# ---------------------------------------------------------------------------
print_summary() {
    echo ""
    log_info "=== Track B Complete ==="
    log_info "Results written to:"
    for opt in "${ALL_OPTIMIZERS[@]}"; do
        for model in "${ALL_MODELS[@]}"; do
            for bench in "${ALL_BENCHMARKS[@]}"; do
                local out_dir="${RESULTS_BASE}/${opt}/${model}/${bench}"
                if [[ -d "$out_dir" ]]; then
                    log_ok "  $opt/$model/$bench -> $out_dir"
                else
                    log_warn "  $opt/$model/$bench -> MISSING ($out_dir)"
                fi
            done
        done
    done
    log_info "Full log: $LOG_FILE"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    setup_env

    local failed=0

    # Pre-flight: check vLLM servers for all target models
    log_info "Checking vLLM server health..."
    for model in "${ALL_MODELS[@]}"; do
        check_server_health "$model" || failed=$(( failed + 1 ))
    done
    if [[ $failed -gt 0 ]]; then
        log_error "$failed vLLM server(s) not reachable. Start them first (see header)."
        exit 1
    fi
    echo ""

    # Run all requested (optimizer, model, benchmark) combinations
    for opt in "${ALL_OPTIMIZERS[@]}"; do
        log_info "=========================================="
        log_info "Optimizer: $opt"
        log_info "=========================================="
        for model in "${ALL_MODELS[@]}"; do
            for bench in "${ALL_BENCHMARKS[@]}"; do
                case "$opt" in
                    gepa) run_gepa "$model" "$bench" || failed=$(( failed + 1 )) ;;
                    dspy) run_dspy "$model" "$bench" || failed=$(( failed + 1 )) ;;
                    *) log_error "Unknown optimizer: $opt"; failed=$(( failed + 1 )) ;;
                esac
                echo ""
            done
        done
    done

    print_summary

    if [[ $failed -gt 0 ]]; then
        log_error "$failed run(s) failed. Check log for details: $LOG_FILE"
        exit 1
    fi

    log_ok "All Track B runs completed successfully."
}

main "$@"
