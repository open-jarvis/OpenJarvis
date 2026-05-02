#!/bin/zsh
set -euo pipefail

ROOT="/Users/paulsunny/Documents/OpenJarvis"

exec "$ROOT/.venv/bin/jarvis" ask \
  -a native_openhands \
  --tools "code_interpreter,file_read,file_write,shell_exec,web_search,think,calculator,skill_manage,memory_search,retrieval" \
  "$@"
