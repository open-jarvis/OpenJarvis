# LLM-Guided Spec Search

LLM-guided spec search (Saad-Falcon et al., 2026) is a local–cloud
collaboration: a frontier cloud *teacher* reads traces from a deployed
local agent and proposes typed edits across the agent's full
configuration; the local hardware runs the resulting configuration with
zero marginal API cost at inference time. A held-out *gate* accepts only
edits that improve a target failure cluster without unacceptable
regression elsewhere.

This page is a copy-paste tutorial. By the end you will have:

- a real `SpecSearchOrchestrator` running on your machine,
- a multi-session loop with the paper's stagnation rule (Algorithm 1),
- an understanding of which knobs to turn for production deployment.

## TL;DR — run it

```bash
python examples/openjarvis/spec_search_quickstart.py
```

The script is self-contained (no API key, no Ollama) — it wires up real
orchestrator + multi-session loop + composite-reward modules with stub
teacher/student/judge so you can see one full session and a stagnation
loop terminate. Production swap-points are commented inline; see
[Going to production](#going-to-production) below.

## How it works

A search session repeats four phases (paper §3.3):

| Phase | What happens |
|---|---|
| **Diagnose** | Teacher reads eligible traces and groups failures into clusters, each annotated with `(student_failure_rate, teacher_success_rate, skill_gap)`. |
| **Plan** | Teacher proposes typed edits across the four editable primitives (Intelligence, Engine, Agents, Tools & Memory). One proposal can edit multiple slots at once. |
| **Execute** | Each candidate edit is applied; the gate scores the resulting spec on a held-out subsample. Accepted iff `GateOK` holds (see below). |
| **Record** | Accepted edits commit to the checkpoint store; rejected edits roll back. The session is persisted to `SessionStore`. |

`SpecSearchOrchestrator.run(trigger)` runs **one** session end-to-end.
`SpecSearchLoop` (paper Algorithm 1) wraps the orchestrator and repeats
sessions until either gate-score stagnation (default *k* = 5 sessions)
or budget exhaustion.

### `GateOK` — the acceptance predicate

Let `G_c(S)` be the held-out gate score of spec `S` restricted to
failure cluster `c`. For an edit `e` targeting cluster `c`, with
`S' = apply(S, e)`:

```
GateOK(S', S, c, eps) ⟺
    G_c(S')  >  G_c(S)            # target cluster improves, AND
    G_c'(S') >= G_c'(S) − eps     # every other cluster regresses by ≤ eps
```

Default `eps = 0.01` (1 %) per the paper. The `BenchmarkGate` class
implements this; the `max_regression` knob is `eps`.

### Composite reward (Intelligence-edit training only)

When an Intelligence edit triggers LoRA / GRPO training inside the
execute phase, candidate responses `y` to query `q` are scored by
(paper Eq. 1):

```
R(q, y) = α · R_acc(q, y)
       − β · Ê(q, y)        # energy
       − γ · L̂(q, y)        # latency
       − δ · Ĉ(q, y)        # cost
```

Defaults `(α, β, γ, δ) = (0.5, 0.1, 0.1, 0.3)`. The efficiency
quantities (E, L, C) are z-scored *within batch* before weighting, so
the reward trades dimensionless deviations rather than raw joules /
seconds / dollars (paper Appendix C.6). Implementation:
`openjarvis.learning.spec_search.composite_reward.score_batch`.

The held-out gate evaluates the resulting spec end-to-end; it is
unaffected by these weights.

## Configuration

The prebuilt config lives at
`configs/openjarvis/examples/spec-search-quickstart.toml`. Copy it to
`~/.openjarvis/config.toml` (or set `OPENJARVIS_CONFIG` to it) and the
regular loader picks it up:

```python
from openjarvis.core.config import load_config
cfg = load_config().learning.spec_search   # SpecSearchLearningConfig
```

The `[learning.spec_search]` table maps 1:1 onto the
`SpecSearchLearningConfig` dataclass and is read by both
`SpecSearchOrchestrator.from_config` and `SpecSearchLoop`:

```toml
[learning.spec_search]
enabled = true
teacher_model = "claude-opus-4-6"
teacher_engine = "cloud"
autonomy_mode  = "tiered"             # auto | tiered | manual

# Per-session bounds
min_traces                   = 20
max_cost_per_session_usd     = 5.0
max_tool_calls_per_diagnosis = 30

# Multi-session loop (paper Algorithm 1)
stagnation_k        = 5               # paper default
stagnation_eps      = 0.001
max_total_cost_usd  = 50.0

# Gate (GateOK)
max_regression           = 0.01       # paper default: epsilon = 1%
min_improvement          = 0.0
benchmark_subsample_size = 50
benchmark_version        = "personal_v1"

[learning.spec_search.composite_reward]
alpha = 0.5    # accuracy
beta  = 0.1    # energy
gamma = 0.1    # latency
delta = 0.3    # cost
```

## Going to production

The quickstart uses fakes for the teacher engine, student runner, and
judge so it runs without external services. To run a real session,
swap each fake for the corresponding production component:

| Slot | Quickstart | Production |
|---|---|---|
| `teacher_engine` | `FakeTeacherEngine` | `EngineRegistry.get(cfg.teacher_engine)(model=cfg.teacher_model)` — set `ANTHROPIC_API_KEY` etc. |
| `trace_store` | `MagicMock` | `openjarvis.traces.store.TraceStore(home / "traces.db")` |
| `student_runner` | `MagicMock` | `openjarvis.learning.spec_search.student_runner.VLLMStudentRunner(host=..., model=...)` |
| `judge` | `MagicMock` | `openjarvis.evals.core.scorer.LLMJudgeScorer(...)` (or a deterministic scorer if your benchmark provides one) |
| `session_store` | `MagicMock` | `openjarvis.learning.spec_search.storage.session_store.SessionStore(home / "learning" / "sessions.db")` |
| `checkpoint_store` | `MagicMock` | `openjarvis.learning.spec_search.checkpoint.store.CheckpointStore(home / "learning" / "checkpoints")` |
| `scorer` | climbing-plateau fake | a real `Scorer` callable (typically a `BenchmarkGate.score` adapter) |

The orchestrator only depends on the *interface* of each slot, not the
concrete class — anything implementing the corresponding protocol works.

## Adding a new external corpus

Diagnose phase can ingest records from a HuggingFace-backed external
corpus. Three providers ship in-tree (`adp`, `toolorchestra`,
`generalthoughts`); to add a new one:

1. Create `src/openjarvis/evals/datasets/<corpus>.py` implementing
   `DatasetProvider` (`adp.py` is a small reference). The provider's
   `load(max_samples, seed, split)` must respect `split` via
   `apply_split` from `openjarvis.evals.core.splits`.
2. Register: `@DatasetRegistry.register("<corpus>")`.
3. Feed it to the proposer via the trace store:

```python
from openjarvis.evals.datasets.adp import ADPDataset
from openjarvis.learning.spec_search.external_adapter import (
    write_external_records_as_traces,
)
from openjarvis.traces.store import TraceStore

records = list(ADPDataset().load(max_samples=200, seed=42, split="all"))
store = TraceStore("~/.openjarvis/traces.db")
n = write_external_records_as_traces(store, records, source_name="adp")
# proposer can now filter on metadata["source"] == "adp"
```

## What runs where

At inference time, the resulting spec runs entirely on-device — model
inference, agent execution, tool invocation. Teacher API calls happen
only at search time (diagnose + plan), and only **eligible scrubbed
traces** are transmitted (per the trace-eligibility rules in your
config).

Users requiring strict local-only operation can swap a larger local
model in as the teacher; this trades search quality for zero cloud
exposure.

## Bug fix bundled with this release

`src/openjarvis/evals/backends/jarvis_agent.py` previously hardcoded
`builder.telemetry(telemetry).traces(True).build()`, ignoring the
`telemetry` parameter. This silently caused every agent-backend
evaluation to write to `~/.openjarvis/traces.db` regardless of caller
intent. A corrupt traces.db then turned every agent eval into "database
disk image is malformed" errors that the eval scorer dropped, producing
fake high accuracies from a handful of successful samples.

The one-line fix:

```python
self._system = builder.telemetry(telemetry).traces(telemetry).build()
```

Callers that previously expected traces to always be written should pass
`telemetry=True` explicitly.

## See also

- `examples/openjarvis/spec_search_quickstart.py` — runnable end-to-end demo.
- `configs/openjarvis/examples/spec-search-quickstart.toml` — prebuilt config.
- `src/openjarvis/learning/spec_search/orchestrator.py` — `SpecSearchOrchestrator` (single session).
- `src/openjarvis/learning/spec_search/multi_session.py` — `SpecSearchLoop` (Algorithm 1).
- `src/openjarvis/learning/spec_search/composite_reward.py` — paper Eq. 1.
- `src/openjarvis/learning/spec_search/gate/benchmark_gate.py` — `GateOK` predicate.
- `src/openjarvis/learning/spec_search/external_adapter.py` — corpus → trace adapter.
- `tests/learning/spec_search/test_multi_session.py`, `test_composite_reward.py` — unit tests.
- `tests/learning/spec_search/test_orchestrator.py` — full-session test with mocks.
