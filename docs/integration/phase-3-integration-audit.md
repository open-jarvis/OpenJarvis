# Phase 3 integration audit

Date: 2026-07-30

This audit was completed before any Phase 3 production-code change. The
repository was inspected at:

```text
branch: feature/codex-jarvis-orchestrator
HEAD:   0681109f3cc5f5f8edf2fd2cae964601a2fad04e
```

The legacy `jarvis-desktop` project and the real Obsidian vault were not
accessed. Phase 3 remains an isolated integration phase.

## Executive decision

OpenJarvis remains the only orchestration, policy, persistence, and approval
authority. The Phase 2 `CodexBackendRouter` is a transport selector, not a
second orchestrator.

The Phase 3 integration will add one canonical task service backed by one
transactional runtime store. That store will extend the existing Phase 2
Codex state database rather than creating a competing Codex-only database.
It will own task state, identity correlation, task events, approvals,
artifacts, sources, and the Codex thread/turn/item references needed for safe
recovery.

Existing OpenJarvis domain stores are not deleted:

- `sessions.SessionStore` remains the canonical conversation-session adapter;
- `AgentManager.agent_tasks` remains a managed-agent compatibility view;
- `SchedulerStore.scheduled_tasks` remains schedule-definition persistence;
- A2A tasks remain an external protocol representation;
- the existing trace tables remain the interaction-summary store;
- the proactive-agent approval tables remain a legacy domain store.

Adapters will link these domain records to the canonical Jarvis task ID. They
must not independently decide the canonical task state.

## Existing component inventory

