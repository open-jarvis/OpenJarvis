#!/bin/zsh
set -euo pipefail

ROOT="/Users/paulsunny/Documents/OpenJarvis"
AGENT_ID="0fce6b139665"

exec "$ROOT/.venv/bin/jarvis" agents ask "$AGENT_ID" "$@"
