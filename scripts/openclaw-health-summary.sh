#!/bin/zsh
set -u

OPENJARVIS_ROOT="${OPENJARVIS_ROOT:-/Users/paulsunny/Documents/OpenJarvis}"
OPENCLAW_ROOT="${OPENCLAW_ROOT:-/Users/paulsunny/Documents/openclaw-workspace}"
OPENCLAW_HOME="${OPENCLAW_HOME:-/Users/paulsunny/.openclaw}"
OPENJARVIS_URL="${OPENJARVIS_URL:-http://127.0.0.1:8000}"
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
LOCAL_LLM_MODEL="${LOCAL_LLM_MODEL:-gemma4-agent:e4b}"
LEGACY_MLX_HOST="${LEGACY_MLX_HOST:-http://127.0.0.1:11435}"
LEGACY_MLX_EXPECTED="${LEGACY_MLX_EXPECTED:-0}"

fail_count=0
warn_count=0

pass() {
  echo "PASS $1"
}

warn() {
  warn_count=$((warn_count + 1))
  echo "WARN $1"
}

info() {
  echo "INFO $1"
}

fail() {
  fail_count=$((fail_count + 1))
  echo "FAIL $1"
}

json_chat_ok='import json, sys
data=json.load(sys.stdin)
try:
    text=data["choices"][0]["message"]["content"].strip().upper().rstrip(".")
except Exception:
    sys.exit(1)
sys.exit(0 if text == "OK" else 1)'

echo "# OpenClaw Health Summary"
echo
echo "- Timestamp: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "- OpenJarvis: $OPENJARVIS_ROOT"
echo "- OpenClaw: $OPENCLAW_ROOT"
echo "- Local LLM: $LOCAL_LLM_MODEL via $OLLAMA_HOST"
echo

if [[ -d "$OPENJARVIS_ROOT" ]]; then
  pass "openjarvis_root exists"
else
  fail "openjarvis_root missing: $OPENJARVIS_ROOT"
fi

if [[ -d "$OPENCLAW_ROOT" && -d "$OPENCLAW_HOME" ]]; then
  pass "openclaw_paths exist"
else
  fail "openclaw paths missing: root=$OPENCLAW_ROOT home=$OPENCLAW_HOME"
fi

if curl -fsS "$OPENJARVIS_URL/health" >/dev/null 2>&1; then
  pass "openjarvis_server healthy at $OPENJARVIS_URL"
else
  fail "openjarvis_server not healthy at $OPENJARVIS_URL"
fi

tags_file="$(mktemp)"
if curl -fsS "$OLLAMA_HOST/api/tags" >"$tags_file" 2>/dev/null; then
  pass "ollama_api reachable at $OLLAMA_HOST"
  if LOCAL_LLM_MODEL="$LOCAL_LLM_MODEL" python3 - "$tags_file" <<'PY'
import json
import os
import sys

path = sys.argv[1]
target = os.environ["LOCAL_LLM_MODEL"]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
names = [m.get("name") for m in data.get("models", []) if isinstance(m, dict)]
raise SystemExit(0 if target in names else 1)
PY
  then
    pass "local_model available: $LOCAL_LLM_MODEL"
  else
    fail "local_model missing from Ollama: $LOCAL_LLM_MODEL"
  fi
else
  fail "ollama_api not reachable at $OLLAMA_HOST"
fi
rm -f "$tags_file"

chat_payload='{"model":"'"$LOCAL_LLM_MODEL"'","messages":[{"role":"user","content":"Reply with only OK."}],"max_tokens":16,"temperature":0.2}'
if curl -fsS "$OLLAMA_HOST/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "$chat_payload" | python3 -c "$json_chat_ok" >/dev/null 2>&1; then
  pass "ollama_openai_chat smoke returned OK"
else
  fail "ollama_openai_chat smoke failed for $LOCAL_LLM_MODEL"
fi

wrapper_output="$(cd "$OPENJARVIS_ROOT" && bash scripts/openclaw-openjarvis-chat.sh --fresh --json 'Reply with only OK.' 2>&1)"
if python3 -c '
import json
import sys

