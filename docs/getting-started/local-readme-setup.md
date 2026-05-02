# Local README Setup

This machine uses the local Ollama/Gemma4 path as the primary OpenJarvis runtime. The older OpenClaw-hosted MLX path is treated as optional legacy infrastructure.

## Installed from README

- Core environment: `uv sync`
- Server extras: `uv sync --extra server`
- MLX extras: `uv sync --extra inference-mlx` (installed for compatibility; not the primary runtime)
- Scheduler extras: `uv sync --extra scheduler`
- Rust extension: `uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml`

## Local Runtime

- Engine: `ollama`
- Ollama host: `http://127.0.0.1:11434`
- Model: `gemma4-agent:e4b`
- Direct fast chat: `scripts/openclaw-openjarvis-chat.sh`
- Memory backend: `sqlite`
- Trace capture: enabled at `~/.openjarvis/traces.db`

## Recommended Commands

- Diagnostics:
  `jarvis doctor`
- General tool-using agent:
  `bash /Users/paulsunny/Documents/OpenJarvis/scripts/jarvis-general.sh "질문"`
- Code-focused agent:
  `bash /Users/paulsunny/Documents/OpenJarvis/scripts/jarvis-code.sh "작업 지시"`
- Research agent:
  `bash /Users/paulsunny/Documents/OpenJarvis/scripts/jarvis-research.sh "조사 질문"`
- Morning digest:
  `bash /Users/paulsunny/Documents/OpenJarvis/scripts/jarvis-digest.sh --text-only --fresh`
- Pi coding agent on the OpenClaw MLX model:
  `bash /Users/paulsunny/Documents/OpenJarvis/scripts/pi-openclaw.sh --no-session --no-context-files -p "Reply with only OK."`
- OpenClaw management check:
  `bash /Users/paulsunny/Documents/OpenJarvis/scripts/openclaw-management-check.sh`

## Local Starter Configs

These are reference configs for local model operation on this machine:

- `configs/openjarvis/examples/local-mlx-code-assistant.toml`
- `configs/openjarvis/examples/local-mlx-deep-research.toml`
- `configs/openjarvis/examples/local-mlx-morning-digest.toml`
- `configs/openjarvis/examples/local-mlx-scheduled-monitor.toml`

They are references only. The live config is still `~/.openjarvis/config.toml`.

## Built-in Agent Instances

Created managed agents:

- `local-research` (`deep_research`) via `scripts/jarvis-agent-local-research.sh`
- `code-review-watch` (`monitor_operative`) via `scripts/jarvis-agent-code-review-watch.sh`
- `agent-research-monitor` (`monitor_operative`) via `scripts/jarvis-agent-research-monitor.sh`

These agents were created in idle state only. No schedule was started automatically.

## Pi Coding Agent

Pi is installed globally as `pi` from `@mariozechner/pi-coding-agent`.

Local model routing is configured in `~/.pi/agent/models.json` with provider `openjarvis-ollama`, pointing to the local Ollama OpenAI-compatible endpoint:

- Endpoint: `http://127.0.0.1:11434/v1`
- Model: `gemma4-agent:e4b`
- Wrapper: `scripts/pi-openclaw.sh`

The legacy `openclaw-mlx` provider remains in `~/.pi/agent/models.json` for rollback, but it is not the primary health baseline unless port `11435` is intentionally restored.

Use Pi for lightweight terminal coding-agent experiments. Use OpenJarvis wrappers when you need OpenJarvis memory, skills, managed agents, or scheduler integration.

## OpenClaw Management

OpenJarvis can manage OpenClaw through the deterministic report script:

- `scripts/openclaw-health-summary.sh`
- `scripts/openclaw-management-check.sh`
- Latest report: `~/.openjarvis/reports/openclaw-management-latest.md`
- Runbook: `docs/getting-started/openclaw-management.md`
- Skill: `openclaw-runtime-ops`

Use this path before any restart or repair action. The script is read-only except for writing its report.

## Manual Follow-ups

- Google connectors still need browser auth:
  `jarvis connect gdrive`
- Morning digest audio still needs a TTS key:
  `CARTESIA_API_KEY=... jarvis digest --fresh`
- If you want automatic skill optimization later, keep using the system so traces accumulate, then run:
  `jarvis optimize skills --policy dspy`

## Installed Local Skills

- `openjarvis-dev-loop`
- `local-agent-runtime-check`
- `agent-ops-checklist`
