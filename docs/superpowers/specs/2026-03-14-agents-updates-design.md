# Agent UX, Auto-Update, and CLI Version Check — Design Spec

**Date:** 2026-03-14
**Scope:** Frontend (React), Backend (Python agents/scheduler), Desktop (Tauri/Rust), CLI (Click)
**Sub-projects:** 3 independent areas that can be implemented in any order

---

## Sub-project 1: Agent UX Overhaul

### 1A. Standing Instruction Field

**Problem:** Interval/cron agents are created without knowing what to do. Users must separately add tasks after creation, which is confusing.

**Change:**
- Add an `instruction` field to the agent config. This is the agent's standing purpose — it runs every tick as the primary prompt.
- In the creation wizard (Step 2), add a textarea: "What should this agent do?" Required for cron/interval schedule types, optional for manual.
- The instruction is stored in `config.instruction` on the managed agent record (no schema migration — `config_json` is a freeform JSON blob).
- The executor injects the instruction as the first message in the agent's context on every tick: `"Standing instruction: {instruction}"`.
- The instruction is editable in the agent detail view (Overview tab).
- Tasks remain as optional one-off goals. The instruction is "who you are", tasks are "specific things to handle now."

**Config editing caution:** The PATCH API for agents does a full `config` replacement (`json.dumps(kwargs["config"])`). When editing only the instruction from the Overview tab, the frontend must read the current config, merge the instruction change, and send the full config object to avoid clobbering other config fields (schedule_type, tools, budget, etc.).

**Validation:** Frontend validates that instruction is non-empty for cron/interval agents before allowing launch. Backend `create` endpoint also rejects cron/interval agents with empty instruction (return 400).

**Files:**
- `frontend/src/pages/AgentsPage.tsx` — add instruction textarea to wizard Step 2, add instruction display/edit to Overview tab
- `src/openjarvis/agents/executor.py` — inject `config.instruction` into agent context at tick start
- `src/openjarvis/server/agent_manager_routes.py` — add validation in create endpoint

### 1B. Model Selection for Agents

**Problem:** Agents use whatever model the server was started with. Users can't choose a different model per agent.

**Change:**
- Add a `model` dropdown to the creation wizard (Step 2), defaulting to the currently selected chat model.
- Store as `config.model` on the managed agent record.
- The executor already reads `config.get("model")` at line 181 and falls back to the system default. No backend change needed for the execution path.
- The model is editable in the agent detail view (Overview tab) without recreating the agent.
- Dropdown populated from the store's `models` array (already fetched at app init from `/v1/models`).

**Files:**
- `frontend/src/pages/AgentsPage.tsx` — add model dropdown to wizard Step 2, add model display/edit to Overview tab

### 1C. Error Visibility (Toast Notifications)

**Problem:** When "Run Now" fails or a scheduled tick errors, the status badge changes to "error" but there's no popup or message explaining what went wrong.

**Change:**
- **Backend fix:** The executor currently sets `status="error"` on failure but does NOT write the error message to `summary_memory` (the `update_summary_memory` call only happens in the success path). Fix: in the executor's error handler, write the error string to `summary_memory` so the frontend can read it.
- **Frontend — post-run check:** After `runManagedAgent()`, wait 3 seconds, then re-fetch the agent. If status is `error`, show a toast via `sonner` with the agent name and the error detail from `summary_memory`. Also emit a log entry.
- **Frontend — periodic polling:** Add a 30-second polling interval in `AgentsPage` (new, does not exist currently) that fetches agent list and compares statuses. If any agent transitioned to `error` since last poll, show a toast.

**Files:**
- `frontend/src/pages/AgentsPage.tsx` — add post-run error check with toast, add 30-second polling interval
- `src/openjarvis/agents/executor.py` — write error string to `summary_memory` in the error/exception handler

### 1D. Auto-Start for Interval/Cron Agents

**Problem:** Creating an interval agent leaves it in `idle` state. The scheduler is not wired into the server, so cron/interval agents never fire automatically.

**Change — scheduler wiring (critical prerequisite):**
The `AgentScheduler` class exists but is never instantiated or started by the server. This must be fixed first:
1. In `serve.py`: instantiate `AgentScheduler` when `agent_manager` is available, start it as a background thread, and register all existing cron/interval agents.
2. Pass the scheduler to the agent manager routes (via app state or router factory) so the create endpoint can register new agents.
3. Stop the scheduler on server shutdown.
4. On server startup, scan `managed_agents` for all non-archived agents with cron/interval schedules and register them with the scheduler (bootstrap).

**Change — auto-start behavior:**
- After creating an interval agent, the frontend calls `runManagedAgent(id)` to trigger the first tick immediately. The scheduler then takes over for subsequent ticks.
- For cron agents: the scheduler registers them and they fire at the next cron match. No immediate first run.
- For manual agents: no change.
- Race condition note: the scheduler's next fire time should be calculated from when the first manual tick completes, not from creation time. The `end_tick` call should update the scheduler's next fire for that agent.

