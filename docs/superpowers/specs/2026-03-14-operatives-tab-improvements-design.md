# Operatives Tab Improvements Design

**Date:** 2026-03-14
**Status:** Draft
**Scope:** Frontend overhaul of Agents/Operatives wizard, detail page, and error handling + one new backend endpoint + minor backend fixes

## Summary

Nine improvements to the Operatives tab addressing UX clarity, tool discovery, error handling, and learning configuration. The backend already supports most required functionality — the primary gap is the frontend not surfacing it.

## Issues Addressed

1. Schedule type lacks explanation (Manual/Cron/Interval unclear)
2. Interval input is a raw string instead of structured hours/minutes/seconds
3. Only 6 tools shown; backend has 44 tools + 27 channels
4. Budget field doesn't clarify it's optional and cloud-only
5. No model/Intelligence selector (recently added, needs enhancement)
6. "Run Now" crashes
7. "Recover" button does nothing visible
8. Logs lack descriptive error messages
9. No learning technique selection (only a boolean toggle)

## Approach

Frontend-first (Approach A). All issues addressable with frontend changes + one new backend endpoint (`GET /v1/tools`) + minor backend error handling fixes.

---

## Section 1: Schedule Help & Structured Interval Input

### Schedule type help

Add an info icon (circled "i") next to the "Schedule" label. Clicking/hovering shows a tooltip or popover explaining each option:

- **Manual** — "Agent runs only when you click 'Run Now'. Good for on-demand tasks."
- **Cron** — "UNIX cron schedule (e.g., `0 9 * * *` = daily at 9 AM). For recurring fixed-time jobs."
- **Interval** — "Runs repeatedly with a fixed delay between runs. For continuous monitoring."

Each option in the select dropdown also gets a one-line subtitle beneath the label.

### Structured interval input

Replace the free-text interval input with three numeric spinners side by side:

```
Hours [0-999]  Minutes [0-59]  Seconds [0-59]
```

The component serializes to total seconds as a string (e.g., `"9000"` for 2h30m), which is the format the `AgentScheduler` already parses. Default: 0h 30m 0s.

**Minimum interval validation:** Total interval must be at least 10 seconds to prevent tight loops. The wizard shows a validation error if all three fields sum to less than 10 seconds.

Cron input stays as a text field but gets a helper tooltip showing common patterns (hourly, daily, weekly).

### Files changed

- `frontend/src/pages/AgentsPage.tsx` — Wizard Step 2 schedule section

---

## Section 2: Categorized Tools Grid with Credential Setup

### New backend endpoint

`GET /v1/tools` returns all registered tools from `ToolRegistry` and channels from `ChannelRegistry`, merged into a unified list with metadata:

```json
[{
  "name": "web_search",
  "description": "Search the web via Tavily/DuckDuckGo",
  "category": "search",
  "source": "tool",
  "requires_credentials": true,
  "credential_keys": ["TAVILY_API_KEY"],
  "configured": true
}]
```

**Credential metadata source:** Since `ToolSpec` does not have a `credential_keys` field, the endpoint maintains a `TOOL_CREDENTIALS` mapping dict that maps tool/channel names to their required env var keys. This is a static dict in the endpoint module (not on ToolSpec itself) to avoid changing the tool interface. Example:

```python
TOOL_CREDENTIALS: dict[str, list[str]] = {
    "web_search": ["TAVILY_API_KEY"],
    "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
    "telegram": ["TELEGRAM_BOT_TOKEN"],
    "email": ["EMAIL_USERNAME", "EMAIL_PASSWORD"],
    "whatsapp": ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"],
    "image_generate": ["OPENAI_API_KEY"],
    # ... etc for all tools/channels that need credentials
}
```

The `configured` field is derived by checking `os.environ.get()` for each required key. Tools not in the `TOOL_CREDENTIALS` mapping return `requires_credentials: false` and `credential_keys: []`.

The `category` field is read from `ToolSpec.category` where set; for channels, category is always `"communication"`.

**Browser tools:** The 6 browser sub-tools (`browser_navigate`, `browser_click`, `browser_type`, `browser_screenshot`, `browser_extract`, `browser_axtree`) are grouped under a single "Browser" meta-entry in the UI. Selecting "Browser" adds all 6 to `config.tools[]`.

### Frontend categories

Categories ordered by likely usage. Within each category, tools are ordered by popularity. Each category is collapsible with a "Show all (N)" link to expand beyond the popular defaults.

