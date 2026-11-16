#!/usr/bin/env bash
# pull-model.sh — pull an Ollama model with state-file lifecycle.
#
# Usage: pull-model.sh <model-id>
#
# State files written under $OPENJARVIS_HOME/.state/models/v1/ use a
# lowercase SHA-256 key so long IDs and path-special characters work across
# filesystems, including case-insensitive ones. The first line of each state
# marker holds the original model ID:
#   <encoded-model>.downloading  — created on start
#   <encoded-model>.ready        — on success (atomic rename)
#   <encoded-model>.failed       — on failure after retries
#   <encoded-model>.log          — captured stderr

set -euo pipefail

MODEL="${1:-}"
if [[ -z "$MODEL" ]]; then
    echo "usage: pull-model.sh <model-id>" >&2
    exit 2
fi

OPENJARVIS_HOME="${OPENJARVIS_HOME:-$HOME/.openjarvis}"
STATE_DIR="$OPENJARVIS_HOME/.state/models"
MODEL_STATE_DIR="$STATE_DIR/v1"
mkdir -p "$MODEL_STATE_DIR"

if command -v sha256sum >/dev/null 2>&1; then
    MODEL_KEY="$(printf '%s' "$MODEL" | sha256sum | cut -d ' ' -f 1)"
else
    MODEL_KEY="$(printf '%s' "$MODEL" | shasum -a 256 | cut -d ' ' -f 1)"
fi
DOWNLOADING="$MODEL_STATE_DIR/${MODEL_KEY}.downloading"
READY="$MODEL_STATE_DIR/${MODEL_KEY}.ready"
FAILED="$MODEL_STATE_DIR/${MODEL_KEY}.failed"
LOG="$MODEL_STATE_DIR/${MODEL_KEY}.log"

# Cleanup any prior state for this model.
rm -f "$READY" "$FAILED"
printf '%s\n' "$MODEL" > "$DOWNLOADING"

MAX_RETRIES=3
attempt=0
last_exit=0

while [[ $attempt -lt $MAX_RETRIES ]]; do
    attempt=$((attempt + 1))
    if ollama pull "$MODEL" >>"$LOG" 2>&1; then
        # Atomic rename: write to .tmp then mv.
        tmp="$MODEL_STATE_DIR/${MODEL_KEY}.ready.tmp"
        { printf '%s\n' "$MODEL"; date -u +"%Y-%m-%dT%H:%M:%SZ"; } > "$tmp"
        mv "$tmp" "$READY"
        rm -f "$DOWNLOADING"
        exit 0
    else
        last_exit=$?
    fi
done

# All retries exhausted.
{
    printf '%s\n' "$MODEL"
    echo "pull-model.sh: $MODEL failed after $MAX_RETRIES attempts (exit=$last_exit)"
    tail -n 50 "$LOG" 2>/dev/null || true
} > "$FAILED"
rm -f "$DOWNLOADING"
exit "$last_exit"
