#!/usr/bin/env bash
# friday-wrapper.sh — symlinked to ~/.local/bin/friday.
# Activates the managed venv and execs the real friday CLI.

FRIDAY_AI_HOME="${FRIDAY_AI_HOME:-$HOME/.friday_ai}"
VENV="$FRIDAY_AI_HOME/.venv"

if [[ ! -d "$VENV" ]]; then
    echo "friday: venv not found at $VENV" >&2
    echo "Re-run the installer: curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash" >&2
    exit 1
fi

exec "$VENV/bin/friday" "$@"
