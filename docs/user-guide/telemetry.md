# Telemetry & Traces

OpenJarvis has two complementary observability systems: **telemetry** for per-inference metrics and **traces** for full interaction-level recording. Together, they provide comprehensive insight into system behavior and power the learning system's routing policy updates.

---

## Telemetry

The telemetry system records metrics for every inference call -- latency, token counts, cost, and energy consumption. Data is stored in SQLite and can be queried, exported, and aggregated.

### TelemetryRecord

Each inference call produces a `TelemetryRecord` with the following fields:

| Field                | Type             | Description                              |
|----------------------|------------------|------------------------------------------|
| `timestamp`          | `float`          | Unix timestamp of the call               |
| `model_id`           | `str`            | Model identifier                         |
| `engine`             | `str`            | Engine backend used                      |
| `agent`              | `str`            | Agent used (if any)                      |
| `prompt_tokens`      | `int`            | Input tokens consumed                    |
| `completion_tokens`  | `int`            | Output tokens generated                  |
| `total_tokens`       | `int`            | Total tokens (prompt + completion)       |
| `latency_seconds`    | `float`          | Wall-clock inference time                |
| `ttft`               | `float`          | Time to first token                      |
| `cost_usd`           | `float`          | Estimated cost in USD                    |
| `energy_joules`      | `float`          | Estimated energy consumption             |
| `power_watts`        | `float`          | Power draw during inference              |
| `trace_id`           | `str`            | Owning trace's id (empty for direct asks); joins to `TraceStore` for RoCS |
| `metadata`           | `dict[str, Any]` | Additional metadata                      |

### TelemetryStore

The `TelemetryStore` is an append-only SQLite database that persists telemetry records. It integrates with the event bus to capture records automatically.

```python
from openjarvis.telemetry.store import TelemetryStore
from openjarvis.core.events import EventBus

bus = EventBus()
store = TelemetryStore(db_path="~/.openjarvis/telemetry.db")
store.subscribe_to_bus(bus)

# Records are now captured automatically when TELEMETRY_RECORD events fire.
# No manual recording needed -- instrumented_generate() handles this.

store.close()
```

The store subscribes to `TELEMETRY_RECORD` events on the event bus. When the `instrumented_generate()` wrapper is used (which happens automatically in both CLI and SDK), telemetry records are published and stored without any manual intervention.

### `instrumented_generate()`

This wrapper function calls `engine.generate()` and automatically publishes telemetry events:

1. Publishes `INFERENCE_START` with model and engine info.
2. Calls the engine and measures wall-clock latency.
3. Extracts token usage from the engine response.
4. Creates a `TelemetryRecord` from the measurements.
5. Publishes `INFERENCE_END` and `TELEMETRY_RECORD` events.

All CLI commands and SDK methods use this wrapper, so telemetry is recorded transparently.

### TelemetryAggregator

The `TelemetryAggregator` provides read-only query and aggregation methods over stored telemetry data.

```python
from openjarvis.telemetry.aggregator import TelemetryAggregator

agg = TelemetryAggregator(db_path="~/.openjarvis/telemetry.db")

# Overall summary
summary = agg.summary()
print(f"Total calls: {summary.total_calls}")
print(f"Total tokens: {summary.total_tokens}")
print(f"Total cost: ${summary.total_cost:.6f}")

# Per-model breakdown
for ms in agg.per_model_stats():
    print(f"  {ms.model_id}: {ms.call_count} calls, {ms.avg_latency:.3f}s avg")

# Per-engine breakdown
for es in agg.per_engine_stats():
    print(f"  {es.engine}: {es.call_count} calls, {es.total_tokens} tokens")

# Top models by usage
top = agg.top_models(n=5)

# Export raw records
records = agg.export_records()

# Time-range filtering (Unix timestamps)
recent = agg.summary(since=1700000000.0)

# Clear all records
count = agg.clear()
print(f"Deleted {count} records")

agg.close()
```

#### Aggregation Methods

