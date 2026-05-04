#!/usr/bin/env bash
# jarvis-uninstall.sh — clean removal of OpenJarvis from $HOME.
#
# Removes:
#   ~/.openjarvis/
#   ~/.local/bin/jarvis
#   ~/.local/bin/jarvis-uninstall
#
# Does NOT remove: ollama, uv, or the Rust toolchain.

set -euo pipefail

OPENJARVIS_HOME="${OPENJARVIS_HOME:-$HOME/.openjarvis}"

if [[ -f "$OPENJARVIS_HOME/.state/bg.pid" ]]; then
    pid=$(cat "$OPENJARVIS_HOME/.state/bg.pid" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        echo "Stopping background work (pid=$pid)..."
        kill "$pid" 2>/dev/null || true
    fi
fi

if command -v ollama >/dev/null 2>&1; then
    ollama stop >/dev/null 2>&1 || true
fi

if [[ -d "$OPENJARVIS_HOME" ]]; then
    rm -rf "$OPENJARVIS_HOME"
    echo "Removed $OPENJARVIS_HOME"
fi

for f in "$HOME/.local/bin/jarvis" "$HOME/.local/bin/jarvis-uninstall"; do
    if [[ -L "$f" ]] || [[ -f "$f" ]]; then
        rm -f "$f"
        echo "Removed $f"
    fi
done

cat <<EOF

OpenJarvis removed.

Left intact (may be used by other tools):
  - Ollama       (uninstall: brew uninstall ollama  /  rm -f /usr/local/bin/ollama)
  - uv           (uninstall: rm -rf ~/.local/share/uv ~/.cargo/bin/uv)
  - Rust toolchain (uninstall: rustup self uninstall)
EOF
