#!/usr/bin/env zsh
set -euo pipefail

export HOME="/Users/guru"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

ROOT="/Users/guru/Documents/GitHub/OpenJarvis"
LOGDIR="$HOME/Library/Logs/OpenJarvis"

UV="/opt/homebrew/bin/uv"
NPM="/opt/homebrew/bin/npm"
OLLAMA="/opt/homebrew/bin/ollama"
CURL="/usr/bin/curl"
LSOF="/usr/sbin/lsof"

mkdir -p "$LOGDIR"
cd "$ROOT"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Starting OpenJarvis Friday local stack..."
log "ROOT=$ROOT"
log "UV=$UV"
log "NPM=$NPM"
log "OLLAMA=$OLLAMA"

if "$CURL" -fsS "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  log "Ollama is already running."
else
  log "Starting Ollama..."
  nohup "$OLLAMA" serve >> "$LOGDIR/ollama.log" 2>&1 &
  sleep 5
fi

if "$LSOF" -iTCP:8000 -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  log "OpenJarvis backend is already running on port 8000."
else
  log "Starting OpenJarvis backend on port 8000..."
  cd "$ROOT"
  nohup "$UV" run jarvis serve --port 8000 >> "$LOGDIR/backend.log" 2>&1 &
  sleep 5
fi

if "$LSOF" -iTCP:5173 -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  log "OpenJarvis frontend is already running on port 5173."
else
  log "Starting OpenJarvis frontend on port 5173..."
  cd "$ROOT/frontend"
  nohup "$NPM" run dev -- --host 127.0.0.1 --port 5173 >> "$LOGDIR/frontend.log" 2>&1 &
  sleep 5
fi

log "OpenJarvis Friday local stack started."

while true; do
  sleep 3600
done
