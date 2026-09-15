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
# Usage: scripts/launcher.sh [start|stop|status] [--no-vision]

set -Eeuo pipefail

# ---------- Standard Linux CLI Logging Helpers ----------
# Format: [YYYY-MM-DD HH:MM:SS] [LEVEL] Message
_log_msg() {
    local level="$1"
    local color="$2"
    local fd="$3"
    shift 3
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    if [ -t "$fd" ]; then
        printf '[%s] %b[%s]%b %s\n' "$ts" "$color" "$level" "\033[0m" "$*" >&"$fd"
    else
        printf '[%s] [%s] %s\n' "$ts" "$level" "$*" >&"$fd"
    fi
}

log_info()    { _log_msg "INFO"    "\033[36m" 1 "$@"; }   # Cyan
log_warn()    { _log_msg "WARN"    "\033[33m" 1 "$@"; }   # Yellow
log_error()   { _log_msg "ERROR"   "\033[31m" 2 "$@"; }   # Red
log_success() { _log_msg "SUCCESS" "\033[32m" 1 "$@"; }   # Green

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OPENJARVIS_ENV_FILE:-/home/robber/Work/jarvis/OpenJarvis/.env}"
VISION_DIR="${OPENJARVIS_VISION_DIR:-/home/robber/Work/jarvis/vision}"
ARTIFACT_DIR="${OPENJARVIS_LOCAL_TTS_ARTIFACT_DIR:-$HOME/.cache/openjarvis/vieneu-3.2.3-onnx}"
# The kiosk config is the default because it is what this stack is run for:
# it gives the Agent the http_request + display_* tools the /kiosk route
# drives. The browser-agent config is still one env var away.
MCP_CONFIG="${OPENJARVIS_CONFIG:-configs/openjarvis/examples/ordering-kiosk-mcp.toml}"
MODEL="${OPENJARVIS_MODEL:-gpt-5.6-luna}"
# VieNeu ONNX thread pools.  More threads buy no audible speed here: measured
# on this box (i7-11800H, otherwise idle) across four utterance lengths,
# 1 thread renders at RTF 0.34 on 2.99 cores while 4 threads render at RTF
# 0.33 on 5.93 cores.  Both finish ~3x faster than playback, so the extra
# ~2.9 cores buy a difference nobody can hear -- and on a kiosk those cores
# are contended by vision and the display browser.
#
# This is a per-machine tuning value, not a universal one: tts_engine.py
# records a box where more threads did help.  Re-measure on new hardware and
# override with OPENJARVIS_VIENEU_THREADS rather than editing this default.
THREADS="${OPENJARVIS_VIENEU_THREADS:-1}"

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
        *) log_error "Unknown argument: $arg"; exit 2 ;;
    esac
done

# -sTCP:LISTEN matters: a bare `lsof -ti:PORT` also returns *clients* connected
# to the port, so an open browser tab shows up as the server — and stop would
# kill the browser instead of the stack.
port_pid() { lsof -ti:"$1" -sTCP:LISTEN 2>/dev/null || true; }

