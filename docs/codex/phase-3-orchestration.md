# Phase 3: Tasks, Sessions, Events, Traces, and Approvals

## Status and scope

Phase 3 connects the Phase 2 `CodexBackendRouter` to the existing OpenJarvis
control, policy, persistence, API, and UI layers. It remains an isolated
integration result, not a production or data-migration approval.

The protected sources stayed outside the implementation:

- no access to or change in the real Obsidian vault;
- no access to or change in the old `jarvis-desktop` project;
- no task, skill, note, or runtime-state migration;
- no `full_access`;
- no API-key or Responses API fallback;
- no automatic approval;
- no upstream push;
- no live browser, desktop, or external-service action.

The implementation began only after the architectural audit in
[`phase-3-integration-audit.md`](../integration/phase-3-integration-audit.md).

## Safe start

The verified starting state was:

```text
branch:   feature/codex-jarvis-orchestrator
HEAD:     0681109f3cc5f5f8edf2fd2cae964601a2fad04e
base:     1fa80d8ecd2e043cb61fdc8310f9f7ffef83698c
upstream: https://github.com/open-jarvis/OpenJarvis.git (fetch)
push:     DISABLED
worktree: clean
```

The final Phase 2 bundle was verified before Phase 3:

```text
openjarvis-phase-2-0681109f.bundle
SHA256 712F745A6934578DFE1B90B75BCCC3CC4A86ED5FE6CBC12A08ACEB476A82CB68
```

All Phase 3 tests used temporary databases, workspaces, and fakes except for
the one explicitly controlled read-only live smoke.

## Control flow

```text
User request
  -> OpenJarvis session
  -> canonical Jarvis task
  -> CodexBackendRouter
  -> Codex thread
  -> Codex turn
  -> Codex item / tool / approval
  -> canonical outcome
  -> task event + trace event
  -> local API + existing OpenJarvis UI timeline
```

OpenJarvis remains the only lifecycle, policy, approval, and persistence
authority. Codex never creates a parallel JARVIS orchestrator.

`SystemBuilder` and the normal `jarvis serve` path use the same
`build_codex_task_runtime` factory. The library query path uses Codex only
when `agent="codex"` is explicit; existing OpenJarvis agents retain their
previous behavior.

## Canonical task model

The only main states are:

```text
pending
running
waiting_approval
paused
recovering
failed
done
canceled
```

Qualified results remain separate:

```text
completed
completed_with_budget_warning
interrupted
failed
canceled
```

### Allowed transitions

| From | Allowed destinations |
| --- | --- |
| `pending` | `running`, `paused`, `canceled` |
| `running` | `waiting_approval`, `paused`, `recovering`, `failed`, `done`, `canceled` |
| `waiting_approval` | `running`, `paused`, `recovering`, `failed`, `canceled` |
| `paused` | `running`, `recovering`, `canceled` |
| `recovering` | `running`, `waiting_approval`, `paused`, `failed`, `canceled` |
| `failed` | `recovering` |
| `done` | none |
| `canceled` | none |

Every transition is a short `BEGIN IMMEDIATE` transaction that updates the
task and appends one ordered event containing time, cause, responsible
component, correlation, and idempotency key. A repeated key returns the
original transition; a conflicting reuse is rejected.

The Codex orchestrator cannot finish a task from text alone when a command,
file change, approval, interruption, budget violation, or ambiguous external
effect remains.

## Identity and correlation

`TaskIdentity` carries:

```text
task_id
session_id
correlation_id
thread_id
turn_id
item_id
approval_id
action_id
artifact_id
```

The IDs flow through API requests, the central task service, Codex contexts,
persisted thread and turn records, projected events, approval requests,
artifacts, traces, and UI payloads. UI correlation never relies on text or
process IDs.

## Canonical persistence

`TaskStore` extends the Phase 2 `CodexStateStore`, so the Codex backend and
OpenJarvis task layer use one SQLite connection and one canonical database.
The current task migration version is `6`.

SQLite settings:

```text
journal_mode = WAL
foreign_keys = ON
busy_timeout = 5000 ms
```

Canonical tables:

| Table | Purpose |
| --- | --- |
| `tasks` | canonical lifecycle, outcome, active thread/turn, risk, lane |
| `task_events` | ordered lifecycle and projected timeline |
| `task_event_sources` | source-event deduplication |
| `task_steps` | task step persistence |
| `task_sources` | external/legacy adapters without deleting old stores |
| `task_artifacts` | bounded large-output storage with SHA-256 |
| `task_approvals` | persistent exact-once approval requests and decisions |
| `task_usage` | per-turn and cumulative-thread token snapshots |
| `task_recovery_checks` | restart evidence and conservative decision |
| `codex_threads` | task/session to persistent Codex thread |
| `codex_turns` | correlated turns |
| `codex_events` | normalized source event log |
| `codex_items` | correlated item records |