| Area | Existing implementation | Audit finding | Phase 3 disposition |
| --- | --- | --- | --- |
| Top-level composition | `openjarvis.system.builder.SystemBuilder`, `openjarvis.system.core.JarvisSystem` | Already centralizes engine, bus, security, traces, sessions, schedulers, and managers. It has no Codex runtime fields. | Extend the builder and `JarvisSystem` with the canonical task service, Codex router, approval broker, lane scheduler, and recovery coordinator. |
| Query orchestration | `openjarvis.system.orchestrator.QueryOrchestrator` | Synchronous engine/agent path. It constructs registered agents and preserves existing tool and trace behavior. | Add an explicit Codex route that delegates to the canonical task service. Do not replace the existing engine or agent paths. |
| Tool-using agent | `openjarvis.agents.orchestrator.OrchestratorAgent` | Existing synchronous model/tool loop. A final text response currently ends the agent run. | Leave its semantics unchanged. Codex execution is a sibling backend route controlled by the task service, not a rewrite of this agent. |
| Managed agents | `openjarvis.agents.manager.AgentManager` | WAL and foreign keys are enabled. `agent_tasks` has free-form status, no transition service, no update timestamp, no idempotency key, and no task event transaction. Checkpoints recover an agent tick, not a Codex turn. | Keep managed-agent CRUD. Add an adapter/source link to canonical tasks. Managed-agent code may request a transition but may not write canonical state directly. |
| Managed-agent execution | `openjarvis.agents.executor.AgentExecutor`, `openjarvis.agents.scheduler.AgentScheduler` | Background tick execution, activity events, budgets, stale-tick handling, and checkpoints already exist. Scheduling is thread based and has no named resource lanes. | Reuse lifecycle signals and checkpoint concepts. Route Codex work through the new lane scheduler; do not overload managed-agent status as task status. |
| Scheduled work | `openjarvis.scheduler.scheduler.TaskScheduler`, `openjarvis.scheduler.store.SchedulerStore` | Persists schedule definitions and run logs. Status vocabulary is `active`, `paused`, `cancelled`, `completed`. It directly calls `system.ask`. Store does not enable WAL or foreign keys and uses `INSERT OR REPLACE`. | Keep it as a schedule-definition store. Each execution creates or references a canonical task. Map schedule state separately; never reinterpret a schedule record as the canonical execution task. |
| Operators/proactive tasks | `openjarvis.operators.manager.OperatorManager`, `openjarvis.agents.proactive_agent` | Operators create deterministic scheduler entries. The proactive agent can auto-approve trivial or remembered actions. | Preserve legacy behavior outside Codex for compatibility, but do not connect its permission memory or text parser to Codex. Future policy unification is deferred. |
| Conversation sessions | `openjarvis.sessions.session.SessionStore` | Persistent cross-channel session identity and messages in `sessions` and `session_messages`. It does not set WAL or foreign keys explicitly and orders messages only by timestamp. | Use as the canonical conversation-session adapter. Extend or adapt it to the runtime store with stable message order and task links. Do not duplicate message history in the task service. |
| Server channel sessions | `openjarvis.server.session_store.SessionStore` | A second store in the same default `sessions.db`, using `channel_sessions` with JSON history and notification/pagination state. | Treat as a channel delivery/UI cache, not canonical conversation history. Add an adapter to resolve its sender/channel pair to a canonical session ID. Do not delete it in Phase 3. |
| A2A tasks | `openjarvis.a2a.protocol.A2ATask` and `TaskState` | In-memory external protocol model with submitted/working/input-required/completed/canceled/failed states. | Map A2A state to and from canonical tasks at the boundary. Do not make A2A state the persistence authority. |
| Event bus | `openjarvis.core.events.EventBus` | Thread-safe synchronous pub/sub, optional in-memory history, enum-based taxonomy, no persistence or replay. Subscribers run in the publisher thread. | Reuse for live projection only. Add task/Codex lifecycle categories and publish only after the canonical event transaction commits. Streaming must read persisted history first, then subscribe. |
| Trace collection | `openjarvis.traces.collector.TraceCollector` | Builds one complete `Trace` around synchronous agent runs and captures inference/tool events. It may include large raw tool results. | Preserve existing agents. Add a Codex/task event projector; do not force asynchronous Codex turns through `TraceCollector.run`. |
| Trace persistence | `openjarvis.traces.store.TraceStore` | WAL-backed summary traces plus ordered steps. Foreign keys are not explicitly enabled. `save` is whole-trace insert and is not an event timeline. | Extend with an idempotent task-event projection or adapter keyed by canonical event ID. Large outputs are represented by artifact references. The canonical task event remains the source for recovery. |
| Phase 2 Codex state | `openjarvis.codex.store.CodexStateStore` | WAL, foreign keys, correlation uniqueness, thread/turn/event tables, atomic per-thread sequence. It explicitly states that it is not the Phase 3 task store. It lacks migrations, tasks, items, approvals, artifacts, sources, task-wide sequence, and recovery decisions. | Evolve this database into the canonical Phase 3 runtime store with a migration-version table and compatibility methods for Phase 2 backends. Avoid a second Codex state database. |
| Phase 2 event normalization | `openjarvis.codex.events.CodexEventAdapter` | Covers the required Codex taxonomy, redacts payloads, preserves an allocated sequence, and deduplicates explicit event IDs. Derived IDs contain random entropy, payloads are not bounded, and sequence allocation happens before duplicate insertion. | Reuse the taxonomy and redaction entry point. Move final ordering/deduplication into the canonical transaction, add stable source-event identity, late-event handling, payload bounds, item persistence, and artifact offload. |
| Phase 2 router/backends | `openjarvis.codex.router`, `sdk_backend`, `app_server`, `cli_backend` | Python SDK is preferred; App Server exposes full approvals; CLI is explicitly degraded. Backend stores currently update thread/turn status independently of a Jarvis task. Phase 2 policy only accepts deny-all. | Reuse the backends and router. The task service owns Jarvis status and derives backend policy for every turn. Expand the validated Phase 2 policy to brokered per-request approval without allowing `full_access` or API-key/Responses fallback. |
| Phase 2 approval port | `openjarvis.codex.approval.ApprovalBroker` | Correct asynchronous port with safe deny broker. The current request contains only backend IDs and a redacted payload. | Implement a persistent OpenJarvis broker behind this port. It must persist before waiting, resolve once, survive restart, default deny without a broker, and never accept `acceptForSession`. |
| Legacy approvals | `openjarvis.tools.approval_store.ApprovalStore` | WAL-backed queue plus permission memory. Supports `always_approve`, trivial auto-execution, free-text decisions, `approve all`, and mutable status without compare-and-set. | Do not use this store as the Codex broker. Provide a compatibility read adapter for the existing Approval Bell if needed. Codex approvals use the canonical store and exact approval IDs only. |
| Server/API | `openjarvis.server.app.create_app`, `api_routes`, `agent_manager_routes`, `approval_routes` | FastAPI dependencies live in `app.state`. Existing managed-task and approval mutation endpoints have no correlation/idempotency headers or canonical transition checks. Local API-key middleware and WebSocket authentication exist. | Inject Phase 3 services through `app.state`; add a dedicated task router and broker-backed approval endpoints. Enforce local binding, authentication/capability checks, correlation and idempotency for mutations, and audit events. |
| Live events | `openjarvis.server.ws_bridge` | Authenticated WebSocket bridge forwards selected ephemeral EventBus events using bounded per-client queues. It cannot replay persisted events and currently filters by agent ID. | Reuse the authenticated transport pattern. Task timeline streaming is task/correlation filtered and resumes from a persisted sequence cursor. |
| Web/desktop UI | React frontend and Tauri shell; `ApprovalBell`, Agents page, trace debugger | Existing Approval Bell offers approve/deny but displays only legacy action type, description, tier, and JSON payload. | Extend the existing UI instead of adding a second application. Display action, target, effect, numeric risk, sandbox, expiry, allow, and deny. Do not offer “always allow”. Add task status/timeline and credential-safe backend health. |
| Security/policy | `openjarvis.security.capabilities`, sandbox setup, audit logger | Existing capability policy protects OpenJarvis tools but is not yet the source for Codex sandbox/approval settings. | Add one central risk/policy derivation service. Only it can derive Codex sandbox and approval mode. Model output, websites, memory, and tool output are untrusted inputs. |

