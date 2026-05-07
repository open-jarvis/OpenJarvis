# Learning & Distillation

Use a frontier model as a meta-engineer to automatically improve your local agent's prompts, routing, and tools — reversibly, with benchmark-gated quality control.

## Quick Start

### 1. Initialize

```bash
jarvis learning init
```

This creates the distillation directory layout under `~/.openjarvis/learning/` and initializes a git checkpoint repo at `~/.openjarvis/.git` for tracking config changes.

### 2. Run your first session

Once you have at least 20 traces from regular use:

```bash
jarvis learning run
```

The system will:
1. **Diagnose** — analyze your traces using a frontier model
2. **Plan** — propose typed edits to your config
3. **Execute** — apply edits that pass the benchmark gate
4. **Record** — persist the session for history and rollback

### 3. Check results

```bash
jarvis learning history
jarvis learning show <session-id>
```

## How a Learning Session Works

A learning session has four phases:

### Phase 1: Diagnose

A frontier model (the "teacher", default `claude-opus-4-6`) analyzes your recent traces using read-only diagnostic tools. It identifies **failure clusters** — groups of related failures with shared root causes. The teacher must actually re-run your student on sample tasks and compare outputs to populate failure rates. This forces evidence-based diagnosis.

**Output:** `diagnosis.md` with narrative analysis + structured failure clusters.

### Phase 2: Plan

A second teacher call converts the diagnosis into a typed `LearningPlan` — a list of `Edit` objects, each targeting a specific part of your configuration (model routing, system prompts, tool availability, etc.). The teacher cannot pick risk tiers — those are assigned deterministically from a lookup table.

**Output:** `plan.json` frozen and immutable.

### Phase 3: Execute

Each edit is applied through its registered `EditApplier`, then scored against your personal benchmark. Edits that improve the benchmark are committed; edits that cause regressions are rolled back. Edits in the `review` tier are queued for your approval instead of being auto-applied.

**Output:** Git commits in the checkpoint repo + `EditOutcome` records.

### Phase 4: Record

The session is persisted to `learning.db` (SQLite index) and `session.json` (authoritative artifact). You can query history, show details, and rollback any session.

## Configuration

Add to `~/.openjarvis/config.toml`:

```toml
[learning.distillation]
enabled = true                          # gate the entire subsystem
autonomy_mode = "tiered"                # auto | tiered | manual
teacher_model = "claude-opus-4-6"       # any CloudEngine-supported model
max_cost_per_session_usd = 5.0          # per-session teacher API budget
max_tool_calls_per_diagnosis = 30       # max teacher tool calls in diagnosis
```

### Trigger configuration

```toml
[learning.distillation.triggers]
scheduled_enabled = true
scheduled_cron = "0 3 * * *"            # daily at 03:00 local
scheduled_min_new_traces = 20           # minimum new traces to trigger

cluster_enabled = true
cluster_check_interval_minutes = 60
cluster_min_size = 5
cluster_failure_threshold = 0.3         # feedback <= this counts as failure
```

### Gate configuration

```toml
[learning.distillation.gate]
min_improvement = 0.0                   # any improvement accepted (raise for margin)
max_regression = 0.05                   # max per-cluster score drop
benchmark_subsample_size = 50           # tasks per gate run
full_benchmark = false                  # set true to disable subsampling
```

### Benchmark configuration

```toml
[learning.distillation.benchmark]
synthesis_feedback_threshold = 0.7      # min feedback for benchmark traces
max_benchmark_size = 200                # max tasks in the benchmark
auto_refresh = true                     # auto-mine new high-feedback traces
max_synthesis_cost_usd_per_refresh = 2.0  # separate from session budget
```

### Risk tier overrides

Power users can override the default tier for any operation:

```toml
[learning.distillation.tier_overrides]
# Promote prompt edits to auto-apply after trust is established:
# patch_system_prompt = "auto"
# replace_system_prompt = "auto"
```

## Risk Tiers

Every edit is assigned a risk tier that controls how it's applied:

| Tier | Behavior | Default ops |
|------|----------|-------------|
| **auto** | Applied automatically if benchmark gate passes | Model routing, model params, tool add/remove/description, agent params |
| **review** | Queued for user approval in `jarvis learning review` | System prompt edits, agent class changes, few-shot exemplars |
| **manual** | Never auto-applied; requires explicit approval | LoRA fine-tuning (v2) |

The tier is assigned deterministically from the edit operation — the teacher cannot override it.

## Reviewing Edits

When edits land in the review queue:

```bash
# List all pending edits
jarvis learning review

# Approve an edit (still goes through the benchmark gate)
jarvis learning approve <edit-id>

# Reject an edit with a reason
jarvis learning reject <edit-id> --reason "prompt change too aggressive"
```

