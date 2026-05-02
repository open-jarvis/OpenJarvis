# OpenJarvis System Record

Last updated: 2026-05-02 KST

This document records the installed OpenJarvis configuration, local access points, OpenClaw management wiring, and the most recent operational changes on this machine. Secret values are intentionally excluded.

## Current Role

OpenJarvis is configured as the local AI agent control plane for this Mac. Its primary operational targets are OpenClaw health management and cross-project agent status visibility.

The intended split is:

- OpenJarvis: management console, local LLM control path, health dashboard, telemetry, skills, and managed agents.
- OpenClaw: runtime plane for gateway, Telegram/channel operations, local development workflows, and agent-side operational tasks.
- ATOP_Dev: agent development and operations platform. It owns ATOP agent catalog metadata, scorecards, artifacts, run ledgers, lifecycle readiness, and promotion policy.
- Ollama/Gemma4: primary local inference path.
- Legacy MLX: optional fallback/legacy path, not currently the primary runtime.

OpenJarvis observes ATOP_Dev through ATOP_Dev's own read-only manager commands. OpenJarvis reports ATOP_Dev health and performance, but ATOP_Dev remains the authority for modifying its agents.

## Core Paths

- OpenJarvis repository: `/Users/paulsunny/Documents/OpenJarvis`
- OpenJarvis config: `/Users/paulsunny/.openjarvis/config.toml`
- OpenJarvis reports: `/Users/paulsunny/.openjarvis/reports`
- Latest OpenClaw management report: `/Users/paulsunny/.openjarvis/reports/openclaw-management-latest.md`
- OpenJarvis cloud key env file: `/Users/paulsunny/.openjarvis/cloud-keys.env`
- OpenClaw workspace: `/Users/paulsunny/Documents/openclaw-workspace`
- OpenClaw home: `/Users/paulsunny/.openclaw`
- OpenClaw logs: `/Users/paulsunny/.openclaw/logs`
- ATOP_Dev repository: `/Users/paulsunny/Documents/ATOP_Dev`
- Pi model routing config: `/Users/paulsunny/.pi/agent/models.json`

## Access Points

- OpenJarvis server: `http://127.0.0.1:8000`
- React operations dashboard: `http://127.0.0.1:8000/dashboard`
- Legacy savings dashboard: `http://127.0.0.1:8000/savings-dashboard`
- OpenClaw health API: `http://127.0.0.1:8000/v1/openclaw/health`
- ATOP_Dev project-agent health: included under `project_agents.atop_dev` in `/v1/openclaw/health`
- OpenJarvis server health: `http://127.0.0.1:8000/health`
- Ollama API: `http://127.0.0.1:11434`
- Ollama OpenAI-compatible API: `http://127.0.0.1:11434/v1`
- OpenClaw Gateway: `http://127.0.0.1:18789`
- Legacy optional MLX endpoint: `http://127.0.0.1:11435/v1`

## Current OpenJarvis Config

Source: `/Users/paulsunny/.openjarvis/config.toml`

- Engine default: `ollama`
- Ollama host: `http://127.0.0.1:11434`
- MLX host retained for legacy compatibility: `http://127.0.0.1:11435`
- Default model: `gemma4-agent:e4b`
- Temperature: `0.4`
- Max tokens: `2048`
- Server host: `127.0.0.1`
- Server port: `8000`
- Server agent: `jarvis`
- Agent default in config: `jarvis`
- Agent objective: `Develop and operate local AI agents on-device with practical tool use`
- Memory context injection: enabled
- Traces: enabled at `~/.openjarvis/traces.db`
- Skills: enabled at `~/.openjarvis/skills/`
- Skill sources: Hermes and OpenClaw, both with `auto_update = false`
- Security profile: `personal`
- Digest: disabled

## Runtime Status On 2026-05-02

OpenJarvis server:

- Status: running
- PID at verification time: see `/Users/paulsunny/.openjarvis/server.pid`
- URL: `http://127.0.0.1:8000`
- Server log: `/Users/paulsunny/.openjarvis/server.log`

Server info:

- Model: `gemma4-agent:e4b`
- Agent: `jarvis`
- Engine reported by server: `ollama`

OpenClaw health API result:

- Overall status: `healthy`
- Score: `100`
- Passes: `10`
- Warnings: `0`
- Failures: `0`

Legacy MLX endpoint `127.0.0.1:11435` is intentionally inactive while Ollama/Gemma4 is the primary local runtime. OpenClaw security audit currently has no critical or warning findings in the latest report.

## OpenClaw Management Surface

OpenJarvis currently manages OpenClaw through deterministic scripts, health APIs, and the dashboard.

Primary scripts:

- `/Users/paulsunny/Documents/OpenJarvis/scripts/openclaw-health-summary.sh`
- `/Users/paulsunny/Documents/OpenJarvis/scripts/openclaw-management-check.sh`
- `/Users/paulsunny/Documents/OpenJarvis/scripts/openclaw-openjarvis-chat.sh`
- `/Users/paulsunny/Documents/OpenJarvis/scripts/pi-openclaw.sh`

Primary docs:

- `/Users/paulsunny/Documents/OpenJarvis/docs/getting-started/openclaw-management.md`
- `/Users/paulsunny/Documents/OpenJarvis/docs/getting-started/openclaw-local-mlx.md`
- `/Users/paulsunny/Documents/OpenJarvis/docs/getting-started/local-readme-setup.md`

Primary skill:

- `/Users/paulsunny/.openjarvis/skills/openclaw-runtime-ops/SKILL.md`

