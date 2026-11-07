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

# The venv the `jarvis` wrapper actually runs from. The installer creates it
# at $OPENJARVIS_HOME/.venv; a contributor checkout (`uv sync`) has it at
# $SRC_DIR/.venv instead. Plain `uv run` inside $SRC_DIR always picks the
# latter (creating it if missing), so on an installer layout the extension
# used to land in a venv nothing serves from while the import check below
# passed against that same wrong venv (#502 reopened).
VENV_DIR="${OPENJARVIS_VENV:-$OPENJARVIS_HOME/.venv}"
if [[ ! -d "$VENV_DIR" ]]; then
    VENV_DIR="$SRC_DIR/.venv"
fi
export VIRTUAL_ENV="$VENV_DIR"

mkdir -p "$STATE_DIR"

if [[ ! -f "$MANIFEST" ]]; then
    echo "build-extension.sh: manifest not found at $MANIFEST" > "$FAILED"
    exit 1
fi

cd "$SRC_DIR"
# `uv tool run` keeps maturin out of the serving venv; `maturin develop`
# installs into $VIRTUAL_ENV, and `--uv` lets it do so in a venv that has
# no pip (uv-created venvs do not ship one).
if uv tool run maturin develop --uv -m "$MANIFEST" >>"$LOG" 2>&1; then
    # Verify the extension actually imports from THIS venv before declaring
    # success. `maturin develop` can report success while installing the .so
    # into a different venv than the one that runs the server, which leaves
    # memory silently broken at runtime (#502). Only the import check below
    # proves the serving venv can load it.
    if ! uv run --active --no-sync python -c "import openjarvis_rust" >>"$LOG" 2>&1; then
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
