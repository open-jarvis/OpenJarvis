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
ASSUME_YES=false

usage() {
    cat <<'EOF'
Usage: jarvis-uninstall [-y|--yes]

Removes OpenJarvis and its local data. Without --yes, an explicit confirmation
is required before config, memory, skills, databases, or connector tokens are
deleted.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)
            ASSUME_YES=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

refuse_unsafe_root() {
    echo "Refusing unsafe OPENJARVIS_HOME: $OPENJARVIS_HOME" >&2
    exit 2
}

if [[ -d "$OPENJARVIS_HOME" ]]; then
    resolved_install_root="$(cd "$OPENJARVIS_HOME" && pwd -P)"
    resolved_user_home="$(cd "$HOME" && pwd -P)"
    if [[ -z "$resolved_install_root" ]] \
        || [[ "$resolved_install_root" == "/" ]] \
        || [[ "$resolved_install_root" == "$resolved_user_home" ]] \
        || [[ "$resolved_user_home" == "$resolved_install_root"/* ]]; then
        refuse_unsafe_root
    fi

    # Never recursively remove a broad system/temp root, even if an unrelated
    # file happens to resemble an OpenJarvis marker there.
    case "$resolved_install_root" in
        /Users|/home|/opt|/tmp|/private|/private/tmp|/var|/var/tmp|/private/var|/private/var/tmp|/usr|/etc)
            refuse_unsafe_root
            ;;
    esac

    # A path being different from $HOME is not evidence that OpenJarvis owns
    # it.  Require the installer's real, non-symlinked state file and at least
    # one known completed install stage before authorizing recursive removal.
    ownership_marker="$resolved_install_root/.state/install-state.json"
    if [[ ! -f "$ownership_marker" ]] \
        || [[ -L "$ownership_marker" ]] \
        || ! grep -Eq '"(install_uv|clone_repo|copy_scripts|create_venv|editable_install)"[[:space:]]*:[[:space:]]*true' "$ownership_marker"; then
        refuse_unsafe_root
    fi

    # Use the exact physical path that passed every check below as well.
    OPENJARVIS_HOME="$resolved_install_root"

    if [[ "$ASSUME_YES" != true ]]; then
        cat <<EOF
WARNING: This permanently deletes all OpenJarvis data under:
  $OPENJARVIS_HOME

That includes config.toml, SOUL.md/MEMORY.md/USER.md, skills, scheduler and
telemetry databases, stored memory, and connector/OAuth credentials.
EOF
        printf 'Type "yes" to continue: '
        reply=""
        read -r reply || true
        case "$reply" in
            yes|YES|Yes) ;;
            *)
                echo "OpenJarvis was not removed."
                exit 0
                ;;
        esac
    fi
fi

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
    rm -rf -- "$OPENJARVIS_HOME"
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
