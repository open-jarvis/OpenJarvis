# LLM-Guided Spec Search

LLM-guided spec search is a local–cloud collaboration that uses each side
for what it does best: a frontier cloud model (the *teacher*) reads traces
from a deployed local agent and proposes typed edits across the agent's
configuration; the local hardware runs the resulting configuration with
zero marginal API cost at inference time. A held-out gate accepts only
edits that improve a target failure mode without unacceptable regression
on others.

The configuration the teacher edits is called the **spec**: a typed object
with five primitives (Intelligence, Engine, Agents, Tools & Memory,
Learning). The Learning primitive is where the search lives — it specifies
which edits are considered, how candidate specs are evaluated, and when
optimization stops.

## How it works

A search session repeats four phases:

| Phase | What happens |
|---|---|
| **Diagnose** | The teacher reads eligible traces and groups failures into clusters, each annotated with a natural-language characterization of the skill gap. |
| **Plan** | The teacher proposes typed edits across the editable primitives (Intelligence, Engine, Agents, Tools & Memory). A single proposal can edit multiple slots at once. |
| **Execute** | The candidate spec is evaluated on a held-out gate: the targeted cluster must improve, and every other cluster must regress by no more than a per-cluster tolerance. |
| **Record** | Accepted edits are committed; rejected edits are rolled back. |

The four-phase loop is implemented by the existing `jarvis learning`
command — see [Learning & Distillation](learning-distillation.md) for the
end-to-end runnable workflow, edit applier registry, and configuration
schema. This document covers the new building blocks added on top.

### Alignment with the paper

The paper's Algorithm 1 specifies a **multi-session loop** that runs
diagnose → plan → execute → record repeatedly until gate-score stagnation
(default *k* = 5 sessions) or budget exhaustion, with default per-cluster
tolerance ε = 1 %. The current `DistillationOrchestrator` runs
**one session per `jarvis learning run` invocation** (one diagnose, one
plan, one round of edits + gate decisions, one record); the per-cluster
regression check uses a default `max_regression = 0.05` (5 %).

To match the paper's defaults today:

- pass `max_regression=0.01` when constructing the orchestrator or the
  `BenchmarkGate` directly, and
- run `jarvis learning run` from a wrapper that re-invokes it until
  per-session gate-score deltas stagnate for *k* sessions.

Wiring the multi-session stagnation loop into the orchestrator natively,
plus changing the default `max_regression` to 1 %, are tracked as
follow-ups — they're not part of this PR.

## What this PR adds

### `splits.py` — deterministic train / test splits

`src/openjarvis/evals/core/splits.py` adds a small helper that takes a
list of records and a benchmark name and returns a deterministic
train / test partition. The split is keyed off a stable hash of each
record's id, so the same `(records, train_frac, seed)` always yields the
same partition. This is the substrate that makes "evaluate on
`split=test`" and "search over `split=train`" reproducible.

```python
from openjarvis.evals.core.splits import apply_split

train = apply_split(records, split="train", train_frac=0.2, seed=42)
test  = apply_split(records, split="test",  train_frac=0.2, seed=42)
all_  = apply_split(records, split="all",   train_frac=0.2, seed=42)  # passthrough
```

The `split` kwarg is now wired through every dataset provider in
`openjarvis.evals.datasets` (gaia, livecodebench, liveresearch,
liveresearchbench, pinchbench, taubench, toolcall15) so any caller that
constructs a `BenchmarkConfig` can request a particular split.

### External-corpus dataset providers

When the diagnose phase wants the teacher to reason over a broader
agent-trace corpus instead of just the local student's own traces, it
can ingest records from a HuggingFace-backed external corpus. Three
providers are included:

| Corpus | HuggingFace dataset | What it surfaces |
|---|---|---|
| `adp` | `neulab/agent-data-collection` | Multi-turn agent trajectories from AgentTuning, CodeAct, OpenHands, and others |
| `toolorchestra` | `nvidia/ToolScale` | Tool-use trajectories (the dataset underlying the ToolOrchestra paper) |
| `generalthoughts` | `natolambert/GeneralThought-430K-filtered` | A filtered reasoning-trace pool |

Each provider implements the standard `DatasetProvider.load(...)`
interface so corpus records can be loaded the same way benchmark records
are. They're labeled "NOT USED FOR EVALUATION" in their docstrings —
they exist purely to feed the proposer's diagnose phase.

### `external_adapter.py` — corpus records as synthetic traces

`src/openjarvis/learning/distillation/external_adapter.py` adapts records
from any external corpus into rows the proposer's existing trace tools
understand. The proposer reads from the SQLite TraceStore via search /
get tools; this adapter writes each `EvalRecord` as a synthetic `Trace`
with `feedback=0.5` (no ground truth) and a `source_name` tag in
metadata so multi-source diagnose runs can filter downstream.

