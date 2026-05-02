# OpenJarvis Operations Improvement Roadmap

Last updated: 2026-05-02 KST

This roadmap tracks the practical improvements for using OpenJarvis as the local AI operations control plane across OpenClaw, ATOP_Dev, and other local projects.

## Implemented First Wave

### 1. Agent Ops Control Center

Status: implemented.

Purpose:

- show all OpenJarvis managed agents in one operations panel
- expose run, pause, resume, and recover controls
- detect running, attention, and stale agents
- make model, schedule, tools, run count, and last-run age visible without opening each agent detail page

Boundary:

- controls OpenJarvis managed-agent state only
- does not edit ATOP_Dev platform agents
- does not repair OpenClaw runtime by itself

### 2. Per-Agent Shell Command Allowlist

Status: implemented.

Purpose:

- allow managed agents to run deterministic read-only diagnostics without broad shell authority
- block unexpected commands before execution
- keep non-allowlisted shell execution on the existing confirmation path

Current configured agents:

- `openclaw-manager`: OpenClaw health/report/security/runtime read commands
- `ATOP Dev Ops`: ATOP_Dev list/scorecard/artifact read commands

### 3. ATOP_Dev Performance Panel

Status: implemented.

Purpose:

- surface ATOP_Dev managed-agent scorecards inside OpenJarvis
- show health, attention, no-data, 24h runs, average success rate, latest run status, artifacts, and failures
- mark legacy/deprecated agents clearly

Boundary:

- OpenJarvis observes ATOP_Dev scorecards and artifacts
- ATOP_Dev remains the authority for agent lifecycle, promotion, scoring rules, and generated artifacts

## Next Improvement Backlog

### 4. Model Routing Policy

Define explicit routing rules for when OpenJarvis should stay on local `gemma4-agent:e4b` versus when it should recommend or request cloud routing.

Recommended policy:

- local Gemma4: routine monitoring, summarization, deterministic tool orchestration, dashboard explanation
- Kimi K2.6 or DeepSeek V4 Pro: complex planning, refactoring, incident diagnosis, multi-file reasoning
- Claude Sonnet 4.6: high-risk code review, behavior regression analysis, precise design review
- Gemini 3.1 Flash Lite Preview: low-latency cloud summarization and classification
- Nemotron 3 Super: larger analytical passes when available and cost is acceptable

### 5. Run Evidence Ledger

Create a compact ledger for each managed-agent tick:

- trigger source
- model used
- tools requested
- commands blocked by policy
- health result before and after
- artifact/report path
- final status

This would make agent behavior auditable without reading raw logs.

### 6. Health Rule Engine

Move dashboard status interpretation into explicit rules:

- warning/failure thresholds
- stale-agent threshold
- expected service ports
- optional legacy checks
- project-specific health gates

The goal is to avoid hard-coded UI interpretation and let OpenJarvis explain why a state is healthy, watch, degraded, or critical.

### 7. Incident Workflow

Add an incident object for degraded states:

- symptom
- evidence
- suspected cause
- safe next command
- owner system
- resolution note

This should support "diagnose first, repair second" operations for OpenClaw and ATOP_Dev.

### 8. Agent Template Registry

Separate placeholder/demo agents from real operational agents:

- template status
- required tools
- schedule intent
- expected data source
- promotion checklist

This prevents users from mistaking example agents for production agents.

### 9. Model Evaluation Harness

Run small repeatable evaluations against local and cloud models:

- health-summary interpretation
- tool-call selection
- code-review finding quality
- incident diagnosis accuracy
- Korean operational explanation quality

Results should feed model-routing decisions instead of relying on model reputation alone.

### 10. Operations Memory

Store only durable operational facts:

- repeated failures
- resolved root causes
- intentionally disabled legacy services
- project ownership boundaries
- known-good commands

Avoid storing noisy per-run logs in memory.