# SIGTERM (never -9): the backend needs to reap its Playwright MCP child,
# otherwise orphaned `npx @playwright/mcp` processes pile up across restarts.
stop_stack() {
    log_info "Stopping OpenJarvis stack services..."
    local pid doomed=() remaining deadline
    for port in 8000 5173; do
        pid="$(port_pid "$port")"
        if [ -n "$pid" ]; then
            log_info "Sending SIGTERM to listener on :$port (PID $pid)..."
            kill "$pid" 2>/dev/null || true
            # Track the PIDs, not the ports.  A backend that has released its
            # listener but not yet exited still holds ~700 MB, and the old
            # port-based sweep could not see it -- so it survived the restart
            # and ran alongside its replacement.
            doomed+=("$pid")
        fi
    done
    if [ "$WITH_VISION" = 1 ]; then
        local v_pids
        v_pids="$(pgrep -f "python3 main.py" 2>/dev/null || true)"
        if [ -n "$v_pids" ]; then
            log_info "Sending SIGTERM to Vision processes (PID $(echo "$v_pids" | tr '\n' ' '))..."
            pkill -f "python3 main.py" 2>/dev/null || true
            for vp in $v_pids; do
                doomed+=("$vp")
            done
        fi
    fi

    # Wait for a clean exit rather than a fixed sleep: SIGTERM has to give the
    # backend time to reap its Playwright MCP child.
    deadline=$((SECONDS + 15))
    while [ "$SECONDS" -lt "$deadline" ]; do
        remaining=""
        for pid in "${doomed[@]:-}"; do
            [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && remaining="$remaining $pid"
        done
        [ -z "$remaining" ] && break
        sleep 0.5
    done

    # Anything the backend failed to reap.
    local mcp_pids
    mcp_pids="$(pgrep -f '@playwright/mcp|playwright-mcp' 2>/dev/null || true)"
    if [ -n "$mcp_pids" ]; then
        log_info "Reaping orphaned Playwright MCP processes..."
        pkill -9 -f "@playwright/mcp" 2>/dev/null || true
        pkill -9 -f "playwright-mcp" 2>/dev/null || true
    fi

    # Whatever ignored SIGTERM, by PID and by port.
    for pid in "${doomed[@]:-}"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            log_warn "Force-killing PID $pid (ignored SIGTERM)..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    for port in 8000 5173; do
        pid="$(port_pid "$port")"
        if [ -n "$pid" ]; then
            log_warn "Force-killing listener on :$port (PID $pid)..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    log_success "All stack services stopped."
    return 0
}

status_stack() {
    log_info "Checking OpenJarvis stack status..."
    local b_pid f_pid v_pids mcp_count
    b_pid="$(port_pid 8000)"
    f_pid="$(port_pid 5173)"
    v_pids="$(pgrep -f 'python3 main.py' 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g;s/ *$//' || true)"
    mcp_count="$(pgrep -f '@playwright/mcp' 2>/dev/null | wc -l)"

    if [ -n "$b_pid" ]; then
        if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
            log_success "Backend:  running (PID $b_pid, port 8000 healthy)"
        else
            log_warn "Backend:  running (PID $b_pid, port 8000 open, health check failing)"
        fi
    else
        log_warn "Backend:  stopped (port 8000 inactive)"
    fi

    if [ -n "$f_pid" ]; then
        if curl -fsS http://127.0.0.1:5173/ >/dev/null 2>&1; then
            log_success "Frontend: running (PID $f_pid, port 5173 ready)"
        else
            log_warn "Frontend: running (PID $f_pid, port 5173 open, not responding to HTTP)"
        fi
    else
        log_warn "Frontend: stopped (port 5173 inactive)"
    fi

    if [ -n "$v_pids" ]; then
        log_success "Vision:   running (PID $v_pids)"
    else
        if [ "$WITH_VISION" = 1 ]; then
            log_warn "Vision:   stopped"
        else
            log_info "Vision:   disabled (--no-vision)"
        fi
    fi

    if [ "$mcp_count" -gt 0 ]; then
        log_info "MCP:      $mcp_count active Playwright process(es)"
    else
        log_info "MCP:      0 active Playwright process(es)"
    fi
}

case "$ACTION" in
    stop)   stop_stack; exit 0 ;;
    status) status_stack; exit 0 ;;
esac