## Overlapping stores and canonical ownership

### Tasks

There are currently three meanings of “task”:

1. `agent_tasks`: work assigned to a managed agent;
2. `scheduled_tasks`: recurring/once schedule definitions;
3. `A2ATask`: an external A2A protocol object.

None satisfies the Phase 3 state, identity, event, recovery, or idempotency
requirements. The canonical Phase 3 task record will therefore live in the
evolved runtime database. Existing records become task sources:

```text
canonical task
  <- source(kind=managed_agent_task, source_id=agent_tasks.id)
  <- source(kind=schedule_run, source_id=scheduled_tasks.id + run identity)
  <- source(kind=a2a, source_id=A2ATask.id)
  <- source(kind=local_api, source_id=request/idempotency identity)
```

The source stores retain their domain state. An adapter maps it to a canonical
request and observes the canonical outcome; it never performs a direct
canonical transition.

### Sessions

`openjarvis.sessions.SessionStore` is the canonical conversation identity and
message-history interface. `openjarvis.server.session_store.SessionStore` is
limited to channel delivery state (notification preference, `/more` pending
response, and a bounded UI history cache). A channel-session adapter resolves:

```text
(sender_id, channel_type) -> canonical session_id
```

The task runtime persists only the `session_id` foreign key and task-specific
correlation. It does not create a third conversation history.

### Codex state and task events

The Phase 2 `codex_state.db` becomes the Phase 3 runtime database. A schema
migration adds:

- schema migrations;
- canonical tasks and task steps;
- stable task-wide event order;
- Codex items;
- approvals and one-time responses;
- artifacts;
- task sources;
- idempotency records;
- usage/budget snapshots;
- recovery facts and decisions.

