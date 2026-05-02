#!/bin/zsh
set -euo pipefail

ROOT="/Users/paulsunny/Documents/OpenJarvis"
AGENT_ID="f383c0dbbd62"

exec "$ROOT/.venv/bin/jarvis" agents ask "$AGENT_ID" "$@"
