#!/usr/bin/env bash
# bg-orchestrator.sh — detached parent of all background install work.
#
# Spawned by install.sh via `nohup ... & disown`.  Runs the Rust
# toolchain install + extension build sequentially, and in parallel
# kicks off model pulls for each model id passed as an argument.
#
# Usage: bg-orchestrator.sh <model-id> [<model-id> ...]

set -euo pipefail

OPENJARVIS_HOME="${OPENJARVIS_HOME:-$HOME/.openjarvis}"
STATE_DIR="$OPENJARVIS_HOME/.state"
SCRIPTS_DIR="$OPENJARVIS_HOME/.scripts"
PID_FILE="$STATE_DIR/bg.pid"
LOG="$STATE_DIR/bg-orchestrator.log"

mkdir -p "$STATE_DIR"
echo "$$" > "$PID_FILE"

cleanup() {
    rm -f "$PID_FILE"
}
trap cleanup EXIT

echo "[$(date -u +%FT%TZ)] bg-orchestrator started, pid=$$" >> "$LOG"

# Sequential: install rust, then build extension.
(
    "$SCRIPTS_DIR/install-rust.sh" >> "$LOG" 2>&1 \
        && "$SCRIPTS_DIR/build-extension.sh" >> "$LOG" 2>&1
) &
RUST_PID=$!

# Parallel: each model pull.
MODEL_PIDS=()
for model in "$@"; do
    "$SCRIPTS_DIR/pull-model.sh" "$model" >> "$LOG" 2>&1 &
    MODEL_PIDS+=($!)
done

# Wait for all subprocesses; non-zero exits don't fail the orchestrator
# because per-task state files already record success/failure.
wait "$RUST_PID" || true
for pid in "${MODEL_PIDS[@]}"; do
    wait "$pid" || true
done

echo "[$(date -u +%FT%TZ)] bg-orchestrator done" >> "$LOG"