**Category mapping:** The backend returns raw `ToolSpec.category` values (e.g., `"search"`, `"code"`, `"browser"`, `"math"`, `"system"`, `"reasoning"`, `"agents"`, `"channel"`, `"memory"`). The frontend maps these to display categories:

| Backend category | Frontend display category |
|-----------------|--------------------------|
| `communication`, `channel` | Communication |
| `search`, `browser` | Search & Browse |
| `code`, `system` | Code & Dev |
| `filesystem`, `""` (empty/unset for file tools) | Files & Data |
| `memory`, `knowledge_graph` | Memory & Knowledge |
| `reasoning`, `math`, `inference`, `agents` | Reasoning & AI |
| `media` | Media |

Tools with no category set are assigned by a frontend fallback map keyed on tool name (e.g., `file_read` → "Files & Data", `http_request` → "Files & Data").

| Category | Popular (shown by default) | Expandable |
|----------|---------------------------|------------|
| **Communication** | slack, email, telegram, whatsapp | discord, bluebubbles (iMessage), signal, teams, google_chat, irc, matrix, mattermost, line, viber, messenger, reddit, mastodon, xmpp, rocketchat, zulip, twitch, nostr, feishu, webhook |
| **Search & Browse** | web_search, Browser (meta-group) | — |
| **Code & Dev** | code_interpreter, shell_exec, git_status, git_diff | git_log, git_commit, repl, code_interpreter_docker, apply_patch |
| **Files & Data** | file_read, file_write, pdf_extract | db_query, http_request |
| **Memory & Knowledge** | retrieval, memory_store | memory_retrieve, memory_search, memory_index, kg_add_entity, kg_add_relation, kg_query, kg_neighbors |
| **Reasoning & AI** | think, llm, calculator | agent_spawn, agent_send, agent_list, agent_kill |
| **Media** | image_generate | audio_transcribe |

### UI behavior

- Each category is a collapsible section header with a chevron
- Popular tools shown by default; "Show all (N)" link expands the rest
- Each tool is a card/chip with: icon, name, one-line description
- Unconfigured tools (missing credentials) show an orange dot + "Setup required"
- Selected tools get a checkmark + accent highlight

### Credential setup flow

Selecting an unconfigured tool opens an inline expandable card beneath it with labeled inputs for each required credential key (e.g., "Slack Bot Token", "Slack App Token"). A "Save" button persists credentials to `~/.openjarvis/.env` or equivalent.

**Credential gating:** The wizard shows a warning banner "N tools need setup" with unconfigured ones highlighted in orange. The user can still proceed to Step 3 (Review) but sees the warning repeated there. This avoids blocking exploration while making the setup requirement clear. Tools without credentials will fail at runtime — the review step warns: "These tools will not work until credentials are configured."

### Credential persistence

Backend endpoint `POST /v1/tools/{tool_name}/credentials` accepts key-value pairs. `GET /v1/tools/{tool_name}/credentials/status` returns which keys are set (without exposing values).

**Storage:** Credentials are written to `~/.openjarvis/credentials.toml` (consistent with the existing TOML config pattern in `core/config.py`). File is created with `chmod 600` permissions. Format:

```toml
[web_search]
TAVILY_API_KEY = "tvly-..."

[slack]
SLACK_BOT_TOKEN = "xoxb-..."
SLACK_APP_TOKEN = "xapp-..."
```

**Runtime reload:** After writing credentials, the endpoint sets `os.environ[key] = value` for each key so the current process picks them up immediately without restart. Credential writes are serialized with a threading lock to prevent concurrent file corruption. On server startup, `credentials.toml` is loaded and injected into `os.environ` before tool/channel imports.

**Security:**
- File permissions: `0o600` (owner read/write only)
- Credential values are never returned by any GET endpoint — only boolean `configured` status
- Key names are validated against the known `TOOL_CREDENTIALS` mapping; unknown keys are rejected
- Values are stripped of whitespace; empty values are rejected

### Files changed

- `src/openjarvis/server/agent_manager_routes.py` — New `GET /v1/tools` endpoint, credential endpoints
- `src/openjarvis/core/credentials.py` — New module: load/save/validate credentials from `~/.openjarvis/credentials.toml`
- `frontend/src/pages/AgentsPage.tsx` — Wizard Step 2 tools section
- `frontend/src/lib/api.ts` — New `fetchAvailableTools()`, `saveToolCredentials()` functions, new `ToolInfo` type
- `frontend/src/types/index.ts` — New `ToolInfo` interface

---