| Method              | Returns            | Description                                |
|---------------------|--------------------|--------------------------------------------|
| `summary()`         | `AggregatedStats`  | Total calls, tokens, cost, latency + per-model and per-engine breakdowns |
| `per_model_stats()` | `list[ModelStats]`  | Call count, tokens, latency, cost grouped by model |
| `per_engine_stats()`| `list[EngineStats]` | Call count, tokens, latency, cost grouped by engine |
| `top_models(n)`     | `list[ModelStats]`  | Top N models by call count                 |
| `export_records()`  | `list[dict]`        | All records as plain dictionaries          |
| `record_count()`    | `int`               | Total number of stored records             |
| `clear()`           | `int`               | Delete all records, return count           |

All query methods accept optional `since` and `until` parameters (Unix timestamps) for time-range filtering.

#### Data Classes

**ModelStats:**

| Field              | Type    | Description                    |
|--------------------|---------|--------------------------------|
| `model_id`         | `str`   | Model identifier               |
| `call_count`       | `int`   | Total inference calls          |
| `total_tokens`     | `int`   | Total tokens processed         |
| `prompt_tokens`    | `int`   | Total input tokens             |
| `completion_tokens`| `int`   | Total output tokens            |
| `total_latency`    | `float` | Sum of all latencies           |
| `avg_latency`      | `float` | Average latency per call       |
| `total_cost`       | `float` | Total cost in USD              |

**EngineStats:**

| Field           | Type    | Description                    |
|-----------------|---------|--------------------------------|
| `engine`        | `str`   | Engine identifier              |
| `call_count`    | `int`   | Total inference calls          |
| `total_tokens`  | `int`   | Total tokens processed         |
| `total_latency` | `float` | Sum of all latencies           |
| `avg_latency`   | `float` | Average latency per call       |
| `total_cost`    | `float` | Total cost in USD              |

**AggregatedStats:**

| Field           | Type               | Description                    |
|-----------------|--------------------|--------------------------------|
| `total_calls`   | `int`              | Total inference calls          |
| `total_tokens`  | `int`              | Total tokens across all models |
| `total_cost`    | `float`            | Total cost in USD              |
| `total_latency` | `float`            | Total latency in seconds       |
| `per_model`     | `list[ModelStats]`  | Breakdown by model             |
| `per_engine`    | `list[EngineStats]` | Breakdown by engine            |

### CLI Commands

```bash
# Show aggregated statistics
jarvis telemetry stats
jarvis telemetry stats -n 5          # Top 5 models only

# Export records
jarvis telemetry export              # JSON to stdout
jarvis telemetry export -f csv       # CSV to stdout
jarvis telemetry export -o data.json # JSON to file
jarvis telemetry export -f csv -o metrics.csv

# Clear all records
jarvis telemetry clear               # With confirmation prompt
jarvis telemetry clear --yes         # Without confirmation
```

For the joined telemetry × trace-feedback view (energy-weighted value per joule, per agent / model / engine), see [Return on Cognitive Spend](rocs.md).

---

## Traces

While telemetry captures per-inference metrics, the trace system records **complete interaction sequences** -- the full chain of steps an agent takes to handle a query. Traces are the primary input to the learning system.

### What is a Trace?

A `Trace` captures the entire lifecycle of handling a user query:

| Field                    | Type               | Description                                   |
|--------------------------|--------------------|-----------------------------------------------|
| `trace_id`               | `str`              | Unique identifier (auto-generated)            |
| `query`                  | `str`              | The original user query                       |
| `agent`                  | `str`              | Agent that handled the query                  |
| `model`                  | `str`              | Model used for inference                      |
| `engine`                 | `str`              | Engine backend used                           |
| `steps`                  | `list[TraceStep]`  | Ordered list of processing steps              |
| `result`                 | `str`              | Final response content                        |
| `outcome`                | `str` or `None`    | `"success"`, `"failure"`, or `None` (unknown) |
| `feedback`               | `float` or `None`  | User quality score [0, 1]                     |
| `started_at`             | `float`            | Unix timestamp when processing began          |
| `ended_at`               | `float`            | Unix timestamp when processing ended          |
| `total_tokens`           | `int`              | Total tokens across all steps                 |
| `total_latency_seconds`  | `float`            | Total latency across all steps                |
| `metadata`               | `dict[str, Any]`   | Additional metadata                           |

### Trace vs Telemetry

