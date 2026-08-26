#!/usr/bin/env bash
# jarvis-uninstall.sh — clean removal of OpenJarvis from $HOME.
#
# Removes:
#   ~/.openjarvis/
#   ~/.local/bin/jarvis
#   ~/.local/bin/jarvis-uninstall
#
# Does NOT remove: ollama, uv, or the Rust toolchain.
#
# Safety:
#   - Creates a backup before deletion (unless --no-backup)
#   - Requires confirmation unless --yes is passed
#   - Shows what will be removed before proceeding

set -euo pipefail

OPENJARVIS_HOME="${OPENJARVIS_HOME:-$HOME/.openjarvis}"
BACKUP_DIR="$HOME"
SKIP_CONFIRM=0
SKIP_BACKUP=0

# ---- args ----
for arg in "$@"; do
    case "$arg" in
        --yes|-y) SKIP_CONFIRM=1 ;;
        --no-backup) SKIP_BACKUP=1 ;;
        --help|-h)
            cat <<USAGE
Usage: jarvis-uninstall [OPTIONS]

Options:
  --yes, -y       Skip confirmation prompt
  --no-backup     Skip backup before deletion
  --help, -h      Show this help

Safety:
  A backup of ~/.openjarvis is created before deletion.
  The backup is saved as ~/openjarvis-backup-<timestamp>.tar.gz
USAGE
            exit 0
            ;;
        *)
            echo "Unknown option: $arg (use --help for usage)" >&2
            exit 1
            ;;
    esac
done

# ---- check if directory exists ----
if [[ ! -d "$OPENJARVIS_HOME" ]]; then
    echo "OpenJarvis directory not found: $OPENJARVIS_HOME"
    echo "Nothing to remove."
    exit 0
fi

# ---- show what will be removed ----
echo "OpenJarvis Uninstall"
echo "===================="
echo
echo "Directory to remove: $OPENJARVIS_HOME"
echo
echo "Contents:"
if [[ -f "$OPENJARVIS_HOME/config.toml" ]]; then
    echo "  - config.toml (API keys, settings)"
fi
if [[ -d "$OPENJARVIS_HOME/.venv" ]]; then
    echo "  - .venv/ (Python environment)"
fi
if [[ -d "$OPENJARVIS_HOME/src" ]]; then
    echo "  - src/ (OpenJarvis source)"
fi
if [[ -d "$OPENJARVIS_HOME/voice_samples" ]]; then
    echo "  - voice_samples/ (wake word recordings)"
fi
if [[ -f "$OPENJARVIS_HOME/credentials.toml" ]]; then
    echo "  - credentials.toml (tool credentials)"
fi
if [[ -f "$OPENJARVIS_HOME/env" ]]; then
    echo "  - env (environment variables)"
fi
if [[ -f "$OPENJARVIS_HOME/inference.json" ]]; then
    echo "  - inference.json (inference config)"
fi
echo
echo "Also removing:"
echo "  - ~/.local/bin/jarvis"
echo "  - ~/.local/bin/jarvis-uninstall"
echo

# ---- confirmation ----
if [[ "$SKIP_CONFIRM" -ne 1 ]]; then
    echo "WARNING: This will permanently delete all OpenJarvis data."
    echo
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

# ---- backup ----
if [[ "$SKIP_BACKUP" -ne 1 ]]; then
    TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/openjarvis-backup-$TIMESTAMP.tar.gz"
    echo "Creating backup: $BACKUP_FILE"
    tar -czf "$BACKUP_FILE" -C "$(dirname "$OPENJARVIS_HOME")" "$(basename "$OPENJARVIS_HOME")" 2>/dev/null
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "Backup created: $BACKUP_SIZE"
    echo
fi

# ---- stop background processes ----
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

# ---- remove ----
echo "Removing $OPENJARVIS_HOME..."
rm -rf "$OPENJARVIS_HOME"
echo "Removed $OPENJARVIS_HOME"

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

if [[ "$SKIP_BACKUP" -ne 1 ]]; then
    echo "To restore from backup:"
    echo "  cd ~ && tar -xzf $BACKUP_FILE"
fi