## Section 3: Budget Clarification & Model Selection Enhancement

### Budget field

- Label: "Budget (optional)"
- Subtitle: "Applies to cloud API models only (OpenAI, Anthropic, Google). Local models have no cost."
- Placeholder: `"e.g., 5.00"`
- Overview display: "Unlimited (local)" or "Unlimited" instead of bare "Unlimited"

### Model/Intelligence selection enhancement

- Group models by source: "Local (Running)" at top, then "Cloud" section
- Each model shows: name + parameter count + context length (from Intelligence catalog)
- "Server default" remains the first option
- If no local engines running, hint: "Start a local engine or configure cloud API keys in Settings"

### Files changed

- `frontend/src/pages/AgentsPage.tsx` — Wizard Step 2 budget and model sections

---

## Section 4: Run Now Fix, Recover Fix, Structured Error Logs

### "Run Now" crash fix

**Root cause:** The frontend handler uses `.catch(() => {})` which silently swallows errors. The backend `_run_tick` thread may raise before setting agent status properly.

**Frontend fix:**
- Replace `.catch(() => {})` with proper error handling that shows a toast with the error message from the API response body
- Handle both HTTP errors (4xx/5xx from the POST) and async errors (agent fails after thread spawn)

**Backend fix:**
- Wrap the entire `_run_tick` thread body in try/except ensuring `manager.end_tick()` is always called
- Write descriptive error to `summary_memory` and set status to "error"
- Return structured error info in the agent status response

### "Recover" fix

**Current behavior:** Calls API, but `manager.recover_agent()` only resets status to idle IF a checkpoint exists. When no checkpoint is found, the route returns 404 and the agent stays in "error" state. The frontend calls `refresh()` with no feedback.

**Backend fix:**
- Modify `manager.recover_agent()` to **always** reset status to "idle", regardless of whether a checkpoint exists. The checkpoint is a bonus (restores conversation state), but the primary purpose of "Recover" is to clear the error state.
- Change the route to return 200 with `{"recovered": true, "checkpoint": <data|null>}` instead of raising 404 when no checkpoint exists.

**Frontend fix:**
- Show success toast: "Agent recovered to idle state" or "Agent recovered from checkpoint (tick #N)"
- If response has `checkpoint: null`: "Agent reset to idle (no checkpoint available)"
- If API call fails: show error toast with reason
- After recover, auto-switch to Overview tab so user sees status change

### Structured error messages in Logs

**Backend:**
- Add `error_detail` dict to tick finalization containing: `error_type` (retryable/fatal/escalate), `error_message`, `stack_trace_summary` (first 3 frames), `suggested_action`
- **Storage:** `error_detail` is stored as JSON in the trace's `metadata` field (traces already have a metadata dict). The executor's `_finalize_tick()` populates `trace_metadata["error_detail"] = {...}` before saving the trace via `trace_store.save()`. This keeps error details co-located with the trace they belong to.
- **Suggested action derivation:** Based on the error classification from `errors.py`. Mapping:
  - "rate limit" → "Rate limited — agent will auto-retry on next tick"
  - "timeout" / "connection" → "Engine not reachable — check that your inference engine is running"
  - "401" / "403" / "permission" → "Check API key configuration in Settings"
  - "not found" / "404" → "Model or endpoint not found — verify model name and engine URL"
  - Default → "Unexpected error — check the full trace for details"
- **Retrieval:** The existing `GET /v1/managed-agents/{id}/traces` endpoint already returns trace metadata. The frontend reads `trace.metadata.error_detail` to render structured errors.

**Frontend Logs tab:**
- Error entries expand to show:
  - **Error type** badge (Fatal, Retryable, Needs Attention) with color coding
  - **Message** — the actual error text
  - **Suggested action** — e.g., "Check API key configuration", "Engine not reachable"
  - **Timestamp + duration**
- Success entries stay compact (green dot + outcome + duration)

### Files changed

- `frontend/src/pages/AgentsPage.tsx` — handleRun, handleRecover, Logs tab
- `frontend/src/lib/api.ts` — Update `recoverManagedAgent()` to return response body
- `src/openjarvis/server/agent_manager_routes.py` — _run_tick error handling, recover endpoint fix
- `src/openjarvis/agents/manager.py` — `recover_agent()` always resets status to idle
- `src/openjarvis/agents/executor.py` — Structured error_detail in tick finalization

---

## Section 5: Learning Technique Selection

### Router Policy dropdown

Replace the "Enable Learning" checkbox with a "Learning" section containing:

