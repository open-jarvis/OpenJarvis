#!/bin/zsh
set -euo pipefail

ROOT="/Users/paulsunny/Documents/OpenJarvis"
AGENT_ID="dc6cd562ca6a"

exec "$ROOT/.venv/bin/jarvis" agents ask "$AGENT_ID" "$@"
