#!/bin/zsh
set -euo pipefail

ROOT="/Users/paulsunny/Documents/OpenJarvis"

exec "$ROOT/.venv/bin/jarvis" digest "$@"
