#!/usr/bin/env bash
set -euo pipefail

# ── OpenJarvis Quickstart ─────────────────────────────────────────────
# One-command setup: installs deps, starts Ollama + model, launches
# the backend API server and frontend, then opens the browser.
#
# Usage:
#   git clone https://github.com/open-jarvis/OpenJarvis.git
#   cd OpenJarvis
#   ./scripts/quickstart.sh
# ──────────────────────────────────────────────────────────────────────

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

info()  { echo -e "${BLUE}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
fail()  { echo -e "${RED}[fail]${NC}  $*"; exit 1; }

CLEANUP_PIDS=()
cleanup() {
  echo ""
  info "Shutting down..."
  for pid in "${CLEANUP_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  ok "Done."
}
trap cleanup EXIT INT TERM

# ── Navigate to repo root ────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo -e "${BOLD}"
echo "  ┌──────────────────────────────────┐"
echo "  │       OpenJarvis Quickstart      │"
echo "  └──────────────────────────────────┘"
echo -e "${NC}"

# ── 1. Check Python ──────────────────────────────────────────────────
info "Checking Python..."
if command -v python3 &>/dev/null; then
  PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
  PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
  if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
    ok "Python $PY_VERSION"
  else
    fail "Python 3.10+ required (found $PY_VERSION)"
  fi
else
  fail "Python 3 not found. Install from https://python.org"
fi

# ── 2. Check / install uv ───────────────────────────────────────────
info "Checking uv..."
if command -v uv &>/dev/null; then
  ok "uv $(uv --version 2>/dev/null | head -1)"
else
  warn "uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  ok "uv installed"
fi

# ── 3. Check Node.js ────────────────────────────────────────────────
info "Checking Node.js..."
if command -v node &>/dev/null; then
  NODE_VERSION=$(node --version)
  NODE_MAJOR=$(echo "$NODE_VERSION" | sed 's/v//' | cut -d. -f1)
  if [ "$NODE_MAJOR" -ge 18 ]; then
    ok "Node.js $NODE_VERSION"
  else
    fail "Node.js 18+ required (found $NODE_VERSION). Install from https://nodejs.org"
  fi
else
  fail "Node.js not found. Install from https://nodejs.org"
fi

# ── 4. Check / install Ollama ────────────────────────────────────────
info "Checking Ollama..."
if command -v ollama &>/dev/null; then
  ok "Ollama found"
else
  warn "Ollama not found — installing..."
  case "$(uname -s)" in
    Darwin)
      if command -v brew &>/dev/null; then
        brew install ollama
      else
        echo "  Download Ollama from https://ollama.com/download"
        echo "  Then re-run this script."
        exit 1
      fi
      ;;
    Linux)
      curl -fsSL https://ollama.com/install.sh | sh
      ;;
    *)
      echo "  Download Ollama from https://ollama.com/download"
      echo "  Then re-run this script."
      exit 1
      ;;
  esac
  ok "Ollama installed"
fi

# ── 5. Start Ollama if not running ───────────────────────────────────
info "Checking if Ollama is running..."
if curl -sf http://localhost:11434/api/tags &>/dev/null; then
  ok "Ollama is running"
else
  info "Starting Ollama..."
  ollama serve &>/dev/null &
  CLEANUP_PIDS+=($!)
  sleep 3
  if curl -sf http://localhost:11434/api/tags &>/dev/null; then
    ok "Ollama started"
  else
    fail "Could not start Ollama. Try running 'ollama serve' manually."
  fi
fi

# ── 6. Pull a starter model ─────────────────────────────────────────
MODEL="${OPENJARVIS_MODEL:-qwen3:0.6b}"
info "Ensuring model '$MODEL' is available..."
if ollama list 2>/dev/null | grep -q "$MODEL"; then
  ok "Model '$MODEL' already pulled"
else
  info "Pulling '$MODEL' (this may take a minute)..."
  ollama pull "$MODEL"
  ok "Model '$MODEL' ready"
fi

# ── 7. Install Python dependencies ──────────────────────────────────
info "Installing Python dependencies..."
uv sync --extra server --quiet 2>/dev/null || uv sync --extra server
ok "Python dependencies installed"

# ── 8. Install frontend dependencies ────────────────────────────────
info "Installing frontend dependencies..."
(cd frontend && npm install --silent 2>/dev/null || npm install)
ok "Frontend dependencies installed"

# ── 9. Start backend ────────────────────────────────────────────────
info "Starting backend API server on port 8000..."
uv run jarvis serve --port 8000 &>/dev/null &
CLEANUP_PIDS+=($!)
sleep 3

if curl -sf http://localhost:8000/health &>/dev/null; then
  ok "Backend running at http://localhost:8000"
else
  warn "Backend may still be starting..."
fi

# ── 10. Start frontend ──────────────────────────────────────────────
info "Starting frontend dev server on port 5173..."
(cd frontend && npm run dev) &>/dev/null &
CLEANUP_PIDS+=($!)
sleep 3
ok "Frontend running at http://localhost:5173"

# ── 11. Open browser ────────────────────────────────────────────────
URL="http://localhost:5173"
info "Opening $URL ..."
case "$(uname -s)" in
  Darwin) open "$URL" ;;
  Linux)  xdg-open "$URL" 2>/dev/null || true ;;
  *)      true ;;
esac

echo ""
echo -e "${GREEN}${BOLD}  OpenJarvis is running!${NC}"
echo ""
echo "  Chat UI:  http://localhost:5173"
echo "  API:      http://localhost:8000"
echo "  Model:    $MODEL"
echo ""
echo "  Press Ctrl+C to stop all services."
echo ""

wait
