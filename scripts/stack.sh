#!/usr/bin/env bash
# OpenJarvis full-stack launcher: Vision (GPU) + Backend + Frontend.
#
# Every export here fixes a failure we actually hit; dropping one breaks a
# feature silently rather than loudly:
#
#   OMP/ORT_NUM_THREADS       unset -> VieNeu renders at 0.4x realtime and
#                             speech breaks up mid-word. Pinned at 4 -> 2.1x.
#                             Must be exported BEFORE the process starts:
#                             numpy sizes its pool at import time.
#   OPENJARVIS_LOCAL_TTS_...  unset -> voice hangs on "Connecting..." forever
#                             (vieneu_artifact_required).
#   OPENJARVIS_CONFIG         unset -> no browser tools; the Agent answers
#                             "no tools for this session".
#   LD_LIBRARY_PATH (vision)  unset -> onnxruntime silently falls back to CPU
#                             and Vision eats ~5 cores instead of the GPU.
#
# Usage: scripts/stack.sh [start|stop|status] [--no-vision]

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OPENJARVIS_ENV_FILE:-/home/robber/Work/jarvis/OpenJarvis/.env}"
VISION_DIR="${OPENJARVIS_VISION_DIR:-/home/robber/Work/jarvis/vision}"
ARTIFACT_DIR="${OPENJARVIS_LOCAL_TTS_ARTIFACT_DIR:-$HOME/.cache/openjarvis/vieneu-3.2.3-onnx}"
MCP_CONFIG="configs/openjarvis/examples/browser-agent-playwright-mcp.toml"
MODEL="${OPENJARVIS_MODEL:-deepseek-v4-pro}"
THREADS="${OPENJARVIS_VIENEU_THREADS:-4}"

LOG_DIR="${OPENJARVIS_LOG_DIR:-/tmp/openjarvis-stack}"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
VISION_LOG="$LOG_DIR/vision.log"

WITH_VISION=1
ACTION="start"
for arg in "$@"; do
    case "$arg" in
        start|stop|status) ACTION="$arg" ;;
        --no-vision) WITH_VISION=0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# -sTCP:LISTEN matters: a bare `lsof -ti:PORT` also returns *clients* connected
# to the port, so an open browser tab shows up as the server — and stop would
# kill the browser instead of the stack.
port_pid() { lsof -ti:"$1" -sTCP:LISTEN 2>/dev/null || true; }

# SIGTERM (never -9): the backend needs to reap its Playwright MCP child,
# otherwise orphaned `npx @playwright/mcp` processes pile up across restarts.
stop_stack() {
    local pid
    for port in 8000 5173; do
        pid="$(port_pid "$port")"
        [ -n "$pid" ] && { echo "  stopping :$port ($(echo $pid | tr '\n' ' '))"; kill $pid 2>/dev/null || true; }
    done
    if [ "$WITH_VISION" = 1 ]; then
        pkill -f "python3 main.py" 2>/dev/null || true
    fi
    sleep 3
    # Anything the backend failed to reap.
    pkill -9 -f "@playwright/mcp" 2>/dev/null || true
    pkill -9 -f "playwright-mcp" 2>/dev/null || true
    for port in 8000 5173; do
        pid="$(port_pid "$port")"
        [ -n "$pid" ] && kill -9 $pid 2>/dev/null || true
    done
    return 0
}

report_line() {  # name, pids (may be empty or multi-line)
    local pids
    pids="$(echo "${2:-}" | tr '\n' ' ' | sed 's/  */ /g;s/ *$//')"
    if [ -n "$pids" ]; then
        printf '  %-10s running (%s)\n' "$1" "$pids"
    else
        printf '  %-10s stopped\n' "$1"
    fi
}

status_stack() {
    report_line backend  "$(port_pid 8000)"
    report_line frontend "$(port_pid 5173)"
    report_line vision   "$(pgrep -f 'python3 main.py' || true)"
    printf '  %-10s %s process(es)\n' "mcp" "$(pgrep -f '@playwright/mcp' | wc -l)"
}

case "$ACTION" in
    stop)   echo "Stopping stack..."; stop_stack; echo "Stopped."; exit 0 ;;
    status) echo "Stack status:"; status_stack; exit 0 ;;
esac

# ---------- preflight: fail loudly now, not silently at runtime ----------
[ -x "$ROOT_DIR/.venv/bin/jarvis" ] || { echo "missing $ROOT_DIR/.venv/bin/jarvis" >&2; exit 1; }
[ -f "$ENV_FILE" ]                  || { echo "missing env file: $ENV_FILE" >&2; exit 1; }
[ -d "$ARTIFACT_DIR" ]              || { echo "missing VieNeu artifact: $ARTIFACT_DIR" >&2; exit 1; }
[ -f "$ROOT_DIR/$MCP_CONFIG" ]      || { echo "missing browser config: $MCP_CONFIG" >&2; exit 1; }

