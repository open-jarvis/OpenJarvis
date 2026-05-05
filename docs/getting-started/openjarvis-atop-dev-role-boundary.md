# OpenJarvis and ATOP_Dev Role Boundary

Last updated: 2026-05-02 KST

This machine runs both OpenJarvis and ATOP_Dev. They should complement each other without competing for the same ownership boundary.

## Operating Principle

- OpenJarvis is the local AI control plane.
- ATOP_Dev is the agent development and operations platform.
- OpenJarvis observes, routes, and summarizes ATOP_Dev status.
- ATOP_Dev owns agent lifecycle, promotion, scorecards, artifacts, and platform-specific execution policy.

OpenJarvis must not silently mutate ATOP_Dev agent state unless an explicit repair or deployment task is requested.

## Responsibility Split

| Area | OpenJarvis owns | ATOP_Dev owns |
| --- | --- | --- |
| Local LLM runtime | Ollama/Gemma4 health, cloud fallback routing, model selection UI | Model requirements for ATOP-specific agents |
| Operations dashboard | Cross-project status, health rollups, warnings, recommendations | Agent scorecards, run history, artifacts, lifecycle readiness |
| Agent management | OpenJarvis managed agents, monitors, local research helpers | ATOP platform agents, catalog metadata, deployment targets |
| Telemetry | Local inference tokens, latency, savings, OpenJarvis server health | Agent success rates, run durations, failures, platform KPIs |
| Automation | System-level checks, reminders, cross-project summaries | Agent scheduling, platform run ledgers, promotion gates |
| Repair authority | OpenJarvis server, Ollama, dashboard, routing config | ATOP agent definitions, scorecard criteria, output artifacts |

## Integration Contract

OpenJarvis should integrate with ATOP_Dev through read-first interfaces:

- `python -m atop_agent_manager list --format json`
- `python -m atop_agent_manager scorecard <agent_id> --format json`
- ATOP artifact paths surfaced as links or paths, not rewritten by OpenJarvis.

OpenJarvis may display:

- agent count
- healthy / attention / no-data count
- runs in the last 24 hours
- average success rate
- per-agent scorecard status
- latest artifact path
- latest failure status

OpenJarvis should not directly edit:

- ATOP agent catalog entries
- ATOP scorecard rules
- ATOP run ledger
- ATOP generated artifacts
- ATOP promotion or deployment state

Those changes belong to ATOP_Dev workflows.

## Specialization

Use OpenJarvis for:

- daily system health checks
- local model readiness
- OpenClaw and project status rollups
- cloud model selection and key routing
- cross-project operational summaries
- lightweight local research or code-review monitors

Use ATOP_Dev for:

- designing new platform agents
- validating agent behavior
- running agent scorecards
- promoting agents from experimental to ready
- comparing agent KPIs
- managing production-quality agent artifacts

## Managed Agent

OpenJarvis includes a managed agent named `ATOP Dev Ops` for ATOP_Dev operations visibility.

- Agent type: `monitor_operative`
- Model: `gemma4-agent:e4b`
- Schedule: every 1800 seconds
- Tools: `shell_exec`, `http_request`, `file_read`, `memory_store`, `memory_retrieve`, `think`
- Default authority: read-only inspection, status summarization, memory updates, and recommendations
- Shell command allowlist: limited to ATOP_Dev manager read commands, OpenJarvis health reads, and artifact listing

The agent monitors ATOP_Dev scorecards, run health, success rates, durations, artifacts, and legacy/deprecated agent status. It must not mutate ATOP_Dev agent definitions, scorecard rules, run ledgers, artifacts, or promotion state unless the user explicitly requests that action.

Allowed shell command families:

- `python -m atop_agent_manager list --format json`
- `python -m atop_agent_manager scorecard`
- `uv run python -m atop_agent_manager list --format json`
- `uv run python -m atop_agent_manager scorecard`
- `curl ... /v1/openclaw/health`
- read-only artifact listing under `/Users/paulsunny/Documents/ATOP_Dev/artifacts`

Commands outside this allowlist are blocked by OpenJarvis before execution. This keeps OpenJarvis useful for ATOP_Dev visibility while preventing silent mutation of ATOP_Dev state.

## Dashboard View

The OpenJarvis operations dashboard now surfaces ATOP_Dev as a project-agent performance panel. It displays:

- healthy, attention, no-data, run-count, and average success-rate summary
- per-agent scorecard status and catalog status
- legacy/deprecated markers
- last run time, last run status, latest artifact basename, and latest failure text when present

## Conflict Avoidance Rules

- If an ATOP_Dev agent is unhealthy, OpenJarvis reports it and links to scorecard evidence; it does not auto-rewrite the agent.
- If OpenJarvis model routing changes, ATOP_Dev keeps its own agent-level model requirements unless deliberately migrated.
- If both systems can schedule a task, ATOP_Dev owns ATOP agent runs; OpenJarvis owns system-level monitoring and summaries.
- If OpenJarvis detects stale ATOP data, the first action is to rerun or inspect ATOP scorecards, not to modify OpenJarvis state.

## Current Preferred Model Stack

- Local primary: `gemma4-agent:e4b` through Ollama.
- Cloud primary route: OpenRouter.
- Preferred OpenRouter order:
  1. `openrouter/moonshotai/kimi-k2.6`
  2. `openrouter/deepseek/deepseek-v4-pro`
  3. `openrouter/nvidia/nemotron-3-super-120b-a12b`
  4. `openrouter/google/gemini-3.1-flash-lite-preview`
  5. `openrouter/anthropic/claude-sonnet-4.6`
