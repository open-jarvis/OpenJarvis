# Phase 2 Codex backend

Date: 2026-07-30

This document records the Phase 2 backend architecture, security invariants,
verification results, and remaining limitations. It contains no credentials,
local account data, vault content, or live thread identifiers.

## Scope

Phase 2 adds only the Codex backend boundary and its immediate configuration,
state, event, build, and test support. It does not migrate any legacy
`jarvis-desktop` source or runtime data, does not integrate the real Obsidian
vault, and does not add a UI, browser automation, or a learning/promotion
system.

The official OpenJarvis baseline remains:

```text
1fa80d8ecd2e043cb61fdc8310f9f7ffef83698c
```

The implementation branch is:

```text
feature/codex-jarvis-orchestrator
```

The official OpenJarvis repository remains fetch-only `upstream`; push is
disabled.

## Architecture

```text
OpenJarvis orchestrator
  |
  +-- CodexBackendRouter
        |
        +-- CodexPythonSdkBackend   primary lifecycle path
        +-- CodexAppServerBackend  full local stdio events and approvals
        +-- CodexCliFallbackBackend explicit degraded emergency path
```

`CodexBackend` is an asynchronous protocol with health, thread start/resume/
fork/list, turn start and event streaming, steer, interrupt, thread read, and
close operations.

`CodexRunContext` makes every security- and correlation-sensitive value
explicit:

- task ID;
- session ID;
- idempotency/correlation ID;
- absolute existing working directory;
- sandbox;
- approval mode;
- model, reasoning effort, and service tier;
- timeout;
- step limit;
- optional token limit;
- developer instructions;
- optional isolated workspace root.

## Capability matrix

| Capability | Python SDK | App Server | CLI fallback |
| --- | ---: | ---: | ---: |
| Persistent threads | yes | yes | no |
| Resume | yes | yes | no |
| Fork | yes | yes | no |
| Streaming | yes | yes | no |
| Steer | yes | yes | no |
| Interrupt | yes | yes | no |
| Command approvals | no | yes | no |
| File approvals | no | yes | no |
| Full item events | yes | yes | no |
| Usage events | yes | yes | yes |
| Read-only | yes | yes | yes |
| Workspace-write | yes | yes | no |

The CLI reports `degraded_backend=true`. It is excluded from automatic routing
unless `allow_cli_fallback` is explicitly enabled. It never claims that its
one-shot process can resume or provide interactive approvals.

## Dependency and runtime

The optional dependency is:

```toml
codex = ["openai-codex==0.144.4"]
```

The package supports Python 3.10 and newer. OpenJarvis itself remains capped
below Python 3.14. The SDK pins and uses
`openai-codex-cli-bin==0.144.4`. The installed global CLI is 0.145.0, but it is
not substituted into the SDK path by default.

The complete public-interface audit is in `docs/codex/sdk-audit.md`.

## Authentication boundary

The SDK and App Server health checks use the public account APIs with token
refresh disabled. The CLI health check uses only:

```text
codex --version
codex login status
```

Only an existing ChatGPT login is accepted. API-key mode is reported as
unauthenticated for this integration. Environment variables whose names
contain API-key, access-token, authorization, cookie, or refresh-token markers
are removed before child Codex processes are launched.

The integration never opens or copies `auth.json` and never serializes access
tokens, refresh tokens, cookies, authorization headers, or API keys.

## Safety invariants

- `ApprovalMode.DENY_ALL` is required in Phase 2.
- `SandboxMode.FULL_ACCESS` is rejected.
- Analysis runs use read-only.
- Workspace-write requires an existing explicit isolated root, and the
  working directory must be contained by that root.
- App Server thread and turn messages set the deny policy and sandbox
  explicitly.
- The Python SDK receives an explicit approval mode and sandbox for every
  thread start, resume, fork, and turn.
