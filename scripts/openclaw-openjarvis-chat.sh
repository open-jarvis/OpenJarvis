#!/bin/zsh
set -euo pipefail

OPENCLAW_CHAT="/Users/paulsunny/Documents/openclaw-workspace/scripts/openjarvis_mlx_chat.sh"

if [[ ! -x "$OPENCLAW_CHAT" ]]; then
  echo "OpenClaw OpenJarvis chat wrapper not found: $OPENCLAW_CHAT" >&2
  exit 1
fi

exec "$OPENCLAW_CHAT" "$@"