**Files:**
- `src/openjarvis/cli/serve.py` — instantiate and start AgentScheduler, stop on shutdown
- `src/openjarvis/server/agent_manager_routes.py` — accept scheduler, register agents on create, deregister on delete
- `frontend/src/pages/AgentsPage.tsx` — call `runManagedAgent(id)` after creation for interval agents

---

## Sub-project 2: Desktop Auto-Update

**Problem:** Users must manually check GitHub releases and download new DMGs. The Tauri updater plugin is configured but not wired up in the frontend.

**Change:**
- On app launch (in `App.tsx`), check for updates using `@tauri-apps/plugin-updater`, guarded by `isTauri()`.
- Wrap in try/catch — silently ignore errors (no internet, endpoint unreachable, etc.).
- Download the update in the background. The UI remains fully usable during download (the async function runs without blocking the React render cycle).
- When download completes, show a toast: "Update ready — restart to apply" with a "Restart Now" button.
- Clicking "Restart Now" calls `relaunch()` from `@tauri-apps/plugin-process`.
- Only check once per launch (not on every route change). Use a ref to prevent double-checking.
- Note: the Tauri updater operates at the Rust level, not via browser fetch, so the CSP `connect-src` restriction does not apply.

**Implementation:**
```typescript
// In App.tsx useEffect, guarded by isTauri()
async function checkUpdate() {
  try {
    const { check } = await import('@tauri-apps/plugin-updater');
    const update = await check();
    if (update) {
      await update.downloadAndInstall();
      // Show toast with "Restart Now" button
    }
  } catch {
    // Silent — no internet or endpoint issue
  }
}
```

**Files:**
- `frontend/src/App.tsx` — add update check in a `useEffect` (Tauri-only)

---

## Sub-project 3: CLI Version Check

**Problem:** CLI users don't know when a new version is available. They must manually check GitHub.

**Change:**
- Add a `check_for_updates()` function in a new `_version_check.py` module.
- Cache the result in `~/.openjarvis/version-check.json` with a timestamp. Only re-check if >24 hours since last check. Ensure `~/.openjarvis/` directory exists before writing.
- Compare the latest release tag against `openjarvis.__version__` using `packaging.version.Version` for proper semver comparison. Strip the `v` prefix from GitHub tags.
- If a newer version exists, print a yellow message to **stderr** (not stdout, to avoid polluting piped output) before the command runs:
  ```
  A new version of OpenJarvis is available (v0.1.0 → v0.2.0)
  Update: cd ~/OpenJarvis && git pull && uv sync
  ```
- Call from a Click group-level callback in `src/openjarvis/cli/__init__.py` that checks the subcommand name — only run for `chat`, `ask`, and `serve`. This avoids repeating the call in three files.
- Network failures are silently ignored (best-effort check).
- For cached results, the check adds ~0ms latency. For fresh API calls (~300ms), the latency is acceptable since `chat`, `ask`, and `serve` are all interactive commands.

**Files:**
- `src/openjarvis/cli/_version_check.py` — new file with `check_for_updates()` function
- `src/openjarvis/cli/__init__.py` — add group-level callback for version check on chat/ask/serve

**Cache format (`~/.openjarvis/version-check.json`):**
```json
{
  "last_check": "2026-03-14T20:00:00Z",
  "latest_version": "0.2.0",
  "current_version": "0.1.0"
}
```

**GitHub API call:**
```
GET https://api.github.com/repos/open-jarvis/OpenJarvis/releases/latest
```
Returns `tag_name` (e.g. `v0.2.0`). No auth required (public repo), rate-limited to 60/hr (once-per-day caching stays well under this).

---

## Non-Goals

- No WebSocket/real-time agent status updates (polling is sufficient for v1)
- No agent log streaming (use the Logs page)
- No automatic restart after update download (user clicks "Restart Now")
- No PyPI version check (project is git-based, not published to PyPI yet)
- No breaking change detection in version check (just version comparison)
- No forced updates or blocking update prompts

---

## Testing

- Agent UX: existing agent manager tests cover the backend; add test for instruction injection in executor; frontend TypeScript-checked
- Desktop auto-update: manual testing (Tauri updater requires signed builds)
- CLI version check: unit test for version comparison, cache read/write, and tag parsing
- All changes: `tsc --noEmit`, `ruff check`, `pytest tests/server/`, `cargo check`

---

## Summary of Changes by File

| File | Changes |
|------|---------|
| `AgentsPage.tsx` | Instruction textarea, model dropdown in wizard; instruction/model edit in detail; error toast + polling; auto-run interval agents |
| `App.tsx` | Desktop auto-update check on launch |
| `executor.py` | Inject `config.instruction` into context; write error to `summary_memory` on failure |
| `agent_manager_routes.py` | Validate instruction on create; accept scheduler; register/deregister agents |
| `serve.py` | Instantiate AgentScheduler, start/stop it, pass to routes |
| `cli/__init__.py` | Group-level callback for version check |
| `cli/_version_check.py` | New file: GitHub releases check, cache, semver comparison |