| Aspect         | Telemetry                              | Traces                                       |
|----------------|----------------------------------------|----------------------------------------------|
| **Scope**      | Single inference call                  | Full interaction (multiple steps)            |
| **Granularity**| Per-call metrics                       | Step-by-step sequence                        |
| **Purpose**    | Performance monitoring, cost tracking  | Learning, routing optimization, debugging    |
| **Data**       | Latency, tokens, cost, energy          | Route, retrieve, generate, tool_call, respond |
| **Storage**    | Flat table of records                  | Traces table + steps table                   |

### TraceStep

Each step in a trace records a single action the agent took.

| Field              | Type             | Description                              |
|--------------------|------------------|------------------------------------------|
| `step_type`        | `StepType`       | Type of step (see below)                 |
| `timestamp`        | `float`          | When the step occurred                   |
| `duration_seconds` | `float`          | How long the step took                   |
| `input`            | `dict[str, Any]` | Input data for the step                  |
| `output`           | `dict[str, Any]` | Output data from the step                |
| `metadata`         | `dict[str, Any]` | Additional metadata                      |

### StepType

| Type         | Description                                      | Example Input                | Example Output                     |
|--------------|--------------------------------------------------|------------------------------|------------------------------------|
| `route`      | Model/agent selection decision                   | `{"query_type": "math"}`     | `{"model": "qwen3:8b"}`           |
| `retrieve`   | Memory search for context                        | `{"query": "topic"}`         | `{"num_results": 3}`               |
| `generate`   | LLM inference call                               | `{"model": "qwen3:8b"}`     | `{"tokens": 128}`                  |
| `tool_call`  | Tool execution                                   | `{"tool": "calculator"}`     | `{"success": true}`                |
| `respond`    | Final response to the user                       | `{}`                         | `{"content": "...", "turns": 2}`   |

### TraceCollector

The `TraceCollector` wraps any `BaseAgent` to automatically record a `Trace` for every `run()` call. It subscribes to event bus events during execution and converts them into `TraceStep` objects.

```python
from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.traces.collector import TraceCollector
from openjarvis.traces.store import TraceStore
from openjarvis.core.events import EventBus

bus = EventBus()
store = TraceStore(db_path="./traces.db")

agent = OrchestratorAgent(engine, model, tools=tools, bus=bus)
collector = TraceCollector(agent, store=store, bus=bus)

# The trace is recorded automatically
result = collector.run("What is 2+2?")
print(result.content)
# Trace is now saved to the store and published on the bus
```

**How the collector works:**

1. Subscribes to `INFERENCE_START`, `INFERENCE_END`, `TOOL_CALL_START`, `TOOL_CALL_END`, and `MEMORY_RETRIEVE` events.
2. Executes the wrapped agent's `run()` method.
3. Converts captured events into `TraceStep` objects with timing data.
4. Appends a final `RESPOND` step with the result.
5. Builds a complete `Trace` object and saves it to the `TraceStore`.
6. Publishes a `TRACE_COMPLETE` event on the bus.
7. Unsubscribes from events after the run completes.

### TraceStore

The `TraceStore` is an SQLite-backed database for persisting complete traces with their steps.

```python
from openjarvis.traces.store import TraceStore

store = TraceStore(db_path="./traces.db")

# Save a trace
store.save(trace)

# Get a specific trace
trace = store.get("abc123def456")

# List traces with filters
traces = store.list_traces(
    agent="orchestrator",
    model="qwen3:8b",
    outcome="success",
    since=1700000000.0,
    limit=50,
)

# Count total traces
count = store.count()

# Subscribe to event bus for automatic saving
store.subscribe_to_bus(bus)

store.close()
```

#### Filtering Options

| Parameter | Type    | Description                              |
|-----------|---------|------------------------------------------|
| `agent`   | `str`   | Filter by agent ID                       |
| `model`   | `str`   | Filter by model ID                       |
| `outcome` | `str`   | Filter by outcome (`"success"`, `"failure"`) |
| `since`   | `float` | Start of time range (Unix timestamp)     |
| `until`   | `float` | End of time range (Unix timestamp)       |
| `limit`   | `int`   | Maximum number of traces to return (default: 100) |

### TraceAnalyzer

The `TraceAnalyzer` provides read-only aggregated statistics over stored traces. These statistics are used by the learning system to update routing policies.