# ---------- preflight: fail loudly now, not silently at runtime ----------
log_info "Running preflight checks..."
[ -x "$ROOT_DIR/.venv/bin/jarvis" ] || { log_error "Missing executable: $ROOT_DIR/.venv/bin/jarvis"; exit 1; }
[ -f "$ENV_FILE" ]                  || { log_error "Missing env file: $ENV_FILE"; exit 1; }
[ -d "$ARTIFACT_DIR" ]              || { log_error "Missing VieNeu artifact: $ARTIFACT_DIR"; exit 1; }
case "$MCP_CONFIG" in
    /*) MCP_CONFIG_PATH="$MCP_CONFIG" ;;
    *)  MCP_CONFIG_PATH="$ROOT_DIR/$MCP_CONFIG" ;;
esac
[ -f "$MCP_CONFIG_PATH" ]           || { log_error "Missing config: $MCP_CONFIG"; exit 1; }

set -a
. "$ENV_FILE"
set +a
[ -n "${GEMINI_API_KEY:-}" ]   || { log_error "GEMINI_API_KEY missing in $ENV_FILE (voice STT needs it)"; exit 1; }
[ -n "${DEEPSEEK_API_KEY:-}" ] || { log_error "DEEPSEEK_API_KEY missing in $ENV_FILE"; exit 1; }

log_success "Preflight checks passed."
mkdir -p "$LOG_DIR"
log_info "Restarting OpenJarvis stack (model=$MODEL, vision=$WITH_VISION, threads=$THREADS)..."
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
    log_info "Vision service started -> $VISION_LOG"
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
log_info "Backend service started on :8000 -> $BACKEND_LOG"

# ---------- Frontend ----------
(cd "$ROOT_DIR/frontend" && setsid npm run dev -- \
    --host 127.0.0.1 --port 5173 --strictPort \
    >"$FRONTEND_LOG" 2>&1 </dev/null &)
log_info "Frontend service started on :5173 -> $FRONTEND_LOG"

# ---------- Healthcheck ----------
log_info "Waiting for stack services to become healthy (timeout 90s)..."
backend_up=0
frontend_up=0
for elapsed in $(seq 1 90); do
    if [ "$backend_up" -eq 0 ] && curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
        backend_up=1
        log_success "Backend is healthy (http://127.0.0.1:8000/health responded in ${elapsed}s)"
    fi
    if [ "$frontend_up" -eq 0 ] && curl -fsS http://127.0.0.1:5173/ >/dev/null 2>&1; then
        frontend_up=1
        log_success "Frontend is ready (http://127.0.0.1:5173/ responded in ${elapsed}s)"
    fi
    if [ "$backend_up" -eq 1 ] && [ "$frontend_up" -eq 1 ]; then
        break
    fi

    # Early exit check: fail fast if backend crashed on startup
    if [ "$backend_up" -eq 0 ] && [ "$elapsed" -ge 4 ] && [ -z "$(port_pid 8000)" ]; then
        if grep -qiE 'Traceback \(most recent call last\)|Error:|Exception:' "$BACKEND_LOG" 2>/dev/null; then
            log_error "Backend process exited with an error. Recent log output:"
            tail -n 12 "$BACKEND_LOG" >&2 || true
            exit 1
        fi
    fi
    sleep 1
done

if [ "$backend_up" -eq 0 ]; then
    log_error "Backend did not come up within 90s. See $BACKEND_LOG"
    exit 1
fi
if [ "$frontend_up" -eq 0 ]; then
    log_error "Frontend did not come up within 90s. See $FRONTEND_LOG"
    exit 1
fi

# ---------- Verification ----------
log_info "Verifying stack components and tool integrations..."
tools=$(grep -o 'Agent tools:.*' "$BACKEND_LOG" 2>/dev/null | tr ',' '\n' | grep -c 'browser_' || true)
expected_tools=$("$ROOT_DIR/.venv/bin/python" -c '
import sys, tomllib
with open(sys.argv[1], "rb") as stream:
    value = tomllib.load(stream).get("tools", {}).get("enabled", "")
names = value if isinstance(value, list) else value.split(",")
print(sum(str(name).strip().startswith("browser_") for name in names))
' "$MCP_CONFIG_PATH" 2>/dev/null || echo 0)

if [ "$tools" -eq "$expected_tools" ] && [ "$expected_tools" -gt 0 ]; then
    log_success "Agent browser tools: $tools/$expected_tools verified"
else
    log_warn "Agent browser tools: found $tools (expected $expected_tools)"
fi

mcp=$(pgrep -f '@playwright/mcp' 2>/dev/null | wc -l)
if [ "$mcp" -eq 1 ]; then
    log_success "Playwright MCP daemon: active (1 process running)"
elif [ "$mcp" -gt 1 ]; then
    log_warn "Playwright MCP daemon: $mcp processes running (expected 1)"
else
    log_warn "Playwright MCP daemon: not running (expected 1 process)"
fi

mem=$(curl -fsS http://127.0.0.1:8000/v1/memory/config 2>/dev/null || echo '')
case "$mem" in
    *'"available":true'*)
        log_success "Memory backend: available and operational"
        ;;
    *)
        log_warn "Memory backend: unavailable — build with: uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml --release"
        ;;
esac

if [ "$WITH_VISION" = 1 ]; then
    sleep 3
    if grep -qiE 'Failed to create CUDAExecutionProvider|libcublasLt' "$VISION_LOG" 2>/dev/null; then
        log_warn "Vision GPU: running on CPU fallback (check nvidia-* wheels)"
    elif grep -qiE 'CUDAExecutionProvider|Running on GPU|Device: cuda' "$VISION_LOG" 2>/dev/null || [ -n "$(pgrep -f 'python3 main.py' 2>/dev/null || true)" ]; then
        log_success "Vision GPU: service running"
    else
        log_warn "Vision GPU: not responding or check $VISION_LOG"
    fi
fi

log_success "OpenJarvis stack launched successfully!"
log_info "  - Web Chat:  http://127.0.0.1:5173"
log_info "  - Kiosk UI:  http://127.0.0.1:5173/kiosk"
log_info "  - Stop with: scripts/launcher.sh stop"
