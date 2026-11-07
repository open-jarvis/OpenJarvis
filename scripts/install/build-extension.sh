#!/usr/bin/env bash
# build-extension.sh — build the Rust maturin extension into the venv.
#
# State files under $FRIDAY_AI_HOME/.state/:
#   extension-built   — atomic marker written on success
#   extension-failed  — written on failure with stderr tail
#   extension-build.log — captured stderr/stdout

set -euo pipefail

FRIDAY_AI_HOME="${FRIDAY_AI_HOME:-$HOME/.friday_ai}"
# Self-heal PATH for cargo: install-rust.sh installs to ~/.cargo/bin, but
# its export doesn't propagate to subsequent subprocess invocations.
export PATH="$HOME/.cargo/bin:$PATH"
SRC_DIR="$FRIDAY_AI_HOME/src"
STATE_DIR="$FRIDAY_AI_HOME/.state"
LOG="$STATE_DIR/extension-build.log"
BUILT="$STATE_DIR/extension-built"
FAILED="$STATE_DIR/extension-failed"
MANIFEST="$SRC_DIR/rust/crates/friday_ai-python/Cargo.toml"

mkdir -p "$STATE_DIR"

if [[ ! -f "$MANIFEST" ]]; then
    echo "build-extension.sh: manifest not found at $MANIFEST" > "$FAILED"
    exit 1
fi

cd "$SRC_DIR"
if uv run maturin develop -m "$MANIFEST" >>"$LOG" 2>&1; then
    # Verify the extension actually imports from THIS venv before declaring
    # success. `maturin develop` can report success while installing the .so
    # into a different venv than the one that runs the server, which leaves
    # memory silently broken at runtime (#502). Only the import check below
    # proves the serving venv can load it.
    if ! uv run python -c "import friday_ai_rust" >>"$LOG" 2>&1; then
        rc=$?
        {
            echo "build-extension.sh: maturin succeeded but 'import friday_ai_rust'"
            echo "failed in the serving venv ($SRC_DIR/.venv) — the extension was"
            echo "not installed where the server runs. (exit=$rc)"
            tail -n 50 "$LOG" 2>/dev/null || true
        } > "$FAILED"
        rm -f "$BUILT"
        exit "$rc"
    fi
    tmp="$BUILT.tmp"
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$tmp"
    mv "$tmp" "$BUILT"
    rm -f "$FAILED"
    exit 0
else
    rc=$?
    {
        echo "build-extension.sh failed (exit=$rc)"
        tail -n 50 "$LOG" 2>/dev/null || true
    } > "$FAILED"
    rm -f "$BUILT"
    exit "$rc"
fi
