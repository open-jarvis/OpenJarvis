#!/bin/zsh
set -euo pipefail

ROOT="/Users/paulsunny/Documents/OpenJarvis"

exec "$ROOT/.venv/bin/jarvis" ask \
  -a orchestrator \
  --tools "code_interpreter,web_search,file_read,file_write,shell_exec,think,calculator,skill_manage,memory_search,memory_retrieve,retrieval" \
  "$@"