- App Server approval requests go through `ApprovalBroker`.
- With no broker, the decision is `decline`.
- Duplicate server request IDs receive no duplicate approval response.
- Reconnect is prohibited while an App Server turn is active.
- Errors, event payloads, developer instructions, stderr, and persisted model
  configuration are redacted.

## Python SDK backend

`CodexPythonSdkBackend` uses only the public asynchronous SDK surface:

- `AsyncCodex.account`;
- `thread_start`;
- `thread_resume`;
- `thread_fork`;
- thread `turn` and `read`;
- turn `stream`, `steer`, and `interrupt`;
- ordered close.

Starts and forks are non-ephemeral. Thread and turn mappings are persisted
before they are exposed to later OpenJarvis operations. Correlation IDs make
repeated start/fork/turn requests idempotent.

## App Server backend

`AppServerTransport` launches only a local stdio child with
`create_subprocess_exec`; it does not use a shell or network listener.

It implements:

- JSONL framing;
- monotonically allocated request IDs;
- request/future correlation;
- bounded notification queues for backpressure;
- per-request and stream timeouts;
- separate, redacted stderr retention;
- safe initialize/initialized negotiation;
- server-initiated approval requests;
- one response per server request ID;
- default deny;
- orderly stdin close, wait, terminate, and kill fallback;
- reconnect only after the backend declares its state safe.

The default binary is the runtime bundled with the pinned SDK. A credential-
safe real health probe confirmed the installed 0.144.4 App Server can
initialize and observe the existing ChatGPT login.

## CLI fallback

The CLI fallback executes one turn with:

```text
codex exec
  --json
  --ephemeral
  --ignore-user-config
  --ignore-rules
  --sandbox read-only
  -c approval_policy="never"
  --cd <isolated working directory>
  --skip-git-repo-check
  --output-schema <packaged schema>
  --color never
  -
```

The prompt is passed over stdin rather than the command line. The final agent
message must contain exactly a non-empty `summary` property; the CLI receives
the packaged JSON schema and the backend validates the parsed result again.

No persistent Codex thread ID is exposed. OpenJarvis creates a clearly marked
in-memory `cli-ephemeral:` handle for one turn only. A second turn, resume,
fork, read, steer, interrupt, interactive approval, or workspace-write request
raises a capability or policy error.

## Persistence

`CodexStateStore` uses SQLite with:

- WAL journal mode;
- foreign keys enabled;
- short transactions;
- a per-thread atomic event sequence;
- unique task/session mappings;
- unique correlation IDs;
- unique backend thread and turn IDs;
- event-ID deduplication;
- resume checkpoints.

The three tables are `codex_threads`, `codex_turns`, and `codex_events`.
Stored fields cover the requested task, session, thread, turn, backend,
sandbox, approval mode, working directory, status, timestamps, sequence, and
checkpoint data. Phase 3 can connect these references to the unified
OpenJarvis task timeline without replacing this minimal mapping prematurely.

## Events

`CodexEventAdapter` emits schema version `1.0` records with event ID, sequence,
timestamp, task/session/thread/turn IDs, optional item ID, backend, normalized
type, and redacted payload.

It covers:

```text
thread.started       thread.resumed       thread.closed
turn.started         turn.completed       turn.failed
turn.interrupted     item.started         item.delta
item.completed       plan.updated         command.started
command.output       command.completed    file_change.proposed
file_change.applied  tool.started         tool.completed
approval.requested   approval.resolved    usage.updated
error
```

Explicit upstream event IDs are deduplicated. Unknown event types become safe
`error` events without forwarding their untrusted raw payload.

## Windows native build

Run:

```powershell
.\scripts\windows\build-native.ps1 `
  -UvPath <absolute-path-to-uv.exe> `
  -CargoHome <process-local-cargo-home> `
  -RustupHome <process-local-rustup-home>