set -a
. "$ENV_FILE"
set +a
[ -n "${GEMINI_API_KEY:-}" ]   || { echo "GEMINI_API_KEY missing (voice STT needs it)" >&2; exit 1; }
[ -n "${DEEPSEEK_API_KEY:-}" ] || { echo "DEEPSEEK_API_KEY missing" >&2; exit 1; }

mkdir -p "$LOG_DIR"
echo "Restarting OpenJarvis stack (model=$MODEL, vision=$WITH_VISION)"
stop_stack

# ---------- Vision (GPU) ----------
if [ "$WITH_VISION" = 1 ] && [ -d "$VISION_DIR" ]; then
    # onnxruntime-gpu ships no CUDA libs; the nvidia-* wheels do. Without these
    # on the path it prints a load error and quietly runs on CPU.
    NV_ROOT="$(python3 -c 'import nvidia,os;print(os.path.dirname(nvidia.__file__))' 2>/dev/null || true)"
    VISION_LD=""
    [ -n "$NV_ROOT" ] && VISION_LD="$NV_ROOT/cu13/lib:$NV_ROOT/cudnn/lib"
    # setsid, not `& disown`: disown is a no-op in a non-interactive subshell,
    # which then blocks in wait() and the launcher never returns.
    (cd "$VISION_DIR" && setsid env LD_LIBRARY_PATH="$VISION_LD:${LD_LIBRARY_PATH:-}" \
        python3 main.py >"$VISION_LOG" 2>&1 </dev/null &)
    echo "  vision   -> $VISION_LOG"
fi

# ---------- Backend ----------
(cd "$ROOT_DIR" && setsid env \
    OMP_NUM_THREADS="$THREADS" \
    ORT_NUM_THREADS="$THREADS" \
    OPENJARVIS_VIENEU_THREADS="$THREADS" \
    KIOSK_ENABLED=true \
    KIOSK_VISION_URL=ws://127.0.0.1:9876 \
    OPENJARVIS_LOCAL_TTS_ARTIFACT_DIR="$ARTIFACT_DIR" \
    OPENJARVIS_CONFIG="$MCP_CONFIG" \
    .venv/bin/jarvis serve --host 127.0.0.1 --port 8000 --engine cloud --model "$MODEL" \
    >"$BACKEND_LOG" 2>&1 </dev/null &)
echo "  backend  -> $BACKEND_LOG"

# ---------- Frontend ----------
(cd "$ROOT_DIR/frontend" && setsid npm run dev -- \
    --host 127.0.0.1 --port 5173 --strictPort \
    >"$FRONTEND_LOG" 2>&1 </dev/null &)
echo "  frontend -> $FRONTEND_LOG"

# ---------- wait ----------
for _ in $(seq 1 90); do
    curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 \
        && curl -fsS http://127.0.0.1:5173/ >/dev/null 2>&1 && break
    sleep 1
done
if ! curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "Backend did not come up. See $BACKEND_LOG" >&2; exit 1
fi
if ! curl -fsS http://127.0.0.1:5173/ >/dev/null 2>&1; then
    echo "Frontend did not come up. See $FRONTEND_LOG" >&2; exit 1
fi

# ---------- verify the things that broke before ----------
echo
echo "Verification:"
tools=$(grep -o 'Agent tools:.*' "$BACKEND_LOG" | tr ',' '\n' | grep -c 'browser_' || echo 0)
printf '  browser tools   %s %s\n' "$tools" "$([ "$tools" -ge 21 ] && echo OK || echo 'FAIL (check OPENJARVIS_CONFIG)')"

mcp=$(pgrep -f '@playwright/mcp' | wc -l)
printf '  playwright mcp  %s %s\n' "$mcp" "$([ "$mcp" -eq 1 ] && echo OK || echo 'unexpected count')"

mem=$(curl -fsS http://127.0.0.1:8000/v1/memory/config 2>/dev/null || echo '')
case "$mem" in
    *'"available":true'*) echo '  memory backend  OK' ;;
    *) echo '  memory backend  FAIL — build it: uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml --release' ;;
esac

if [ "$WITH_VISION" = 1 ]; then
    sleep 5
    if grep -qiE 'Failed to create CUDAExecutionProvider|libcublasLt' "$VISION_LOG" 2>/dev/null; then
        echo '  vision GPU      FAIL — running on CPU, check nvidia-* wheels'
    else
        echo '  vision GPU      OK'
    fi
fi

echo
echo "  Frontend  http://127.0.0.1:5173"
echo "  Kiosk     http://127.0.0.1:5173/kiosk"
echo "  Stop with: scripts/stack.sh stop"
