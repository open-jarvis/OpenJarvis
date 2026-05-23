# Return on Cognitive Spend (RoCS)

`jarvis rocs` is a ledger that joins **telemetry** (joules, dollars, tokens) against **trace feedback** (your thumbs / scores) and reports the energy-weighted value delivered per joule, per bucket — agent, model, engine, or day. It's the per-installation answer to "where is my local AI actually paying off, and where is it just burning power?"

## TL;DR

```bash
jarvis rocs                       # last 7 days, grouped by agent
jarvis rocs --day --by model      # last 24h, grouped by model
jarvis rocs --month --by engine   # last 30 days, grouped by engine
jarvis rocs --since 12h --json    # custom window, machine-readable
jarvis rocs explain               # the formula + how to grade
```

## What RoCS measures

For each bucket (e.g. one agent), RoCS is:

```
RoCS = SUM(feedback × energy_joules) / SUM(energy_joules of graded calls)
```

- **Range:** `[0, 1]`. `1` means every graded joule produced a perfect outcome.
- **Energy-weighted on purpose.** A thumbs-up on a 100 J research loop counts more than a thumbs-up on a 1 J one-shot ask. The metric is asking *where your cognitive spend is paying off*, not which trace got the most stars.
- **Only graded calls contribute.** Ungraded calls are tracked alongside (so you can see how much spend is currently un-judgeable) but don't move RoCS up or down.

If no traces in the window have feedback, RoCS is shown as `—`. Grade some traces (see below) and rerun.

## Data flow

```
┌────────────────────────┐         ┌───────────────────────┐
│ TraceCollector wraps   │  sets   │  trace_id ContextVar  │
│ agent.run()            │ ──────► │  (per-task scope)     │
└────────────────────────┘         └──────────┬────────────┘
                                              │ read on every
                                              ▼ generate()/stream()
┌────────────────────────┐         ┌───────────────────────┐
│ TraceStore (traces.db) │         │ TelemetryStore        │
│   trace_id, feedback   │         │   trace_id, joules,   │
│                        │         │   cost, tokens, ...   │
└──────────┬─────────────┘         └──────────┬────────────┘
           │                                   │
           └──── compute_rocs() joins on trace_id (SQLite ATTACH)
```

The link is the `trace_id` column on `TelemetryRecord`. Every inference made inside an agent's `run()` is stamped with the owning trace's id, so the join is exact — not a fuzzy match on `(timestamp, agent, model)`.

## Grading traces

RoCS needs feedback. Three ways to grade:

```bash
# Quick — thumbs the last interaction
jarvis feedback thumbs --up --last
jarvis feedback thumbs --down --last

# Targeted — thumbs a specific trace
jarvis feedback thumbs --up <trace_id>
jarvis feedback thumbs --down <trace_id>

# Precise — score in [0.0, 1.0]
jarvis feedback score <trace_id> --score 0.8

# Bulk — let an LLM judge grade recent traces
jarvis feedback evaluate --since 7d
```

Run `jarvis feedback stats` to see how much of your trace history is currently graded.

## CLI reference

### Time window (mutually exclusive)

| Flag              | Window           |
|-------------------|------------------|
| `--day`           | last 24 hours    |
| `--week`          | last 7 days (default) |
| `--month`         | last 30 days     |
| `--since DURATION`| custom, e.g. `12h`, `3d`, `90m` |

### Grouping

```
--by {agent,model,engine,day}     # default: agent
```

- `agent` — answer "which of my agents earns its keep?"
- `model` — answer "which local model wins per joule?"
- `engine` — answer "Ollama, vLLM, or Pearl?"
- `day` — daily timeseries, useful with `--month`

### Other flags

```
--top N        # cap rows in the per-bucket table (default 10)
--json         # emit JSON instead of the rich table — for scripts
```

### Subcommands

```bash
jarvis rocs explain     # prints the formula + how to grade
```

## Reading the output

`jarvis rocs` prints two pieces:

1. **Throughput Ledger panel** — the totals for the window: total energy, cost, completion tokens, trace count, % graded, and the overall RoCS.
2. **Per-bucket table** — one row per agent/model/engine/day, sorted by total energy spent. Columns:

