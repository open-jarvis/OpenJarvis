#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Run distillation ablation experiments
#
# Prerequisites:
#   - Ollama running with qwen3.5:{2b,9b,27b}
#   - ANTHROPIC_API_KEY set (for Opus teacher)
#   - OPENAI_API_KEY set (for GPT-5.4 teacher)
#   - GOOGLE_API_KEY set (for Gemini teacher)
#   - For Qwen-397B teacher: vLLM serving on port 8010 with 8×H100
#   - Traces seeded with feedback (run A1 blocker first)
#   - jarvis learning init already run
#
# Usage:
#   bash scripts/experiments/run_distillation_experiments.sh               # Run all
#   bash scripts/experiments/run_distillation_experiments.sh exp1a         # Run Phase 1a only
#   bash scripts/experiments/run_distillation_experiments.sh exp1a opus    # Single config
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

CONFIGS_DIR="src/openjarvis/evals/configs/distillation"
RESULTS_DIR="results/neurips-2026/agent-optimization/distillation"
EXPERIMENT=${1:-all}
FILTER=${2:-}

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[distill]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $*"; }
fail() { echo -e "${RED}[ FAIL ]${NC} $*"; }

# ── Preflight checks ────────────────────────────────────────────────────────
check_prereqs() {
    log "Preflight checks..."

    # Check API keys
    if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
        warn "ANTHROPIC_API_KEY not set — Opus teacher experiments will fail"
    fi
    if [ -z "${OPENAI_API_KEY:-}" ]; then
        warn "OPENAI_API_KEY not set — GPT-5.4 teacher experiments will fail"
    fi
    if [ -z "${GOOGLE_API_KEY:-}" ]; then
        warn "GOOGLE_API_KEY not set — Gemini teacher experiments will fail"
    fi

    # Check Ollama
    if ! ollama list &>/dev/null; then
        fail "Ollama not running. Start it first."
        exit 1
    fi

    # Check student models
    for model in qwen3.5:2b qwen3.5:9b qwen3.5:27b; do
        if ! ollama list 2>/dev/null | grep -q "$model"; then
            warn "Model $model not found in Ollama. Pull with: ollama pull $model"
        fi
    done

    # Check distillation init
    if [ ! -d "$HOME/.openjarvis/learning" ]; then
        log "Running jarvis learning init..."
        uv run jarvis learning init
    fi

    ok "Preflight complete"
}