The existing `codex_threads`, `codex_turns`, and `codex_events` APIs remain
available to the backends during migration, but all new writes participate in
canonical task transactions. A single task event is the recovery authority.
EventBus and TraceStore are projections, not competing truth.

### Approvals

The proactive-agent `ApprovalStore` cannot be safely promoted to the Codex
authority because its designed behavior includes remembered permission,
trivial auto-approval, free-text approval parsing, bulk decisions, and
`INSERT OR REPLACE`.

The persistent Phase 3 broker uses the canonical runtime database and exact
opaque IDs. The existing Approval Bell is reused through new broker endpoints;
legacy proactive approvals can remain visible through a compatibility
adapter, clearly marked as a different source.

## Canonical execution path and router attachment

The attachment point is the system composition layer, not the tool-using
agent loop:

```text
local API / channel / scheduler / managed-agent adapter
  -> canonical TaskService
     -> SessionStore adapter
     -> central risk and capability policy
     -> execution-lane scheduler
     -> CodexTaskOrchestrator
        -> CodexBackendRouter
           -> Python SDK (normal persistent/read-only turns)
           -> App Server (interactive command/file approvals)
           -> CLI fallback (disabled by default, degraded read-only only)
        -> canonical event transaction
           -> EventBus live projection
           -> TraceStore projection
           -> task timeline/API stream
```

`SystemBuilder` constructs these optional services only when
`config.codex.enabled` is true. `JarvisSystem` owns their lifecycle and closes
them in dependency order. `QueryOrchestrator` receives an explicit Codex route
and delegates; it does not make task transitions itself.

The `CodexTaskOrchestrator` is an adapter between the canonical task service
and the Phase 2 transport protocol. It:

1. obtains the canonical task/session/correlation context;
2. derives sandbox and approval requirements from central policy;
3. selects the eligible backend through `CodexBackendRouter`;
4. starts or resumes the persisted backend thread;
5. starts the turn and consumes its event stream;
6. persists each normalized event before projecting it;
7. requests state changes only through `TaskService`;
8. evaluates terminal safety facts before requesting `done`.

It is not a general JARVIS orchestrator and cannot bypass OpenJarvis policy.

## Existing agents remain compatible

The default engine path and all registered OpenJarvis agents continue to use
the current synchronous `QueryOrchestrator` behavior. No existing agent name
is silently reinterpreted as Codex.

Codex is selected only by an explicit configured route or a canonical task
request whose execution backend is `codex`. When Codex is disabled or
unavailable, existing agents continue unchanged. There is no automatic
API-key/Responses fallback and no silent CLI fallback.

Existing `TraceCollector`, tool execution, managed-agent scheduler, operator
schedules, and channel message flow remain intact. Their later adoption of the
canonical task service happens through adapters, not a flag-day migration.

## Event, trace, and timeline projection

The canonical event transaction assigns a monotonically increasing
`task_sequence` and, where applicable, a `turn_sequence`. It stores:

- schema version and stable event/source IDs;
- all correlation IDs;
- component, cause, timestamp, and redacted bounded payload;
- an optional artifact reference.

After commit, a projector publishes a compact event to EventBus and appends an
idempotent observability projection to TraceStore. A failed projection is
retryable and does not roll back the canonical event. The UI/API reads
persisted events by sequence and then tails committed EventBus events, so a
restart or slow client does not create a timeline gap.

Large command output is written as a bounded artifact with digest, media type,
size, and storage reference. Timeline and trace payloads carry only preview,
digest, truncation marker, and `artifact_id`.

Unknown Codex events become redacted `error` records. Late events are stored
with their ingestion order and original occurrence time, but cannot reverse a
terminal task state. Duplicate source-event IDs are ignored transactionally.

## Approval integration

The App Server's `ApprovalBroker.resolve` call is connected to the persistent
OpenJarvis broker. The broker records task/thread/turn/item/action identity,
exact action, target, user-readable effect, risk level, sandbox, working
directory, undo information, timestamps, expiry, status, decision, and
one-time response identity before it waits.

