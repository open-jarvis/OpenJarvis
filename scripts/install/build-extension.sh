#!/usr/bin/env bash
# build-extension.sh — build the Rust maturin extension into the venv.
#
# State files under $OPENJARVIS_HOME/.state/:
#   extension-built   — atomic marker written on success
#   extension-failed  — written on failure with stderr tail
#   extension-build.log — captured stderr/stdout

set -euo pipefail

OPENJARVIS_HOME="${OPENJARVIS_HOME:-$HOME/.openjarvis}"
# Self-heal PATH for cargo: install-rust.sh installs to ~/.cargo/bin, but
# its export doesn't propagate to subsequent subprocess invocations.
export PATH="$HOME/.cargo/bin:$PATH"
SRC_DIR="$OPENJARVIS_HOME/src"
STATE_DIR="$OPENJARVIS_HOME/.state"
LOG="$STATE_DIR/extension-build.log"
BUILT="$STATE_DIR/extension-built"
FAILED="$STATE_DIR/extension-failed"
MANIFEST="$SRC_DIR/rust/crates/openjarvis-python/Cargo.toml"

mkdir -p "$STATE_DIR"

if [[ ! -f "$MANIFEST" ]]; then
    echo "build-extension.sh: manifest not found at $MANIFEST" > "$FAILED"
    exit 1
fi

cd "$SRC_DIR"
if uv run maturin develop -m "$MANIFEST" >>"$LOG" 2>&1; then
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