data = json.load(sys.stdin)
text = str(data.get("response", "")).strip().upper().rstrip(".")
raise SystemExit(0 if data.get("ok") is True and text == "OK" else 1)
' <<< "$wrapper_output" >/dev/null 2>&1
then
  pass "openclaw_lightweight_chat wrapper returned OK"
else
  fail "openclaw_lightweight_chat wrapper failed"
  echo "$wrapper_output" | sed 's/^/  /'
fi

if lsof -nP -iTCP:18789 -sTCP:LISTEN >/dev/null 2>&1; then
  pass "openclaw_gateway port 18789 listening"
else
  fail "openclaw_gateway port 18789 not listening"
fi

if [[ -x "$OPENCLAW_ROOT/scripts/openclaw_runtime_status_fast.sh" ]]; then
  runtime_status="$("$OPENCLAW_ROOT/scripts/openclaw_runtime_status_fast.sh" 2>&1)"
  if echo "$runtime_status" | rg -q "gateway_state=running" && echo "$runtime_status" | rg -q "port_18789=listening"; then
    pass "openclaw_runtime_fast gateway healthy"
  else
    fail "openclaw_runtime_fast did not confirm gateway health"
    echo "$runtime_status" | sed 's/^/  /'
  fi
else
  fail "openclaw_runtime_status_fast.sh missing or not executable"
fi

if lsof -nP -iTCP:11435 -sTCP:LISTEN >/dev/null 2>&1; then
  if curl -fsS "$LEGACY_MLX_HOST/v1/models" >/dev/null 2>&1; then
    pass "legacy_mlx endpoint reachable at $LEGACY_MLX_HOST"
  else
    warn "legacy_mlx port listens but /v1/models did not respond"
  fi
else
  if [[ "$LEGACY_MLX_EXPECTED" == "1" ]]; then
    warn "legacy_mlx endpoint $LEGACY_MLX_HOST is expected but not listening"
  else
    info "legacy_mlx endpoint $LEGACY_MLX_HOST is intentionally inactive; primary local path is Ollama"
  fi
fi

if command -v pi >/dev/null 2>&1; then
  pi_output="$(OPENJARVIS_ROOT="$OPENJARVIS_ROOT" python3 <<'PY'
import os
import subprocess
import sys

root = os.environ["OPENJARVIS_ROOT"]
cmd = [
    "bash",
    "scripts/pi-openclaw.sh",
    "--no-session",
    "--no-context-files",
    "-p",
    "Reply with only OK.",
]
try:
    result = subprocess.run(
        cmd,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=45,
    )
    print(result.stdout, end="")
    raise SystemExit(result.returncode)
except subprocess.TimeoutExpired as exc:
    if exc.stdout:
        print(exc.stdout, end="")
    print("pi_openclaw timed out after 45s")
    raise SystemExit(124)
PY
)"
  pi_code=$?
  if [[ "$pi_code" -eq 0 ]] && echo "$pi_output" | rg -qi "OK"; then
    pass "pi_openclaw wrapper returned OK"
  elif [[ "$pi_code" -eq 124 ]]; then
    warn "pi_openclaw wrapper timed out"
    echo "$pi_output" | sed 's/^/  /'
  else
    warn "pi_openclaw wrapper did not return OK"
    echo "$pi_output" | sed 's/^/  /'
  fi
else
  warn "pi command not installed"
fi

recent_gateway_errors="$(tail -200 "$OPENCLAW_HOME/logs/gateway.err.log" 2>/dev/null | rg -i 'traceback|fatal|crash|panic' || true)"
if [[ -z "$recent_gateway_errors" ]]; then
  pass "gateway recent fatal signals absent"
else
  warn "gateway recent fatal signals detected"
  echo "$recent_gateway_errors" | sed 's/^/  /'
fi

echo
echo "Summary: failures=$fail_count warnings=$warn_count"

if [[ "$fail_count" -gt 0 ]]; then
  exit 1
fi
if [[ "$warn_count" -gt 0 ]]; then
  exit 2
fi
exit 0