The existing proactive `ApprovalStore` remains intact. It is not treated as a
second truth for Codex approvals; the existing UI endpoint aggregates both
stores through an explicit adapter.

## Event and trace projection

`CodexTaskEventProjector` maps:

```text
thread.started        thread.resumed        thread.closed
turn.started          turn.completed        turn.failed
turn.interrupted      item.started          item.delta
item.completed        plan.updated          command.started
command.output        command.completed     file_change.proposed
file_change.applied   tool.started           tool.completed
approval.requested    approval.resolved     usage.updated
error
```

Properties:

- stable per-task order;
- source-event deduplication;
- safe handling of late events;
- unknown event types become redacted errors;
- recursive credential redaction;
- bounded payloads;
- large command output stored as an artifact with only digest and preview in
  the timeline;
- schema version carried into task and trace events;
- committed events published to `EventBus`;
- `TraceStore` persists correlated `task_trace_events`.

The WebSocket endpoint replays persisted events after an `after_sequence`
watermark, then streams new EventBus events while suppressing replay/live
boundary duplicates.

## Approval broker

`PersistentApprovalBroker` is the App Server approval port. With no broker,
the backend uses the deny broker.

Each record persists:

```text
approval_id, request_id, task_id, thread_id, turn_id, item_id,
action_id, kind, exact action, target, effect, risk level, sandbox,
cwd, undo path, creation, expiry, status, user decision,
decision_id, response_id, responded_at
```

Flow:

1. persist the request before waiting;
2. move the task to `waiting_approval`;
3. show it in the existing Approval Bell;
4. accept only an authenticated local actor named `local_user`;
5. record exactly one decision ID;
6. wake the waiting App Server request;
7. claim exactly one response ID;
8. publish the resolved event and resume only through the task service.

No decision means wait; timeout means deny. A restart preserves an open
request or safely reuses an already committed decision. Duplicate equal
answers are idempotent; conflicting answers are rejected. Model text,
website text, tool output, and memory cannot grant permission. The UI offers
only **Allow once** and **Deny**, never a default “always allow”.

## Risk policy

| Level | Meaning | Sandbox | Approval | Lane |
| ---: | --- | --- | --- | --- |
| 0 | read-only | `read_only` | `deny_all` | `model_lane` |
| 1 | reversible isolated workspace change | `workspace_write` | `brokered` | `model_lane` |
| 2 | external/visible preparation | `workspace_write` | `brokered` | `interactive_lane` |
| 3 | destructive or sensitive | `workspace_write` | `brokered`, single action | `interactive_lane` |
| 4 | financial or security critical | `workspace_write` | `brokered`, never autonomous | `interactive_lane` |

Levels 1-4 require an existing explicit isolated workspace and keep `cwd`
inside it. Untrusted text can raise risk but never lower it or grant a
capability. `full_access` and model-based `auto_review` are rejected.

## Restart and recovery

Startup scans `running`, `waiting_approval`, and `recovering` tasks:

1. transition to `recovering`;
2. inspect persisted thread and last turn;
3. inspect commands, file changes, approvals, and response claims;
4. record the facts in `task_recovery_checks`;
5. expose an unambiguous read-only resume as `paused`;
6. retain `waiting_approval` when a decision/response is still pending;
7. pause any active or unmatched side effect;
8. never mark a task `done` during recovery.

Covered crash points:

- before command;
- during command;
- after command before event persistence;
- during approval;
- after allow before App Server response;
- resumable read-only thread;
- unclear workspace-write effect;
- missing thread;
- no false `done`.

## Execution lanes

`ExecutionLaneScheduler` provides:

- `model_lane`: configurable parallel capacity, default 4;
- `interactive_lane`: exclusive capacity 1.

An interactive wait or approval cannot occupy the model lane. Unit tests
hold the interactive lane and prove a model task still completes.

## Usage and budgets

Configurable values:

```text
max_turn_duration             300 s
max_steps                     100
max_input_tokens              200,000
max_output_tokens              32,000
max_total_tokens_per_task     500,000
warning_threshold                0.8
hard_limit_action             interrupt
```

The effective backend timeout and step limit are the stricter values from the
default context and budget configuration. Turn input/output and cumulative
thread input/output remain separate. Warning precedes hard limit; an early
hard breach interrupts the turn. A correct terminal result is not invalidated
by a late usage event and may become
`completed_with_budget_warning`.

The live smoke exposed and fixed the current SDK payload shape:

```text
tokenUsage.last
tokenUsage.total
```

Persisted live values after offline re-evaluation:

| Turn | Input | Output | Cumulative input | Cumulative output |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 16,068 | 11 | 16,068 | 11 |
| 2 | 16,129 | 11 | 32,197 | 22 |

Task total: `32,219` tokens.

## Local API

Read endpoints:

```text
GET /v1/tasks
GET /v1/tasks/{task_id}
GET /v1/tasks/{task_id}/timeline
GET /v1/tasks/{task_id}/usage
GET /v1/approvals/pending
GET /v1/codex/health
WS  /v1/tasks/events?task_id=...&after_sequence=...
```

Mutating endpoints:

```text
POST /v1/tasks
POST /v1/tasks/{task_id}/pause
POST /v1/tasks/{task_id}/resume
POST /v1/tasks/{task_id}/cancel
POST /v1/approvals/{approval_id}/approve
POST /v1/approvals/{approval_id}/deny
```

Every new mutation requires:

```text
X-Correlation-ID
Idempotency-Key
```

Requests are schema-validated, restricted to loopback clients, protected by
the existing API-key middleware when configured, capability-gated on the
Codex task runtime, and recorded as canonical audit events. A resume request
is persisted before execution so a network retry cannot repeat an uncertain
effect.

Health reports only redacted data:

- selected backend;
- ChatGPT authentication boolean;
- runtime and OpenJarvis versions;
- sandbox and approval mode;
- persistent-thread and App Server capability;
- explicit CLI-fallback state;
- degraded state;
- active task;
- redacted thread ID unless developer view is requested;
- open approval count;
- last error category;
- per-backend capability matrix.

Tokens, cookies, keys, `auth.json`, and raw stderr secrets are never returned.

## Existing UI integration

No independent UI was created.

- The existing Approval Bell now displays exact action, target, effect, risk,
  sandbox, undo information, **Allow once**, and **Deny**.
- The existing Agents page now includes credential-safe Codex health, recent
  canonical tasks, task status/lane/outcome, separate turn/thread usage, and
  the persisted event timeline.

## Verification

### Focused Phase 3 suite

```text
278 passed, 2 deprecation warnings
ruff: All checks passed
git diff --check: passed
```

All normal tests use fakes, temporary SQLite databases, temporary workspaces,
recorded events, and simulated restarts. They consume no Codex quota.

### Frontend

```text
npm run build: passed
vitest: 6 passed
```

The build reports only existing chunk-size/dynamic-import warnings. `npm ci`
reported 29 locked transitive audit findings (2 low, 16 moderate, 11 high);
no unreviewed `npm audit fix` was applied.

### Full hermetic OpenJarvis suite

Selector:

```text
pytest tests -n auto -q --tb=short \
  -m "not live and not cloud and not hub and not live_external \
      and not live_channel and not docker"
```

Result at the final implementation HEAD:

```text
7,258 passed
43 skipped
50 failed
10 errors
70 warnings
176.16 s
```

Phase 2 comparison:

| Result | Phase 2 | Phase 3 |
| --- | ---: | ---: |
| passed | 7,125 | 7,258 |
| skipped | 49 | 43 |
| failed | 53 | 50 |
| errors | 10 | 10 |

The remaining groups predate Phase 3: Windows/POSIX permissions and process
semantics, missing optional WhatsApp/Node and Ollama services, Windows path
fixtures, telemetry timing, and FTS temporary-directory teardown. No final
Phase 3 task, Codex, approval, API, trace, or UI test failed.

### Local server smoke

A real Uvicorn server was bound to `127.0.0.1` with a deterministic no-LLM
engine and temporary state:

```text
GET  /health                       200
POST /v1/tasks                     201
GET  /v1/tasks/{id}/timeline       200, 1 event
GET  /v1/codex/health              200
server thread stopped              true
Codex orchestrator closed          true
temporary state removed            true
```

### Controlled live Python SDK smoke

Preflight:

```text
codex login status
Logged in using ChatGPT
```

One scenario was executed with the official Python SDK, no CLI fallback,
`read_only`, `deny_all`, an empty temporary workspace, a new task ID, and an
external temporary state directory.

Turn 1:

```text
exact response: PHASE3_TURN1_OK
status: running (intentionally resumable)
timeline events: 17
workspace files: 0
workspace unchanged: true
```

The Python process was then fully stopped. A second process reopened the
database; startup recovery conservatively paused the read-only task, and the
second turn resumed the same persistent thread:

```text
exact response: PHASE3_TURN2_OK
same thread: true
thread.resumed present: true
turn.started count: 2
turn.completed count: 2
timeline events: 36
trace events: 30
final status/outcome: done/completed
workspace files: 0
workspace SHA256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
workspace unchanged: true
```

