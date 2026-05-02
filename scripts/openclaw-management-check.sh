#!/bin/zsh
set -u

OPENJARVIS_ROOT="/Users/paulsunny/Documents/OpenJarvis"
OPENCLAW_ROOT="/Users/paulsunny/Documents/openclaw-workspace"
OPENCLAW_HOME="/Users/paulsunny/.openclaw"
OPENJARVIS_URL="${OPENJARVIS_URL:-http://127.0.0.1:8000}"
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
LOCAL_LLM_MODEL="${LOCAL_LLM_MODEL:-gemma4-agent:e4b}"
LEGACY_MLX_HOST="${LEGACY_MLX_HOST:-http://127.0.0.1:11435}"
LEGACY_MLX_EXPECTED="${LEGACY_MLX_EXPECTED:-0}"
REPORT_DIR="/Users/paulsunny/.openjarvis/reports"
RUN_ID="$(date '+%Y%m%d_%H%M%S')"
REPORT_PATH="$REPORT_DIR/openclaw-management-$RUN_ID.md"
LATEST_PATH="$REPORT_DIR/openclaw-management-latest.md"

mkdir -p "$REPORT_DIR"

exec > >(tee "$REPORT_PATH") 2>&1

section() {
  echo
  echo "## $1"
  echo
}

run_shell() {
  local label="$1"
  local cmd="$2"
  echo "### $label"
  echo
  echo '```text'
  echo "$ $cmd"
  zsh -lc "$cmd"
  local code=$?
  echo
  echo "(exit=$code)"
  echo '```'
  echo
  return 0
}

run_shell_timeout() {
  local label="$1"
  local seconds="$2"
  local cmd="$3"
  echo "### $label"
  echo
  echo '```text'
  echo "$ $cmd"
  perl -e 'alarm shift; exec @ARGV' "$seconds" zsh -lc "$cmd"
  local code=$?
  echo
  echo "(exit=$code)"
  echo '```'
  echo
  return 0
}

json_chat_smoke='import json, sys
data=json.load(sys.stdin)
try:
    print(data["choices"][0]["message"]["content"].strip())
except Exception:
    print(json.dumps(data)[:1000])'

cat <<EOF
# OpenClaw Management Check

- Run ID: $RUN_ID
- Timestamp: $(date '+%Y-%m-%d %H:%M:%S %Z')
- OpenJarvis root: $OPENJARVIS_ROOT
- OpenClaw root: $OPENCLAW_ROOT
- OpenClaw home: $OPENCLAW_HOME
- OpenJarvis URL: $OPENJARVIS_URL
- Primary local LLM: $LOCAL_LLM_MODEL via $OLLAMA_HOST
- Legacy optional MLX endpoint: $LEGACY_MLX_HOST
- Legacy MLX expected: $LEGACY_MLX_EXPECTED

EOF

section "Management Console"
cat <<'EOF'
OpenJarvis provides CLI management, an API server via `jarvis serve`, and browser/desktop UI surfaces.
This repository has frontend pages for Dashboard, Agents, Logs, Settings, and Data Sources, but it does not ship an OpenClaw-specific management console by default.
This check is the deterministic OpenClaw operations surface for now.
EOF

section "Health Summary"
run_shell_timeout "OpenClaw health summary" 90 "cd '$OPENJARVIS_ROOT' && bash scripts/openclaw-health-summary.sh || true"

section "Core Paths"
run_shell "OpenJarvis scripts" "ls -la '$OPENJARVIS_ROOT/scripts' | sed -n '1,220p'"
run_shell "OpenClaw key scripts" "ls -la '$OPENCLAW_ROOT/scripts' | sed -n '1,220p'"
run_shell "OpenClaw logs" "ls -la '$OPENCLAW_HOME/logs' | sed -n '1,220p'"

section "OpenJarvis Runtime"
run_shell_timeout "jarvis doctor" 30 "cd '$OPENJARVIS_ROOT' && jarvis doctor"
run_shell_timeout "OpenJarvis server status" 10 "cd '$OPENJARVIS_ROOT' && jarvis status"
run_shell_timeout "OpenJarvis local default ask smoke" 30 "cd '$OPENJARVIS_ROOT' && jarvis ask --no-stream --max-tokens 16 'Reply with only OK.'"