Even approved edits are gated by the benchmark — approval means "try it", not "force it".

## Rollback and History

Every edit creates a git commit in the checkpoint repo at `~/.openjarvis/.git`. This is separate from your OpenJarvis source repo.

```bash
# List past sessions
jarvis learning history --limit 20

# Show session details (diagnosis, plan, outcomes, cost)
jarvis learning show <session-id>

# Rollback a session (creates new revert commits, preserves history)
jarvis learning rollback <session-id>
jarvis learning rollback --last
```

Rollback never rewrites git history — it creates new revert commits so the audit trail stays intact.

## Cost Controls

Three cost boundaries prevent runaway spending:

1. **`max_cost_per_session_usd`** (default $5.00) — caps the total teacher API cost per session (diagnosis + planning).
2. **`max_synthesis_cost_usd_per_refresh`** (default $2.00) — caps the cost of generating gold answers for new benchmark tasks. Separate from the session budget.
3. **`teacher_model`** — choose a cheaper model (e.g., `claude-sonnet-4-6`) to reduce per-token costs at the expense of diagnosis quality.

Cost is tracked on every `LearningSession` as `teacher_cost_usd` and surfaced in `jarvis learning show`.

## The Personal Benchmark

The benchmark is your acceptance gate's source of truth — a set of tasks distilled from your high-quality traces, scored by an LLM-as-judge against frontier gold answers.

**How it's built:**
1. Traces with feedback >= 0.7 are candidates
2. Tasks are grouped by query class and deduplicated
3. For each task, the teacher generates a gold reference answer
4. The benchmark is versioned (`personal_v1.json`, `personal_v2.json`, ...)

**Auto-refresh:** The benchmark grows over time as you accumulate more traces. New tasks are added automatically during background refresh cycles.

```bash
# Manual refresh
jarvis learning benchmark refresh

# Show stats
jarvis learning benchmark show
```

## Cold Start: What to Expect on Day One

The system needs real usage data before it can learn:

- **< 20 traces:** `jarvis learning run` returns "Not enough traces yet." Triggers are no-ops.
- **20+ traces, < 10 high-feedback:** Enough for diagnosis, but no benchmark yet. Sessions will run diagnosis but can't gate edits.
- **10+ high-feedback traces:** Bootstrap benchmark is created automatically (`personal_v1.json`). Full learning loop is available.

**Getting there faster:** Use OpenJarvis normally and provide feedback on results (thumbs up/down in the UI, or `jarvis feedback` in the CLI).

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| "Not enough traces yet" | Fewer than 20 traces in the store | Use OpenJarvis more, provide feedback |
| "Working tree dirty, cannot stage" | Manual edits to `~/.openjarvis/config.toml` during a session | Commit or revert manual changes first |
| "All clusters dropped: insufficient evidence" | Teacher diagnosed clusters but couldn't reproduce failures | Check that the student is actually failing on the flagged tasks |
| "ConfigurationError: distillation root inside source tree" | `OPENJARVIS_HOME` points inside the repo | Set `OPENJARVIS_HOME` to `~/.openjarvis` (default) or another external dir |
| "Personal benchmark is empty" | Not enough high-feedback traces yet | Provide feedback on 10+ traces with score >= 0.7 |

## Where Artifacts Live

All distillation artifacts live under `~/.openjarvis/` (never inside the source repo):

```
~/.openjarvis/
├── config.toml              # Your configuration (git-tracked by checkpoint)
├── agents/                  # Agent prompts (git-tracked)
├── tools/                   # Tool descriptions (git-tracked)
├── .git/                    # Checkpoint repo for rollback
└── learning/
    ├── learning.db          # SQLite session index
    ├── benchmarks/          # Personal benchmark versions + gold answers
    ├── sessions/            # Per-session artifacts (diagnosis, plan, traces)
    └── pending_review/      # Edits awaiting user approval
```

## Background Daemon

For continuous learning:

```bash
jarvis learning daemon start    # Start background watcher
jarvis learning daemon status   # Check if running
jarvis learning daemon stop     # Stop the daemon
```

The daemon runs the scheduled trigger (default: daily at 03:00) and the cluster trigger (watches for failure patterns in real-time).

## See Also

- [Architecture: Learning](../architecture/learning.md#distillation-frontier-driven-harness-learning) — internal architecture of the distillation subsystem
- [User Guide: Evaluations](evaluations.md) — the eval infrastructure that powers the benchmark gate
- [User Guide: CLI](cli.md#jarvis-learning) — full CLI reference
- [Getting Started: Configuration](../getting-started/configuration.md) — all config knobs
