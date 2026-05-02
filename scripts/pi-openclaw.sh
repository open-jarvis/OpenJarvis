#!/bin/zsh
set -euo pipefail

exec pi \
  --provider openjarvis-ollama \
  --model "gemma4-agent:e4b" \
  "$@"