Health checks cover:

- OpenJarvis server availability
- Ollama availability
- `gemma4-agent:e4b` model availability
- OpenClaw Gateway port `18789`
- OpenClaw runtime fast status
- Pi coding agent routing
- Legacy MLX status
- Recent fatal gateway log signals
- Latest OpenClaw security audit summary
- ATOP_Dev managed agent scorecards

Managed operations agents:

- `openclaw-manager`: OpenClaw runtime, gateway, security-audit, and OpenJarvis integration monitor.
- `ATOP Dev Ops`: ATOP_Dev scorecard, run health, latency, artifact, and legacy/deprecated-agent monitor.
- Both use `gemma4-agent:e4b`, run every 1800 seconds, and are constrained to read-only diagnostics plus memory/reporting unless an explicit repair request is made.

## OpenJarvis and ATOP_Dev Boundary

Detailed role boundary: `/Users/paulsunny/Documents/OpenJarvis/docs/getting-started/openjarvis-atop-dev-role-boundary.md`

Operating rule:

- OpenJarvis owns cross-project visibility, local model routing, dashboarding, and system-level health checks.
- ATOP_Dev owns ATOP agent lifecycle, scorecards, artifacts, run ledgers, and promotion policy.
- OpenJarvis may read ATOP_Dev scorecards and display status.
- OpenJarvis should not rewrite ATOP_Dev agent definitions, catalog entries, scorecard rules, run ledgers, or promotion state unless explicitly requested.

## Recent Changes

OpenJarvis local model and cloud routing:

- Default runtime was aligned to Ollama/Gemma4.
- Local primary model name is standardized on `gemma4-agent:e4b`.
- OpenRouter routing was narrowed so only `openrouter/...` is treated as OpenRouter.
- Preferred OpenRouter order is Kimi K2.6, DeepSeek V4 Pro, Nemotron 3 Super, Gemini 3.1 Flash Lite Preview, Claude Sonnet 4.6.
- Local Ollama model IDs such as `gemma4-agent:e4b` are kept on the local path.
- Cloud API key saving was made more stable via backend key persistence.
- Cloud keys are stored in `/Users/paulsunny/.openjarvis/cloud-keys.env`; actual key values must not be committed or copied into notes.

OpenClaw management:

- Added fast health summary script.
- Updated full management report script to treat MLX `11435` as legacy optional.
- Added OpenClaw operations health API at `/v1/openclaw/health`.
- Added OpenClaw operations dashboard at `/dashboard`.
- Moved old savings-only HTML dashboard to `/savings-dashboard`.
- Updated OpenJarvis docs and skills to use Ollama/Gemma4 as the primary health baseline.
- Updated Pi coding agent route to `openjarvis-ollama` with model `gemma4-agent:e4b`.

Frontend dashboard:

- Added `OpenClawOpsDashboard` to show score, status, component checks, safety findings, recommended operating rules, and report path.
- Added `AgentOpsControlCenter` to show managed-agent status, stale/running/attention rollups, model, schedule, tool count, run count, and direct run/pause/resume/recover controls.
- Expanded the ATOP_Dev dashboard section with 24h run count, average success rate, no-data count, legacy/deprecated badges, last-run age, artifact basename, and latest failure text.
- Existing energy and cost panels remain below the operations dashboard.

Managed-agent safety:

- `shell_exec` now supports per-agent command allowlists.
- Allowlisted shell tools can run without generic confirmation, but only for explicitly configured commands.
- Non-allowlisted shell tools retain confirmation behavior.
- `openclaw-manager` and `ATOP Dev Ops` are configured with narrow read-only command allowlists.

## Operating Rules

- Use `scripts/openclaw-health-summary.sh` as the daily quick gate.
- Use `scripts/openclaw-management-check.sh` before restart, repair, or incident claims.
- Do not restart MLX only to clear the legacy warning unless MLX is intentionally restored as the primary local runtime.
- Keep OpenClaw tool-using sessions sandboxed when local small models are enabled.
- Avoid storing API keys or credential values in repo docs or Obsidian notes.
- Treat OpenJarvis as the control plane and OpenClaw as the runtime plane.
- Treat `shell_command_allowlist` as a safety boundary. Add only deterministic, read-only commands unless a repair workflow is explicitly approved.

## Useful Commands

```bash
cd /Users/paulsunny/Documents/OpenJarvis
uv run jarvis status
uv run jarvis restart
bash scripts/openclaw-health-summary.sh
bash scripts/openclaw-management-check.sh
curl -sS http://127.0.0.1:8000/v1/openclaw/health | python3 -m json.tool
```

## Related Files Changed In This Setup Phase

- `src/openjarvis/server/routes.py`
- `src/openjarvis/server/app.py`
- `src/openjarvis/server/cloud_router.py`
- `src/openjarvis/server/dashboard.py`
- `src/openjarvis/server/comparison.py`
- `src/openjarvis/agents/executor.py`
- `src/openjarvis/tools/shell_exec.py`
- `frontend/src/components/Dashboard/AgentOpsControlCenter.tsx`
- `frontend/src/components/Dashboard/OpenClawOpsDashboard.tsx`
- `frontend/src/pages/DashboardPage.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/types/index.ts`
- `scripts/openclaw-health-summary.sh`
- `scripts/openclaw-management-check.sh`
- `scripts/pi-openclaw.sh`
- `docs/getting-started/openclaw-management.md`
- `docs/getting-started/openclaw-local-mlx.md`
- `docs/getting-started/local-readme-setup.md`
