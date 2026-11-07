#!/usr/bin/env bash
# friday-uninstall.sh — clean removal of FridayAI from $HOME.
#
# Removes:
#   ~/.friday_ai/
#   ~/.local/bin/friday
#   ~/.local/bin/friday-uninstall
#
# Does NOT remove: ollama, uv, or the Rust toolchain.

set -euo pipefail

FRIDAY_AI_HOME="${FRIDAY_AI_HOME:-$HOME/.friday_ai}"
ASSUME_YES=false

usage() {
    cat <<'EOF'
Usage: friday-uninstall [-y|--yes]

Removes FridayAI and its local data. Without --yes, an explicit confirmation
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
    echo "Refusing unsafe FRIDAY_AI_HOME: $FRIDAY_AI_HOME" >&2
    exit 2
}

if [[ -d "$FRIDAY_AI_HOME" ]]; then
    resolved_install_root="$(cd "$FRIDAY_AI_HOME" && pwd -P)"
    resolved_user_home="$(cd "$HOME" && pwd -P)"
    if [[ -z "$resolved_install_root" ]] \
        || [[ "$resolved_install_root" == "/" ]] \
        || [[ "$resolved_install_root" == "$resolved_user_home" ]] \
        || [[ "$resolved_user_home" == "$resolved_install_root"/* ]]; then
        refuse_unsafe_root
    fi

    # Never recursively remove a broad system/temp root, even if an unrelated
    # file happens to resemble an FridayAI marker there.
    case "$resolved_install_root" in
        /Users|/home|/opt|/tmp|/private|/private/tmp|/var|/var/tmp|/private/var|/private/var/tmp|/usr|/etc)
            refuse_unsafe_root
            ;;
    esac

    # A path being different from $HOME is not evidence that FridayAI owns
    # it.  Require the installer's real, non-symlinked state file and at least
    # one known completed install stage before authorizing recursive removal.
    ownership_marker="$resolved_install_root/.state/install-state.json"
    if [[ ! -f "$ownership_marker" ]] \
        || [[ -L "$ownership_marker" ]] \
        || ! grep -Eq '"(install_uv|clone_repo|copy_scripts|create_venv|editable_install)"[[:space:]]*:[[:space:]]*true' "$ownership_marker"; then
        refuse_unsafe_root
    fi

    # Use the exact physical path that passed every check below as well.
    FRIDAY_AI_HOME="$resolved_install_root"

    if [[ "$ASSUME_YES" != true ]]; then
        cat <<EOF
WARNING: This permanently deletes all FridayAI data under:
  $FRIDAY_AI_HOME

That includes config.toml, SOUL.md/MEMORY.md/USER.md, skills, scheduler and
telemetry databases, stored memory, and connector/OAuth credentials.
EOF
        printf 'Type "yes" to continue: '
        reply=""
        read -r reply || true
        case "$reply" in
            yes|YES|Yes) ;;
            *)
                echo "FridayAI was not removed."
                exit 0
                ;;
        esac
    fi
fi

if [[ -f "$FRIDAY_AI_HOME/.state/bg.pid" ]]; then
    pid=$(cat "$FRIDAY_AI_HOME/.state/bg.pid" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        echo "Stopping background work (pid=$pid)..."
        kill "$pid" 2>/dev/null || true
    fi
fi

if command -v ollama >/dev/null 2>&1; then
    ollama stop >/dev/null 2>&1 || true
fi

if [[ -d "$FRIDAY_AI_HOME" ]]; then
    rm -rf -- "$FRIDAY_AI_HOME"
    echo "Removed $FRIDAY_AI_HOME"
fi

for f in "$HOME/.local/bin/friday" "$HOME/.local/bin/friday-uninstall"; do
    if [[ -L "$f" ]] || [[ -f "$f" ]]; then
        rm -f "$f"
        echo "Removed $f"
    fi
done

cat <<EOF

FridayAI removed.

Left intact (may be used by other tools):
  - Ollama       (uninstall: brew uninstall ollama  /  rm -f /usr/local/bin/ollama)
  - uv           (uninstall: rm -rf ~/.local/share/uv ~/.cargo/bin/uv)
  - Rust toolchain (uninstall: rustup self uninstall)
EOF