```

The script finds Visual Studio Build Tools with `vswhere`, imports
`VsDevCmd.bat` into the current process, verifies `cl.exe`, `link.exe`,
`rustc.exe`, and `cargo.exe`, and then runs:

```text
uv run maturin develop --uv --manifest-path rust/crates/openjarvis-python/Cargo.toml
```

It sets these values only in the current process and its children:

```text
AWS_LC_SYS_PREBUILT_NASM=1
AWS_LC_SYS_NO_JITTER_ENTROPY=1
```

The final smoke imports `openjarvis_rust`. The verified incremental run built
and installed the wheel and passed the import. No administrator access, global
PATH edit, `setx`, or permanent environment setting is used.

## Verification

The focused Codex block:

```text
56 passed
```

It includes fakes and local protocol fixtures only; these tests consume no
Codex quota.

The controlled live SDK smoke was executed once with the existing ChatGPT
login. It used one read-only thread, received the expected first answer,
reopened the SQLite store and SDK backend, resumed the same thread, received
the expected second answer, stored the second turn as the resume checkpoint,
and left the empty isolated workspace unchanged.

The first turn also demonstrated the token guard: a deliberately low
10,000-token bound produced a persisted normalized policy error after the
usage event. The same controlled thread was then resumed with a realistic
100,000-token bound and completed. This is evidence that the usage guard is
active, not an additional live scenario.

The full non-live/non-cloud/non-hub OpenJarvis suite completed with:

```text
7125 passed, 49 skipped, 53 failed, 10 errors, 68 warnings
```

All new Codex and Windows-entry tests passed. The Phase 1.5 baseline was
`7071 passed, 49 skipped, 51 failed, 10 errors, 68 warnings`. The known
Windows, missing optional service, unmarked Ollama, fixture/path, SQLite
teardown, and telemetry groups remain. Two order-dependent outliers passed
when rerun alone; one existing throughput-zero assertion still failed alone.
No failure imports or exercises `src/openjarvis/codex`.

The real local OpenJarvis server smoke also passed after the changes:

- `/health` returned `ok`;
- native extension loaded;
- SQLite memory active;
- `GuardrailsEngine` active;
- explicit capability grant and deny both worked;
- rate limiting throttled the second request;
- no real LLM was used;
- deterministic chat completion succeeded;
- shutdown completed cleanly.

## Known limitations

1. The official Python SDK is beta and its bundled runtime is 0.144.4.
2. The global CLI is newer (0.145.0) and is used only by explicit degraded
   fallback, not as a silent SDK override.
3. The Python SDK does not expose interactive approval callbacks; use the App
   Server backend when Phase 3 connects an approval UI.
4. App Server approval UI presentation is intentionally deferred. Phase 2
   provides only the broker port and safe default deny.
5. CLI JSONL is buffered until the one-shot process completes and therefore
   does not claim real-time streaming or full event fidelity.
6. Token usage reported by Codex can include a large prompt/context window;
   production limits must be set with that behavior in mind.
7. The existing OpenJarvis Windows and optional-service test limitations
   listed in the Phase 1.5 readiness report remain unresolved.
8. The Codex backends are not yet wired into the complete orchestrator task
   timeline, approval UI, or unified session lifecycle; that is Phase 3 work.

## Phase 3 recommendation

Phase 3 may safely begin as an isolated integration phase, provided it keeps
the same restrictions: temporary vaults and workspaces first, no automatic
approval, no full-access sandbox, no API-key fallback, and no migration of
legacy runtime data until an independently verified backup/restore boundary is
in place.

The recommended next sequence is:

1. wire `CodexBackendRouter` into the existing orchestrator dependency
   boundary;
2. map normalized Codex events into the OpenJarvis task/trace timeline;
3. connect the App Server `ApprovalBroker` to a UI that requires an explicit
   user decision;
4. expose capability and degraded-state health without credential material;
5. run the integration against only a temporary Obsidian vault;
6. design and approve the legacy-data migration separately.
