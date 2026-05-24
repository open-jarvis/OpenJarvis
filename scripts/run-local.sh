#!/usr/bin/env bash
set -euo pipefail

# OpenJarvis local macOS startup script.
#
# Usage:
#   ./scripts/run-local.sh
#
# Optional overrides:
#   OPENJARVIS_MODEL=qwen3:8b ./scripts/run-local.sh
#   BACKEND_PORT=8000 FRONTEND_PORT=5173 ./scripts/run-local.sh
#   OLLAMA_HOST=http://127.0.0.1:11434 ./scripts/run-local.sh
#
# This script keeps OpenJarvis local-first:
#   - Ollama is required and started locally when needed.
#   - The backend is started with --engine ollama and a local Ollama model.
#   - Cloud API key environment variables are cleared for the backend process.
#
# Prerequisites:
#   uv sync --extra server
#   cd frontend && npm install && cd ..

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${BLUE}[info]${NC} $*"; }
ok() { echo -e "${GREEN}[ok]${NC}   $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
fail() {
  echo -e "${RED}[fail]${NC} $*" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
OPENJARVIS_MODEL="${OPENJARVIS_MODEL:-qwen3:0.6b}"

PIDS=()
cleanup() {
  if [ "${#PIDS[@]}" -gt 0 ]; then
    echo ""
    info "Stopping services started by this script..."
    for pid in "${PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

require_command() {
  local command_name="$1"
  local install_hint="$2"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    fail "$command_name is required. $install_hint"
  fi
}

http_ok() {
  local url="$1"
  curl -fsS "$url" >/dev/null 2>&1
}

port_in_use() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for_url() {
  local url="$1"
  local name="$2"
  local attempts="${3:-30}"

  for _ in $(seq 1 "$attempts"); do
    if http_ok "$url"; then
      ok "$name is ready at $url"
      return 0
    fi
    sleep 1
  done

  return 1
}

cd "$REPO_ROOT"

echo "OpenJarvis local startup"
echo "Backend:  http://$BACKEND_HOST:$BACKEND_PORT"
echo "Frontend: http://$FRONTEND_HOST:$FRONTEND_PORT"
echo "Ollama:   $OLLAMA_HOST"
echo "Model:    $OPENJARVIS_MODEL"
echo ""

case "$(uname -s)" in
  Darwin) ;;
  *) warn "This script is intended for macOS, but will continue on this system." ;;
esac

require_command curl "Install curl or use the macOS system curl."
require_command lsof "Install lsof or use the macOS system lsof."
require_command uv "Install uv: https://docs.astral.sh/uv/"
require_command node "Install Node.js 20 or newer: https://nodejs.org/"
require_command npm "Install npm with Node.js."
require_command ollama "Install Ollama: https://ollama.com/download"

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  fail "Frontend dependencies are missing. Run: cd frontend && npm install && cd .."
fi

info "Checking Ollama..."
if http_ok "$OLLAMA_HOST/api/tags"; then
  ok "Ollama is already running"
else
  info "Starting Ollama..."
  OLLAMA_HOST="$OLLAMA_HOST" ollama serve >/tmp/openjarvis-ollama.log 2>&1 &
  PIDS+=("$!")
  wait_for_url "$OLLAMA_HOST/api/tags" "Ollama" 20 \
    || fail "Ollama did not become ready. See /tmp/openjarvis-ollama.log"
fi

info "Checking local model '$OPENJARVIS_MODEL'..."
if OLLAMA_HOST="$OLLAMA_HOST" ollama list 2>/dev/null \
  | awk '{print $1}' \
  | grep -Fxq "$OPENJARVIS_MODEL"; then
  ok "Model is available locally"
else
  warn "Model '$OPENJARVIS_MODEL' is not pulled yet."
  echo "Run this in another terminal, then start again:"
  echo "  ollama pull $OPENJARVIS_MODEL"
  exit 1
fi

BACKEND_URL="http://$BACKEND_HOST:$BACKEND_PORT"
FRONTEND_URL="http://$FRONTEND_HOST:$FRONTEND_PORT"

info "Checking backend on port $BACKEND_PORT..."
if http_ok "$BACKEND_URL/health"; then
  ok "Backend is already running at $BACKEND_URL"
elif port_in_use "$BACKEND_PORT"; then
  fail "Port $BACKEND_PORT is already in use, but $BACKEND_URL/health did not respond."
else
  info "Starting OpenJarvis backend with Ollama on port $BACKEND_PORT..."
  env \
    OPENAI_API_KEY= \
    ANTHROPIC_API_KEY= \
    GEMINI_API_KEY= \
    GOOGLE_API_KEY= \
    OPENROUTER_API_KEY= \
    OLLAMA_HOST="$OLLAMA_HOST" \
    uv run jarvis serve \
      --host "$BACKEND_HOST" \
      --port "$BACKEND_PORT" \
      --engine ollama \
      --model "$OPENJARVIS_MODEL" \
      >/tmp/openjarvis-backend.log 2>&1 &
  PIDS+=("$!")
  wait_for_url "$BACKEND_URL/health" "Backend" 30 \
    || fail "Backend did not become ready. See /tmp/openjarvis-backend.log"
fi

info "Checking frontend on port $FRONTEND_PORT..."
if http_ok "$FRONTEND_URL"; then
  ok "Frontend is already running at $FRONTEND_URL"
elif port_in_use "$FRONTEND_PORT"; then
  fail "Port $FRONTEND_PORT is already in use, but $FRONTEND_URL did not respond."
else
  info "Starting frontend dev server on port $FRONTEND_PORT..."
  (
    cd "$FRONTEND_DIR"
    npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
  ) >/tmp/openjarvis-frontend.log 2>&1 &
  PIDS+=("$!")
  wait_for_url "$FRONTEND_URL" "Frontend" 30 \
    || fail "Frontend did not become ready. See /tmp/openjarvis-frontend.log"
fi

echo ""
ok "OpenJarvis is running locally."
echo "Chat UI: $FRONTEND_URL"
echo "API:     $BACKEND_URL"
echo "Model:   $OPENJARVIS_MODEL"
echo ""
echo "Logs:"
echo "  Backend:  /tmp/openjarvis-backend.log"
echo "  Frontend: /tmp/openjarvis-frontend.log"
echo "  Ollama:   /tmp/openjarvis-ollama.log"
echo ""
echo "Press Ctrl+C to stop services started by this script."

wait
