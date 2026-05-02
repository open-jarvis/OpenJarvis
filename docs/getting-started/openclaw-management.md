# OpenClaw Management From OpenJarvis

OpenJarvis is the management layer for OpenClaw on this machine. OpenClaw remains the runtime layer for gateway, local development, Telegram/channel bridges, and OpenClaw operations. The current primary local LLM path is Ollama/Gemma4 on port `11434`; the older MLX path on port `11435` is optional legacy infrastructure unless explicitly restored.

## Console Status

OpenJarvis includes:

- CLI management via `jarvis ...`
- API server via `jarvis serve`
- Browser frontend under `frontend/`
- Desktop/Tauri app under `desktop/`
- dashboard, agents, logs, settings, and data-source pages in the frontend

OpenJarvis does not currently provide an OpenClaw-specific management console out of the box. The current OpenClaw management surface is the deterministic CLI/report harness in `scripts/openclaw-health-summary.sh` and `scripts/openclaw-management-check.sh`.

Start the generic OpenJarvis console/API server with:

```bash
jarvis start
```

On this machine it is currently served at:

```text
http://127.0.0.1:8000
```

## Source Of Truth

- OpenJarvis config: `~/.openjarvis/config.toml`
- OpenJarvis local setup notes: `docs/getting-started/local-readme-setup.md`
- OpenClaw workspace: `/Users/paulsunny/Documents/openclaw-workspace`
- OpenClaw home: `/Users/paulsunny/.openclaw`
- OpenClaw logs: `/Users/paulsunny/.openclaw/logs`
- Primary local LLM endpoint: `http://127.0.0.1:11434/v1`
- Primary local LLM model: `gemma4-agent:e4b`
- Legacy optional MLX endpoint: `http://127.0.0.1:11435/v1`
- OpenClaw gateway port: `18789`

## Required Checks

Run the fast summary before claiming OpenClaw is healthy:

```bash
bash /Users/paulsunny/Documents/OpenJarvis/scripts/openclaw-health-summary.sh
```

Run the full evidence report before restart or repair work:

```bash
bash /Users/paulsunny/Documents/OpenJarvis/scripts/openclaw-management-check.sh
```

The latest report is written to:

```text
/Users/paulsunny/.openjarvis/reports/openclaw-management-latest.md
```

## Safe Management Levels

- Read-only: status, logs, endpoints, ports, model list, smoke tests.
- Assisted recovery: suggest exact restart or repair command after evidence.
- Controlled execution: run a restart only when explicitly requested or when a pre-approved automation has a narrow condition.
- Prohibited by default: deleting caches, deleting models, editing credentials, changing launchd plists, destructive git commands, and broad file cleanup.

## First Operating Loop

1. Run `openclaw-management-check.sh`.
2. Read the report summary and recent log signals.
3. If the local LLM path is unhealthy, verify Ollama and `gemma4-agent:e4b` before changing OpenClaw.
4. If gateway is unhealthy, use OpenClaw's own gateway restart path and re-run gateway probes.
5. Store important incidents in OpenJarvis memory after diagnosis.
6. Convert repeated incidents into a skill, check, or guardrail.

## Managed Agent

OpenJarvis includes a managed agent named `openclaw-manager` for OpenClaw operations.

- Agent type: `monitor_operative`
- Model: `gemma4-agent:e4b`
- Schedule: every 1800 seconds
- Tools: `shell_exec`, `http_request`, `file_read`, `memory_store`, `memory_retrieve`, `think`
- Default authority: read-only diagnostics, memory updates, and recommendations
- Shell command allowlist: limited to deterministic health/report scripts and read-only inspection commands

The agent should use the deterministic scripts above as its evidence source. It must not restart daemons, edit OpenClaw config, delete files, or run repair commands unless the user explicitly requests that action.

Current allowed shell command families:

- `bash /Users/paulsunny/Documents/OpenJarvis/scripts/openclaw-health-summary.sh`
- `bash /Users/paulsunny/Documents/OpenJarvis/scripts/openclaw-management-check.sh`
- `curl ... /v1/openclaw/health`
- `openclaw security audit --json`
- `openclaw runtime status --fast --json`
- `lsof`, `ps`, and `launchctl list` read-only inspection

Commands outside this per-agent allowlist are blocked by the `shell_exec` tool before execution.

## Recommended Next Console Work

Build an OpenClaw-specific page on top of the existing OpenJarvis frontend. The first page should display:

- Local LLM endpoint health
- OpenClaw gateway health
- LaunchAgent/LaunchDaemon state
- latest management report
- recent error signals
- safe action buttons for smoke test and restart proposal

Avoid adding destructive action buttons until the read-only dashboard is stable.

## Current Console Additions

The operations dashboard now includes an Agent Ops Control Center above the OpenClaw health panel. It is intended for control-plane visibility, not for editing project-owned agents directly.

The control center shows:

- managed-agent status, model, schedule, tool count, run count, and last-run age
- running, attention, and stale-agent rollups
- direct `Run`, `Pause`, `Resume`, and `Recover` controls for OpenJarvis managed agents

Use `Recover` only for stuck OpenJarvis managed-agent execution state. It does not repair OpenClaw itself and does not change ATOP_Dev agent definitions.