# ── Run a single distillation session ────────────────────────────────────────
run_session() {
    local config_file=$1
    local experiment_name
    experiment_name=$(basename "$(dirname "$config_file")")
    local config_name
    config_name=$(basename "${config_file%.toml}")
    local output_dir="${RESULTS_DIR}/${experiment_name}/${config_name}"

    # Skip if already completed
    if [ -f "${output_dir}/session/session.json" ]; then
        ok "SKIP ${experiment_name}/${config_name} (already done)"
        return 0
    fi

    log "──────────────────────────────────────────────────────"
    log "Experiment: ${experiment_name}/${config_name}"
    log "Config:     ${config_file}"
    log "Output:     ${output_dir}"
    log "──────────────────────────────────────────────────────"

    mkdir -p "${output_dir}"

    # Extract metadata from config
    local teacher_model
    teacher_model=$(grep 'teacher_model' "$config_file" | head -1 | sed 's/.*= *"\(.*\)"/\1/')
    local student_model
    student_model=$(grep 'default_model' "$config_file" | head -1 | sed 's/.*= *"\(.*\)"/\1/')
    local benchmark
    benchmark=$(grep '^benchmark ' "$config_file" | head -1 | sed 's/.*= *"\(.*\)"/\1/')
    local data_config
    data_config=$(grep 'data_config' "$config_file" | head -1 | sed 's/.*= *"\(.*\)"/\1/')
    local iterative
    iterative=$(grep 'iterative_sessions' "$config_file" | head -1 | sed 's/.*= *//')

    log "Teacher: ${teacher_model}"
    log "Student: ${student_model}"
    log "Data:    ${data_config:-C2}"
    log "Iter:    ${iterative:-1}"

    # ── Step 1: Seed traces based on data config ─────────────────────────
    # (In a full implementation, this would filter/prepare the TraceStore
    #  based on C1/C2/C3. For now we use whatever traces exist.)

    # ── Step 2: Run distillation session ─────────────────────────────────
    local n_sessions=${iterative:-1}
    local session_num=1
    local prev_session_id=""

    while [ "$session_num" -le "$n_sessions" ]; do
        log "Session ${session_num}/${n_sessions}..."

        local session_output="${output_dir}/session_${session_num}"
        mkdir -p "${session_output}"

        # Run the distillation session via Python
        # (jarvis learning run doesn't support all config params yet,
        #  so we call the orchestrator directly)
        uv run python << PYEOF > "${session_output}/run.log" 2>&1 || true
import json, os, shutil, sys
from pathlib import Path

from openjarvis.engine.cloud import CloudEngine
from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend
from openjarvis.traces.store import TraceStore
from openjarvis.learning.distillation.checkpoint.store import CheckpointStore
from openjarvis.learning.distillation.models import AutonomyMode
from openjarvis.learning.distillation.orchestrator import DistillationOrchestrator
from openjarvis.learning.distillation.storage.session_store import SessionStore
from openjarvis.learning.distillation.student_runner import (
    VLLMStudentRunner,
    build_benchmark_samples_from_traces,
)
from openjarvis.learning.distillation.triggers import OnDemandTrigger
from openjarvis.learning.optimize.feedback.judge import TraceJudge

home = Path(os.environ.get("OPENJARVIS_HOME", str(Path.home() / ".openjarvis")))

# Read config params
teacher_model = "${teacher_model}"
student_model = "${student_model}"
autonomy = "auto"
max_cost = float("$(grep 'max_cost_per_session_usd' "$config_file" | head -1 | sed 's/.*= *//')")
max_tools = int("$(grep 'max_tool_calls_per_diagnosis' "$config_file" | head -1 | sed 's/.*= *//')")

# Real student runner via vLLM
vllm_host = os.environ.get("VLLM_HOST", "http://localhost:8001")
student_runner = VLLMStudentRunner(
    host=vllm_host,
    model=student_model,
)

# Real judge via cloud LLM
cloud_engine = CloudEngine()
judge_backend = JarvisDirectBackend(engine_key="cloud")
judge = TraceJudge(backend=judge_backend, model="gpt-5-mini-2025-08-07")

# Build benchmark samples from existing traces
trace_store = TraceStore(home / "traces.db")
benchmark_samples = build_benchmark_samples_from_traces(trace_store, limit=50)

orch = DistillationOrchestrator(
    teacher_engine=cloud_engine,
    teacher_model=teacher_model,
    trace_store=trace_store,
    benchmark_samples=benchmark_samples,
    student_runner=student_runner,
    judge=judge,
    session_store=SessionStore(home / "learning" / "learning.db"),
    checkpoint_store=CheckpointStore(home),
    openjarvis_home=home,
    autonomy_mode=AutonomyMode.AUTO,
    scorer=None,
    min_traces=10,
    max_cost_usd=max_cost,
    max_tool_calls=max_tools,
)
session = orch.run(OnDemandTrigger())

# Save results
result = {
    "session_id": session.id,
    "status": session.status.value,
    "cost_usd": session.teacher_cost_usd,
    "edits_total": len(session.edit_outcomes),
    "edits_applied": len([o for o in session.edit_outcomes if o.status == "applied"]),
    "edits_rejected": len([o for o in session.edit_outcomes if o.status == "rejected_by_gate"]),
    "error": session.error,
}
Path("${session_output}/result.json").write_text(json.dumps(result, indent=2))

# Copy session artifacts
sd = home / "learning" / "sessions" / session.id
if sd.exists():
    shutil.copytree(sd, Path("${session_output}/artifacts"), dirs_exist_ok=True)

print(json.dumps(result, indent=2))
PYEOF

        # Check result
        if [ -f "${session_output}/result.json" ]; then
            local status
            status=$(python3 -c "import json; print(json.load(open('${session_output}/result.json'))['status'])")
            local cost
            cost=$(python3 -c "import json; print(f\"\${json.load(open('${session_output}/result.json'))['cost_usd']:.4f}\")")
            local applied
            applied=$(python3 -c "import json; print(json.load(open('${session_output}/result.json'))['edits_applied'])")

            if [ "$status" = "completed" ]; then
                ok "Session ${session_num}: status=${status}, cost=\$${cost}, applied=${applied}"
            else
                warn "Session ${session_num}: status=${status}, cost=\$${cost}"
            fi
        else
            fail "Session ${session_num}: no result.json (check ${session_output}/run.log)"
        fi

        session_num=$((session_num + 1))
    done

    ok "Done: ${experiment_name}/${config_name}"
}

# ── Run experiment group ─────────────────────────────────────────────────────
run_experiment() {
    local exp_dir=$1
    local exp_name
    exp_name=$(basename "$exp_dir")

    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "EXPERIMENT GROUP: ${exp_name}"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    local count=0
    local total
    total=$(ls "${exp_dir}"/*.toml 2>/dev/null | wc -l)

    for config in "${exp_dir}"/*.toml; do
        [ -f "$config" ] || continue

        # Apply filter if specified
        if [ -n "${FILTER}" ] && ! echo "$config" | grep -q "${FILTER}"; then
            continue
        fi

        count=$((count + 1))
        log "[${count}/${total}] $(basename "$config")"
        run_session "$config"
    done

    ok "Experiment group ${exp_name}: ${count} configs processed"
}

# ── Main ─────────────────────────────────────────────────────────────────────
main() {
    check_prereqs

    log "Starting distillation experiments"
    log "Experiment filter: ${EXPERIMENT}"
    log "Config filter: ${FILTER:-none}"

    local start_time
    start_time=$(date +%s)

    if [ "$EXPERIMENT" = "all" ]; then
        # Run in priority order
        for exp in exp1a-teacher exp1b-budget exp1c-student \
                   exp2a-gate exp2b-autonomy \
                   exp3a-iterative exp3b-transfer; do
            if [ -d "${CONFIGS_DIR}/${exp}" ]; then
                run_experiment "${CONFIGS_DIR}/${exp}"
            fi
        done
    elif [ -d "${CONFIGS_DIR}/${EXPERIMENT}" ]; then
        run_experiment "${CONFIGS_DIR}/${EXPERIMENT}"
    else
        fail "Unknown experiment: ${EXPERIMENT}"
        echo "Available: exp1a-teacher exp1b-budget exp1c-student exp2a-gate exp2b-autonomy exp3a-iterative exp3b-transfer"
        exit 1
    fi

    local end_time
    end_time=$(date +%s)
    local elapsed=$((end_time - start_time))

    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ok "All experiments complete in ${elapsed}s"
    log "Results in: ${RESULTS_DIR}/"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

main "$@"