**Part A: Router Policy** (all agent types)

Dropdown with descriptions. Display names map to `RouterPolicyRegistry` keys:
- **None** — "No learning. Agent always uses the selected model." (config value: `null`)
- **Heuristic** — "Rule-based model selection. Picks models based on query type (code, math, length, urgency)." (config value: `"heuristic"`)
- **Trace-Driven** — "Learns from past runs. Builds query-type to model mapping over time. Requires 5+ runs to activate." (config value: `"learned"`)

### Agent Strategies (MonitorOperative only)

**Part B: Strategy dropdowns** (shown only when agent_type is `monitor_operative`)

Four dropdowns, each with a help icon tooltip. Display names and their config values:

| Strategy | Options (display → config value) | Default | Tooltip |
|----------|---------|---------|---------|
| Memory Extraction | Causality Graph → `causality_graph`, Scratchpad → `scratchpad`, Structured JSON → `structured_json`, None → `none` | Causality Graph (`causality_graph`) | "How the agent extracts and stores findings between runs" |
| Observation Compression | Summarize → `summarize`, Truncate → `truncate`, None → `none` | Summarize (`summarize`) | "How long tool outputs are compressed to fit context" |
| Retrieval Strategy | Hybrid + Self-Eval → `hybrid_with_self_eval`, Keyword → `keyword`, Semantic → `semantic`, None → `none` | Hybrid + Self-Eval (`hybrid_with_self_eval`) | "How the agent retrieves relevant past context" |
| Task Decomposition | Phased → `phased`, Monolithic → `monolithic`, Hierarchical → `hierarchical` | Phased (`phased`) | "How the agent breaks down complex instructions into subtasks" |

For non-monitor-operative agent types, Part B is hidden.

### Wizard review display

```
Learning: Trace-Driven Router
Strategies: Scratchpad memory, Summarize compression, Hybrid retrieval, Phased decomposition
```

### Config mapping

The router policy maps to `config.router_policy` (new field). The strategies map to existing MonitorOperativeAgent config fields: `memory_extraction`, `observation_compression`, `retrieval_strategy`, `task_decomposition`.

**Router policy integration data flow:**
1. Agent config stores `router_policy: "learned"` (or `"heuristic"` or `null`)
2. In `executor.py`, `_invoke_agent()` reads `config.get("router_policy")`
3. If set, looks up the policy class via `RouterPolicyRegistry.create(policy_key, available_models=models)`
4. Passes the policy to `SystemBuilder.with_router(policy)` when building the `JarvisSystem` for the tick
5. During agent execution, if a router is present, `system.ask()` calls `router.select_model(context)` to override the default model for that query
6. If `router_policy` is `null`, no router is created and the agent uses its configured model directly (current behavior)

### Files changed

- `frontend/src/pages/AgentsPage.tsx` — Wizard Step 2 learning section, Step 3 review
- `frontend/src/types/index.ts` — Add router_policy and strategy fields to ManagedAgent config type
- `src/openjarvis/agents/executor.py` — Wire router_policy from agent config when building system
- `src/openjarvis/system.py` — `SystemBuilder` accepts optional router_policy override

---

## Data Flow

```
Wizard Step 2
├── Schedule: type + structured value → config.schedule_type, config.schedule_value
├── Tools: categorized grid + credential setup → config.tools[]
├── Budget: optional dollar amount → config.max_cost
├── Model: grouped dropdown → config.model
└── Learning: router policy + strategies → config.router_policy, config.memory_extraction, etc.
    ↓
POST /v1/managed-agents { name, config }
    ↓
AgentManager.create_agent() → SQLite
    ↓
AgentScheduler.register_agent() (if scheduled)
```

## Testing Plan

- Unit tests for new `GET /v1/tools` endpoint (tool + channel merging, credential status)
- Unit tests for credential persistence (`credentials.toml` read/write, permissions, key validation)
- Unit tests for structured error_detail in executor
- Unit tests for `recover_agent()` always resetting to idle (with and without checkpoint)
- Unit tests for interval serialization (hours/minutes/seconds → string, minimum 10s validation)
- Frontend: manual testing of wizard flow end-to-end
- Frontend: verify "Run Now" error handling with intentionally broken engine config
- Frontend: verify "Recover" shows feedback toast and switches to Overview tab
- Frontend: verify credential gating blocks wizard progression
- Frontend: verify browser meta-group expands to all 6 sub-tools in config
- Frontend: verify strategy dropdowns only appear for monitor_operative agent type