No tool, command, file write, browser, desktop action, vault access, or
external service was used.

## Runtime versions

```text
Python                    3.11.9
openai-codex              0.144.4
openai-codex-cli-bin      0.144.4
global codex-cli          0.145.0 (not used by normal runtime)
FastAPI                   0.129.0
Pydantic                  2.12.5
Uvicorn                   0.41.0
pytest                    9.0.2
pytest-xdist              3.8.0
Node.js                   24.13.1
npm                       11.8.0
```

## Phase 3 commits

```text
713713ae docs: audit OpenJarvis orchestration integration points
cf5efadc feat: add canonical task state machine
72cf8fde feat: correlate tasks sessions Codex threads and turns
fe03ab59 feat: project Codex events into OpenJarvis traces
6320dd48 feat: add persistent approval broker
68625480 feat: connect Codex router to OpenJarvis orchestration
0460d70a feat: add execution lane scheduling
1e2c68ef feat: enforce task and turn usage budgets
4f984ff7 feat: add restart recovery and idempotency
be04ba12 feat: wire Codex task runtime into local server
f91e2388 feat: expose task timeline and approval API
5e7dcea9 feat: show Codex health approvals and task timeline
1995ea3e test: stabilize task state parametrization
ebdbb542 fix: parse live Codex token usage snapshots
ab55e30f feat: expose separate turn and thread usage
```

## Files changed since Phase 2

```text
docs/integration/phase-3-integration-audit.md
docs/codex/phase-3-orchestration.md
frontend/src/components/ApprovalBell.tsx
frontend/src/components/CodexTasksPanel.tsx
frontend/src/lib/api.ts
frontend/src/pages/AgentsPage.tsx
frontend/tsconfig.tsbuildinfo
src/openjarvis/cli/serve.py
src/openjarvis/codex/app_server.py
src/openjarvis/codex/types.py
src/openjarvis/core/config.py
src/openjarvis/core/events.py
src/openjarvis/server/api_routes.py
src/openjarvis/server/app.py
src/openjarvis/server/approval_routes.py
src/openjarvis/server/task_routes.py
src/openjarvis/server/ws_bridge.py
src/openjarvis/system/builder.py
src/openjarvis/system/core.py
src/openjarvis/system/orchestrator.py
src/openjarvis/system/protocols.py
src/openjarvis/tasks/__init__.py
src/openjarvis/tasks/approval.py
src/openjarvis/tasks/budget.py
src/openjarvis/tasks/identity.py
src/openjarvis/tasks/lanes.py
src/openjarvis/tasks/orchestrator.py
src/openjarvis/tasks/policy.py
src/openjarvis/tasks/projection.py
src/openjarvis/tasks/recovery.py
src/openjarvis/tasks/runtime.py
src/openjarvis/tasks/service.py
src/openjarvis/tasks/store.py
src/openjarvis/tasks/types.py
src/openjarvis/traces/store.py
tests/codex/test_app_server_backend.py
tests/codex/test_config.py
tests/codex/test_policy.py
tests/server/test_task_routes.py
tests/server/test_ws_bridge.py
tests/tasks/__init__.py
tests/tasks/test_approval.py
tests/tasks/test_budget.py
tests/tasks/test_identity.py
tests/tasks/test_lanes.py
tests/tasks/test_orchestrator.py
tests/tasks/test_policy.py
tests/tasks/test_projection.py
tests/tasks/test_recovery.py
tests/tasks/test_state_machine.py
tests/tasks/test_store.py
tests/test_query_orchestrator.py
```

## Known limitations and Phase 4 recommendation

Known limitations:

1. The official Python SDK remains beta and pins Codex runtime `0.144.4`.
2. The global CLI is newer but remains disabled as normal-runtime fallback.
3. Interactive approval was verified with fake App Server requests; the one
   live scenario was deliberately read-only and generated no approval.
4. Browser and desktop resource adapters remain deferred to Phase 5.
5. FastAPI's existing `on_event` shutdown API emits a deprecation warning; it
   still shuts the owned runtime down correctly.
6. The locked frontend dependency tree has the npm audit findings listed
   above and should be handled as a separate reviewed dependency update.
7. The upstream Windows/optional-service failures remain tracked and are not
   caused by Phase 3.

Phase 4 may safely begin as another isolated implementation phase. This is
not approval to migrate old runtime data or to touch the real Obsidian vault.
The temporary-vault, external-state, isolated-workspace, no-`full_access`,
ChatGPT-only, explicit-approval, and no-upstream-push constraints remain.