Rules:

- missing broker: deny;
- no decision: remain waiting;
- expiry: deny;
- restart: recover the pending record or safely deny;
- repeated request ID: return the one persisted decision/response;
- repeated user response: no second response and no second execution;
- no model text, website content, memory, or tool output can call the decision
  path;
- no session-wide or “always allow” Codex decision is accepted.

The canonical task enters `waiting_approval` through `TaskService`. A resolved
approval does not itself mark the task done; it only makes a guarded resume
eligible.

## Scheduler and execution lanes

The existing schedulers do not model exclusive resources. Phase 3 will add a
small lane scheduler owned by the task runtime:

- `model_lane`: bounded concurrent Codex reasoning, read-only analysis, and
  background planning;
- `interactive_lane`: exclusive visible UI resources and future browser or
  desktop control.

An approval wait releases the execution slot while preserving the task/turn
wait record. A blocked interactive job therefore cannot exhaust the model
lane. Existing scheduled tasks create canonical executions and then submit to
the appropriate lane; their schedule definitions remain in `SchedulerStore`.

Phase 3 implements the lane architecture and fake-resource tests only. Real
browser and desktop side effects remain deferred to Phase 5.

## API and UI reuse points

New task endpoints are mounted through `include_all_routes` and obtain their
service from `app.state`. Mutating endpoints require:

- validated Pydantic input;
- authenticated local request;
- correlation ID;
- idempotency key;
- central capability check;
- canonical audit event.

The existing authenticated WebSocket pattern is reused for task events with a
persisted sequence cursor. The existing React/Tauri application gains task
timeline, backend health, and richer Approval Bell views. No independent web
application or approval daemon is introduced.

Health output is built from `CodexBackendRouter.health`, configuration, task
service, and broker state. It exposes only credential-safe status: active
backend, ChatGPT login boolean, runtime version, sandbox, approval mode,
persistent-thread/App-Server availability, CLI fallback configuration,
degraded state, redacted thread identity, active task, pending count, and last
error category.

## Changes deliberately deferred

The following are intentionally not part of the first Phase 3 implementation:

- migration or cleanup of the legacy `jarvis-desktop` project;
- access, renaming, reordering, or cleanup of the real Obsidian vault;
- migration of existing managed-agent, scheduler, channel-session, proactive
  approval, A2A, task, skill, or runtime data;
- deletion or physical consolidation of existing SQLite tables;
- changing legacy proactive-agent permission-memory behavior;
- replacing existing OpenJarvis agents with Codex;
- API-key or Responses-API integration;
- `full_access`;
- automatic, remembered, bulk, model-generated, or website-generated Codex
  approvals;
- real browser, desktop, mouse, or external-service side effects;
- upstream push;
- broad UI redesign;
- production deployment.

The legacy cloud engine's Codex/Responses code path is explicitly outside this
integration and must not be selected as a fallback.

## Implementation sequence after this audit

1. Add the canonical task state machine, transition service, migration table,
   and transactional task events.
2. Add session/source/correlation records and adapters without migrating
   legacy data.
3. Wire `SystemBuilder`, `JarvisSystem`, and `QueryOrchestrator` to an optional
   `CodexTaskOrchestrator`.
4. Make Codex event persistence canonical; add EventBus, TraceStore, artifact,
   and timeline projections.
5. Add the persistent broker, central risk policy, safe App Server approval
   bridge, and existing-UI/API integration.
6. Add recovery facts/decisions, execution lanes, and separate turn/task usage
   budgets.
7. Add task/timeline/approval/health APIs and frontend views.
8. Verify with fakes, temporary databases/vaults/workspaces, restart
   simulations, the full suite, server startup/shutdown, and at most one final
   read-only live smoke.

No production-code implementation starts until this audit is committed on the
Phase 3 branch.
