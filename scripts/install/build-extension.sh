#!/usr/bin/env bash
# build-extension.sh — build the Rust maturin extension into the venv.
#
# State files under $OPENJARVIS_HOME/.state/:
#   extension-built   — atomic marker written on success
#   extension-failed  — written on failure with stderr tail
#   extension-build.log — captured stderr/stdout

set -euo pipefail

OPENJARVIS_HOME="${OPENJARVIS_HOME:-$HOME/.openjarvis}"
# Self-heal PATH for cargo and uv: install-rust.sh installs to ~/.cargo/bin
# and install.sh installs uv to ~/.local/bin, but neither export propagates
# to subsequent subprocess invocations.
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
SRC_DIR="$OPENJARVIS_HOME/src"
# The venv the runtime actually uses. jarvis-wrapper.sh execs
# "$OPENJARVIS_HOME/.venv/bin/jarvis", so this — not a venv that `uv run`
# happens to resolve from the cwd — is where the extension has to land.
VENV_DIR="$OPENJARVIS_HOME/.venv"
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

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "build-extension.sh: runtime venv not found at $VENV_DIR" > "$FAILED"
    exit 1
fi

cd "$SRC_DIR"
# `uv run` resolves its environment from the cwd, which creates and targets
# $SRC_DIR/.venv — a venv nothing runs from. Point maturin at the runtime
# venv explicitly instead. `--uv` is required because that venv is a uv venv
# with no pip; without it maturin fails with "Failed to find pip".
if VIRTUAL_ENV="$VENV_DIR" uvx maturin develop --uv -m "$MANIFEST" >>"$LOG" 2>&1; then
    # Verify the extension actually imports from THIS venv before declaring
    # success. `maturin develop` can report success while installing the .so
    # into a different venv than the one that runs the server, which leaves
    # memory silently broken at runtime (#502). Only the import check below
    # proves the serving venv can load it.
    if ! "$VENV_DIR/bin/python" -c "import openjarvis_rust" >>"$LOG" 2>&1; then
        rc=$?
        {
            echo "build-extension.sh: maturin succeeded but 'import openjarvis_rust'"
            echo "failed in the serving venv ($VENV_DIR) — the extension was"
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