```python
from openjarvis.traces.analyzer import TraceAnalyzer

analyzer = TraceAnalyzer(store=trace_store)

# Overall summary
summary = analyzer.summary()
print(f"Total traces: {summary.total_traces}")
print(f"Total steps: {summary.total_steps}")
print(f"Avg steps/trace: {summary.avg_steps_per_trace:.1f}")
print(f"Avg latency: {summary.avg_latency:.3f}s")
print(f"Success rate: {summary.success_rate:.1%}")
print(f"Step distribution: {summary.step_type_distribution}")

# Per-route statistics (model + agent combinations)
for rs in analyzer.per_route_stats():
    print(f"  {rs.model}/{rs.agent}: {rs.count} traces, "
          f"{rs.avg_latency:.3f}s avg, {rs.success_rate:.1%} success")

# Per-tool statistics
for ts in analyzer.per_tool_stats():
    print(f"  {ts.tool_name}: {ts.call_count} calls, "
          f"{ts.avg_latency:.3f}s avg, {ts.success_rate:.1%} success")

# Find traces matching query characteristics
code_traces = analyzer.traces_for_query_type(has_code=True)
short_traces = analyzer.traces_for_query_type(max_length=100)

# Export traces as plain dicts
exported = analyzer.export_traces(limit=500)
```

#### Analysis Methods

| Method                    | Returns            | Description                                          |
|---------------------------|--------------------|------------------------------------------------------|
| `summary()`               | `TraceSummary`     | Overall statistics: counts, averages, distributions  |
| `per_route_stats()`       | `list[RouteStats]` | Stats grouped by (model, agent) combinations         |
| `per_tool_stats()`        | `list[ToolStats]`  | Stats grouped by tool name                           |
| `traces_for_query_type()` | `list[Trace]`      | Filter traces by query characteristics               |
| `export_traces()`         | `list[dict]`       | Export traces as serializable dictionaries           |

All analysis methods accept optional `since` and `until` parameters for time-range filtering.

#### Data Classes

**TraceSummary:**

| Field                    | Type            | Description                              |
|--------------------------|-----------------|------------------------------------------|
| `total_traces`           | `int`           | Total number of traces                   |
| `total_steps`            | `int`           | Total steps across all traces            |
| `avg_steps_per_trace`    | `float`         | Average number of steps per trace        |
| `avg_latency`            | `float`         | Average total latency per trace          |
| `avg_tokens`             | `float`         | Average tokens per trace                 |
| `success_rate`           | `float`         | Fraction of evaluated traces that succeeded |
| `step_type_distribution` | `dict[str, int]`| Count of each step type                  |

**RouteStats:**

| Field          | Type           | Description                              |
|----------------|----------------|------------------------------------------|
| `model`        | `str`          | Model identifier                         |
| `agent`        | `str`          | Agent identifier                         |
| `count`        | `int`          | Number of traces for this route          |
| `avg_latency`  | `float`        | Average latency for this route           |
| `avg_tokens`   | `float`        | Average tokens for this route            |
| `success_rate` | `float`        | Success rate for this route              |
| `avg_feedback` | `float` or `None` | Average user feedback (if available)  |

**ToolStats:**

| Field          | Type    | Description                              |
|----------------|---------|------------------------------------------|
| `tool_name`    | `str`   | Tool identifier                          |
| `call_count`   | `int`   | Number of times the tool was called      |
| `avg_latency`  | `float` | Average execution latency                |
| `success_rate` | `float` | Fraction of successful executions        |

---

## Data Flow

The following diagram shows how telemetry and trace data flows through the system:

```
User Query
    |
    v
Agent.run()  -->  EventBus  -->  TraceCollector (captures steps)
    |                   |
    v                   v
Engine.generate()  TelemetryStore (captures per-call metrics)
    |
    v
instrumented_generate()
    |
    +---> INFERENCE_START event
    +---> INFERENCE_END event
    +---> TELEMETRY_RECORD event
    |
    v
TraceCollector
    |
    +---> Builds Trace with TraceSteps
    +---> Saves to TraceStore
    +---> Publishes TRACE_COMPLETE event
    |
    v
TraceAnalyzer / TelemetryAggregator  -->  Learning System
```

Both systems operate transparently -- no manual instrumentation is needed when using the CLI or SDK, as they automatically set up the event bus and telemetry store.
