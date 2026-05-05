#!/bin/zsh
set -euo pipefail

ROOT="/Users/paulsunny/Documents/OpenJarvis"

exec "$ROOT/.venv/bin/jarvis" ask \
  -a deep_research \
  --tools "web_search,retrieval,memory_search,memory_retrieve,think,file_read" \
  "$@"