```python
from openjarvis.evals.datasets.adp import ADPDataset
from openjarvis.learning.distillation.external_adapter import (
    write_external_records_as_traces,
)
from openjarvis.traces.store import TraceStore

records = ADPDataset().load(max_samples=200, seed=42, split="all")
store = TraceStore("~/.openjarvis/traces.db")
n = write_external_records_as_traces(store, records, source_name="adp")
# proposer's diagnose phase can now search/filter these traces by source="adp"
```

### Bug fix: agent-backend trace toggle

`src/openjarvis/evals/backends/jarvis_agent.py` previously hardcoded
`builder.telemetry(telemetry).traces(True).build()`, ignoring the
`telemetry` parameter. This silently caused every agent-backend
evaluation to write to `~/.openjarvis/traces.db` regardless of caller
intent. A corrupt traces.db then turned every agent eval into "database
disk image is malformed" errors that the eval scorer dropped, producing
fake high accuracies from a handful of successful samples.

The fix is one line — match the `JarvisDirectBackend` pattern:

```python
self._system = builder.telemetry(telemetry).traces(telemetry).build()
```

Callers that previously expected traces to always be written should pass
`telemetry=True` explicitly.

## Configuration

`jarvis learning` reads its configuration from `~/.openjarvis/config.toml`:

```toml
[learning.distillation]
enabled = true                          # gate the entire subsystem
autonomy_mode = "tiered"                # auto | tiered | manual
teacher_model = "claude-opus-4-6"       # any CloudEngine-supported model
max_cost_per_session_usd = 5.0          # per-session teacher API budget
max_tool_calls_per_diagnosis = 30       # max teacher tool calls in diagnosis
```

Gate / acceptance knobs (constructor arguments to `BenchmarkGate` and
`DistillationOrchestrator`):

| Argument | Meaning | Current default | Paper default |
|---|---|---|---|
| `max_regression` | Maximum per-cluster score drop tolerated before rejecting an edit (the ε in the paper's `GateOK`). | `0.05` (5 %) | `0.01` (1 %) |
| `min_improvement` | Minimum overall score improvement required to accept an edit. | `0.0` | (paper does not specify; uses `> 0` per `Gc(S') > Gc(S)`) |
| `n_tasks` | Number of tasks scored per gate run. | `50` | n/a (gate is per-cluster) |

Pass `max_regression=0.01` explicitly to match the paper's default. See
the *Alignment with the paper* note above for the gap between the
single-session `DistillationOrchestrator` and the paper's multi-session
loop with stagnation criterion.

Each `EditApplier` registers an autonomy tier (`auto`, `review`,
`manual`); see the
[Learning & Distillation](learning-distillation.md) doc for the per-edit
configuration schema and the registered appliers.

## What runs where

At inference time, the resulting spec runs entirely on-device — model
inference, agent execution, and tool invocation. Teacher API calls are
made only at search time, for diagnosis and edit proposal. The local
spec makes zero teacher calls at inference time.

When a frontier teacher is used, only **eligible** scrubbed traces are
transmitted (per the trace-eligibility rules in the configuration).
Users requiring strict local-only operation can swap a larger local
model in as the teacher; this trades some search quality for zero cloud
exposure.

## Why decouple primitives at all

Existing personal AI frameworks bundle agent prompts, tool descriptions,
memory configuration, and runtime settings around a specific cloud
model. Naive substitution of a local model for the cloud model collapses
accuracy because none of the surrounding configuration was tuned for the
new model. Optimizing across primitives jointly — instead of
single-primitive optimization (LoRA-only, prompt-only) — is what allows
LLM-guided spec search to recover that lost accuracy. The decomposition
into Intelligence / Engine / Agents / Tools & Memory / Learning, with
the spec as the typed configuration object, is what makes the search
space well-defined.

## Adding a new external corpus

1. Create `src/openjarvis/evals/datasets/<corpus>.py` implementing
   `DatasetProvider` (look at `adp.py` for a small reference). The
   provider's `load(max_samples, seed, split)` should respect the
   `split` kwarg via `apply_split` from `openjarvis.evals.core.splits`.
2. Register the new dataset in your local `DatasetRegistry` (typically
   via `@DatasetRegistry.register("<corpus>")` decorator on the class).
3. Use it the same way as the bundled corpora: load records, then call
   `write_external_records_as_traces(store, records, source_name="<corpus>")`
   to make them visible to the proposer's diagnose phase.

The proposer can then filter on `metadata["source"] == "<corpus>"` if
you're feeding multiple corpora into the same search session.
