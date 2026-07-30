# Phase 6 legacy tool-call inventory

Date: 2026-07-30  
Scope: `openjarvis-codex` at the Phase 6 feature branch

## Enforcement boundary

The supported Phase 6 application path is the local FastAPI application plus
the React/Tauri client. Model- or UI-originated tool work in that boundary must
be a `ToolProposal` and may execute only through `ToolActionService`,
`CentralRiskPolicy`, persistent allow-once approval when required, and a
postcondition verifier. A missing action service fails closed.

The canonical Jarvis chat does not call a legacy tool executor. Codex emits
normalized task items and approvals; OpenJarvis remains the authority. The
managed-agent SSE compatibility endpoint now converts each proposed tool call
to a deterministic canonical proposal. MCP adapters and `ToolExecutor` are not
called by that endpoint. Deep-research progress uses the same gateway. Replayed
call IDs are idempotent and do not execute twice.

The old OpenAI-compatible completion endpoint rejects a configured legacy
tool-using agent when canonical action mode is active and directs the caller to
`/v1/chat`. The old direct agent mutation endpoints and external channel
activation also fail closed in canonical action mode. Tauri no longer registers
the arbitrary `run_jarvis_command(args)` invocation and no longer grants shell
permissions, so the desktop UI cannot reach legacy CLI tool loops.

## Classified call sites

| Location | Call type | Class | Phase 6 disposition |
|---|---|---:|---|
| `server/agent_manager_routes.py` managed-agent tool loop | MCP adapter and `ToolExecutor.execute` | 3 | Runtime branches disabled; every reachable call enters `_execute_exposed_tool_via_action_service`. Missing service, unknown manifest, bad schema, denied policy, or missing approval fails closed. |
| `server/agent_manager_routes.py` deep-research progress wrapper | agent `ToolExecutor.execute` | 3 | Wrapper replaced with the same canonical action gateway. No implicit confirmation is used for the reachable call. |
| `server/routes.py` legacy `/v1/chat/completions` agent loop | `agent.run` leading to `ToolExecutor` | 3/4 | Rejected with HTTP 409 when a canonical action service is configured. Raw caller-supplied function schemas may still be returned as model decisions but are never executed by this endpoint. |
| `server/api_routes.py` POST/DELETE/message agent helpers | direct `Agent*Tool.execute` | 3/4 | Mutations fail closed in canonical action mode. Read-only inventory remains available. |
| `server/agent_manager_routes.py` iMessage, SendBlue and Slack bind startup | channel and daemon helpers | 3 | External channel activation fails closed in canonical action mode. No real accounts are used in Phase 6. |
| `frontend/src-tauri/src/lib.rs` former `run_jarvis_command(args)` | arbitrary CLI subprocess | 3/4/5 | Removed from the Tauri command registry and compile-excluded; Admin UI uses only owned `start_backend` and `stop_backend`. Shell plugin and permissions removed. |
| `tools/action_service.py` | registered handlers | canonical | The only Phase 6 execution authority. It validates manifests and parameters, applies `CentralRiskPolicy`, queues persistent approvals, uses bounded lanes, records output/artifacts, verifies postconditions, and handles retry safety. |
| `browser/process.py`, `browser/service.py` | browser/control subprocess helpers | 1 | Trusted implementation behind `BrowserSessionService` and its action runtime. Only owned temporary sessions may be closed or recovered. Not model-callable directly. |
| `desktop/session.py` | desktop test process helper | 1 | Trusted test adapter with owned-process tracking. Not exposed as a general UI command in Phase 6. |
| `tools/safe_filesystem.py`, `tools/safe_shell.py`, `tools/git_secure.py` | bounded primitive runtimes | 1 | Trusted handlers only when registered in `ToolActionService`; they are not authorization boundaries themselves. |
| `agents/orchestrator.py`, `agents/operative.py`, `agents/proactive_agent.py` | legacy `ToolExecutor` loops | 2/4 | Upstream compatibility implementations. They are not selected by the canonical Jarvis route. Managed-server exposure is intercepted as described above. |
| `workflow/engine.py`, `skills/executor.py` | workflow/skill `ToolExecutor` | 2/4 | Explicit legacy library/CLI workflows, not exposed by the Phase 6 UI or Tauri shell. Retained to avoid blind compatibility deletion. |
| `mcp/server.py` | standalone MCP `ToolExecutor` | 4 | Standalone compatibility server, not mounted into the Phase 6 FastAPI app. Managed-agent MCP execution is intercepted by the action gateway. |
| `cli/ask.py`, `cli/agent_cmd.py`, `cli/serve.py` scheduler wiring | legacy CLI/tool construction | 2/4 | Retained upstream CLI compatibility. The Phase 6 desktop cannot invoke arbitrary CLI arguments. These paths are not the supported unified Jarvis surface. |
| connector/channel OAuth and send helpers | filesystem, browser, HTTP and subprocess helpers | 1/4 | Provider internals retained but no provider account is configured or activated in the isolated Phase 6 runtime. They are not registered as unrestricted Tauri commands. |
| test files and benchmark/bootstrap helpers | direct tool and subprocess calls | 1 | Synthetic fixtures or explicit developer bootstrap. They remain isolated and do not accept model authorization. |

## Residual compatibility code

Some disabled compatibility branches remain in source so upstream behavior is
not deleted blindly. Their presence does not make them reachable in canonical
action mode: hard-coded dispatch prevents MCP/`ToolExecutor` use, the legacy
completion guard blocks tool-using agents, and the Tauri handler/capabilities do
not expose arbitrary shell execution. Static and integration tests cover these
boundaries.

Manual use of the upstream standalone CLI, standalone MCP server, provider
daemons, or library agents remains a separate compatibility surface. It is not
silently represented as Phase 6-safe and is not launched by the unified app.
A future phase should either migrate each standalone entry point to an injected
`ToolActionService` or explicitly deprecate it; Phase 6 preserves it without
granting application reachability.

## Verification

- `tests/server/test_legacy_action_gateway.py` proves policy, execution,
  verification, and idempotent replay through the canonical service and proves
  fail-closed behavior without that service.
- `tests/desktop/test_tauri_hardening.py` proves broad process/shell grants and
  the arbitrary Tauri handler are absent.
- Phase 5 action, policy, approval, filesystem, shell, Git, browser and recovery
  suites remain the detailed safety coverage for registered runtimes.