section "OpenClaw Local LLM Runtime"
run_shell_timeout "Ollama tags endpoint" 10 "curl -sS '$OLLAMA_HOST/api/tags'"
run_shell_timeout "Ollama OpenAI-compatible chat endpoint" 30 "curl -sS '$OLLAMA_HOST/v1/chat/completions' -H 'Content-Type: application/json' -d '{\"model\":\"$LOCAL_LLM_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with only OK.\"}],\"max_tokens\":16,\"temperature\":0.2}' | python3 -c '$json_chat_smoke'"
run_shell_timeout "OpenClaw lightweight local chat wrapper" 30 "cd '$OPENJARVIS_ROOT' && bash scripts/openclaw-openjarvis-chat.sh --fresh --json 'Reply with only OK.'"
run_shell_timeout "Pi on OpenClaw local LLM" 45 "cd '$OPENJARVIS_ROOT' && bash scripts/pi-openclaw.sh --no-session --no-context-files -p 'Reply with only OK.'"

section "Legacy Optional MLX Runtime"
run_shell_timeout "Legacy MLX models endpoint" 10 "if lsof -nP -iTCP:11435 -sTCP:LISTEN >/dev/null 2>&1; then curl -sS '$LEGACY_MLX_HOST/v1/models'; elif [[ '$LEGACY_MLX_EXPECTED' == '1' ]]; then echo 'WARN legacy MLX endpoint is expected but not listening'; else echo 'INFO legacy MLX endpoint is intentionally inactive; primary local path is Ollama on 11434'; fi"
run_shell_timeout "Legacy OpenClaw MLX LaunchAgent" 10 "launchctl print gui/$(id -u)/com.paulsunny.openclaw.mlx-localdev 2>/dev/null | sed -n '1,120p' || echo 'missing'"

section "Launch Services"
run_shell_timeout "OpenClaw gateway service" 10 "launchctl print system/ai.openclaw.gateway 2>/dev/null | sed -n '1,120p' || echo 'missing'"
run_shell_timeout "OpenClaw gateway guard service" 10 "launchctl print system/ai.openclaw.gateway.guard 2>/dev/null | sed -n '1,120p' || echo 'missing'"
run_shell_timeout "OpenClaw gateway relay service" 10 "launchctl print system/ai.openclaw.gateway.relay 2>/dev/null | sed -n '1,120p' || echo 'missing'"

section "Ports And Processes"
run_shell_timeout "Listening ports" 10 "lsof -nP -iTCP:11434 -sTCP:LISTEN || true; lsof -nP -iTCP:11435 -sTCP:LISTEN || true; lsof -nP -iTCP:18789 -sTCP:LISTEN || true"
run_shell_timeout "Relevant processes" 10 "ps -ef | rg 'openclaw|mlx_lm.server|ollama|jarvis|pi-coding-agent' | rg -v 'rg '"

section "OpenClaw Built-in Checks"
run_shell_timeout "OpenClaw runtime fast" 30 "'$OPENCLAW_ROOT/scripts/openclaw_runtime_status_fast.sh'"
run_shell_timeout "OpenClaw ops check" 45 "'$OPENCLAW_ROOT/openclaw_ops_check.sh'"

section "Recent Log Signals"
run_shell_timeout "Legacy MLX fatal signals" 10 "tail -200 '$OPENCLAW_HOME/logs/mlx-localdev.stderr.log' 2>/dev/null | rg -i 'traceback|fatal|crash|panic' || true"
run_shell_timeout "Gateway fatal signals" 10 "tail -200 '$OPENCLAW_HOME/logs/gateway.err.log' 2>/dev/null | rg -i 'traceback|fatal|crash|panic' || true"
run_shell_timeout "Guard fatal signals" 10 "tail -200 '$OPENCLAW_HOME/logs/gateway-guard.stderr.log' 2>/dev/null | rg -i 'traceback|fatal|crash|panic' || true"

section "Management Guardrails"
cat <<'EOF'
- This check is read-only except for writing this report.
- Restart actions are intentionally not executed here.
- Use OpenClaw restart commands only after evidence from this report shows a concrete runtime failure.
- Do not delete models, caches, credentials, memories, or launchd files from an automated management task.
EOF

cp "$REPORT_PATH" "$LATEST_PATH"

cat <<EOF

## Report

- Report path: $REPORT_PATH
- Latest symlink/copy: $LATEST_PATH
EOF