| Column           | Meaning                                                  |
|------------------|----------------------------------------------------------|
| Bucket           | The agent / model / engine / day                         |
| Traces           | Trace count in the window                                |
| Graded %         | Percentage of traces with feedback                       |
| RoCS             | Energy-weighted feedback per joule (the metric)          |
| Energy           | Total joules (with Wh in parentheses past 1 Wh)          |
| Cost             | Total USD                                                |
| J / trace        | Mean joules per trace — your "thinking cost" per task    |
| Ungraded calls   | Engine calls in the window that have no trace_id at all  |

When at least two buckets have graded data, the footer also highlights the best and worst RoCS — that's usually where the next improvement is hiding.

### The `(direct ask)` bucket

Engine calls made *outside* a `TraceCollector` scope have an empty `trace_id`. They get rolled into a single `(direct ask)` bucket so you can see how much un-attributed compute you're spending. They never contribute to RoCS — they have no owning trace, so no feedback to weight by.

## Programmatic use

```python
from openjarvis.telemetry.aggregator import TelemetryAggregator

agg = TelemetryAggregator("~/.openjarvis/telemetry.db")
try:
    overall = agg.compute_rocs_overall("~/.openjarvis/traces.db")
    per_agent = agg.compute_rocs(
        "~/.openjarvis/traces.db",
        since=overall_start_ts,   # unix timestamp; None for all-time
        group_by="agent",
    )
finally:
    agg.close()

print(overall.rocs, overall.total_energy_joules)
for row in per_agent:
    print(row.bucket, row.rocs, row.joules_per_trace)
```

`compute_rocs()` and `compute_rocs_overall()` use SQLite `ATTACH DATABASE` to perform the join inside the engine — no Python-side row-by-row matching. Multiple sequential calls are safe; the `_attach_traces_db()` context manager handles `ATTACH`/`DETACH` so they don't conflict.

### `RoCSRow` fields

| Field                        | Type    | Notes                                              |
|------------------------------|---------|----------------------------------------------------|
| `bucket`                     | `str`   | The agent / model / engine / day label             |
| `traces_count`               | `int`   | Distinct traces in the bucket                      |
| `graded_count`               | `int`   | Traces with non-null feedback                      |
| `ungraded_calls`             | `int`   | Engine calls without a `trace_id`                  |
| `total_energy_joules`        | `float` | Sum of joules in the bucket                        |
| `graded_energy_joules`       | `float` | Sum of joules belonging to graded traces           |
| `weighted_value_joules`      | `float` | Numerator: `SUM(feedback × energy_joules)`         |
| `total_cost_usd`             | `float` | Sum of cost in the bucket                          |
| `total_completion_tokens`    | `int`   | Sum of completion tokens                           |
| `rocs`                       | `float` | The metric (property)                              |
| `pct_graded`                 | `float` | `graded_count / traces_count` (property)           |
| `joules_per_trace`           | `float` | `total_energy_joules / traces_count` (property)    |

## Troubleshooting

**"No telemetry database at …"** — RoCS reads `telemetry.db`. Run some agent calls first (any preset works), then come back.

**"traces.db not found at …"** — RoCS still runs, but treats every call as ungraded. Wrap your agent in a `TraceCollector` (the CLI does this for you under `jarvis ask`, `jarvis digest`, etc.) so traces get recorded.

**RoCS is `—` everywhere** — you have traces but no feedback. Grade some with `jarvis feedback thumbs --up --last` or `jarvis feedback evaluate --since 7d`.

**A bucket shows all spend in `(direct ask)`** — those calls aren't running inside a `TraceCollector` scope, so they have no `trace_id` and can't be graded. If you want them counted, route them through an agent or a `trace_scope()` block. See the [Telemetry & Traces](telemetry.md) page for how `TraceCollector` wraps an agent.

## Background

From the *Solve Everything* manifesto, the framing this metric is built around:

> "If you cannot prove that every dollar of electricity you burn is generating a verified unit of intelligence, you are functionally bankrupt."

RoCS is the local-AI version of that test. Watch it over time and you'll see which agents are pulling their weight per joule and which are just expensive.
