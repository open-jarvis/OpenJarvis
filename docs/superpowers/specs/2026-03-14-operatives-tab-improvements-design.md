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

The component serializes to the interval string the backend expects (e.g., `"2h30m"`) on submission. Default: 0h 30m 0s.

Cron input stays as a text field but gets a helper tooltip showing common patterns (hourly, daily, weekly).

### Files changed

- `frontend/src/pages/AgentsPage.tsx` — Wizard Step 2 schedule section

---

## Section 2: Categorized Tools Grid with Credential Setup

### New backend endpoint

`GET /v1/tools` returns all registered tools from `ToolRegistry` with metadata:

```json
[{
  "name": "web_search",
  "description": "Search the web via Tavily/DuckDuckGo",
  "category": "search",
  "requires_credentials": true,
  "credential_keys": ["TAVILY_API_KEY"],
  "configured": true
}]
```

The endpoint introspects each tool's `ToolSpec` and checks whether required env vars are set so the UI can show configured vs needs-setup status.

### Frontend categories

Categories ordered by likely usage. Within each category, tools are ordered by popularity. Each category is collapsible with a "Show all (N)" link to expand beyond the popular defaults.

| Category | Popular (shown by default) | Expandable |
|----------|---------------------------|------------|
| **Communication** | Slack, Email, Telegram, WhatsApp | Discord, iMessage (BlueBubbles), Signal, Teams, Google Chat, IRC, Matrix, Mattermost, LINE, Viber, Messenger, Reddit, Mastodon, XMPP, Rocket.Chat, Zulip, Twitch, Nostr, Feishu, Webhook |
| **Search & Browse** | web_search, browser | — |
| **Code & Dev** | code_interpreter, shell_exec, git_status, git_diff | git_log, git_commit, repl, code_interpreter_docker, apply_patch |
| **Files & Data** | file_read, file_write, pdf_extract | db_query, http_request |
| **Memory & Knowledge** | retrieval, memory_store | memory_retrieve, memory_search, memory_index, kg_add_entity, kg_add_relation, kg_query, kg_neighbors |
| **Reasoning & AI** | think, llm, calculator | agent_spawn, agent_send, agent_list, agent_kill |
| **Media** | image_generate | audio_transcribe, audio_tool |

### UI behavior

- Each category is a collapsible section header with a chevron
- Popular tools shown by default; "Show all (N)" link expands the rest
- Each tool is a card/chip with: icon, name, one-line description
- Unconfigured tools (missing credentials) show an orange dot + "Setup required"
- Selected tools get a checkmark + accent highlight

### Credential setup flow

Selecting an unconfigured tool opens an inline expandable card beneath it with labeled inputs for each required credential key (e.g., "Slack Bot Token", "Slack App Token"). A "Save" button persists credentials to `~/.openjarvis/.env` or equivalent.

**Gating requirement:** The wizard blocks progression to Step 3 (Review) until all selected tools have their required credentials configured. Validation message: "N tools need setup" with unconfigured ones highlighted.

### Credential persistence

Backend endpoint `POST /v1/tools/{tool_name}/credentials` accepts key-value pairs and writes them to the credential store. A `GET /v1/tools/{tool_name}/credentials/status` returns which keys are set (without exposing values).

### Files changed

- `src/openjarvis/server/agent_manager_routes.py` — New `GET /v1/tools` endpoint
- `src/openjarvis/server/agent_manager_routes.py` — New credential endpoints
- `frontend/src/pages/AgentsPage.tsx` — Wizard Step 2 tools section
- `frontend/src/lib/api.ts` — New `fetchAvailableTools()`, `saveToolCredentials()` functions

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

**Current behavior:** Calls API, resets status to idle, returns checkpoint. No visible feedback.

**Fix:**
- Show success toast: "Agent recovered to idle state" or "Agent recovered from checkpoint (tick #N)"
- If no checkpoint exists: "Agent reset to idle (no checkpoint available)"
- If API call fails: show error toast with reason
- After recover, auto-switch to Overview tab so user sees status change

### Structured error messages in Logs

**Backend:**
- Add `error_detail` dict to tick finalization containing: error_type (retryable/fatal/escalate), error_message, stack_trace_summary (first 3 frames), suggested_action

**Frontend Logs tab:**
- Error entries expand to show:
  - **Error type** badge (Fatal, Retryable, Needs Attention) with color coding
  - **Message** — the actual error text
  - **Suggested action** — e.g., "Check API key configuration", "Engine not reachable"
  - **Timestamp + duration**
- Success entries stay compact (green dot + outcome + duration)

### Files changed

- `frontend/src/pages/AgentsPage.tsx` — handleRun, handleRecover, Logs tab
- `src/openjarvis/server/agent_manager_routes.py` — _run_tick error handling
- `src/openjarvis/agents/executor.py` — Structured error_detail in tick finalization

---

## Section 5: Learning Technique Selection

### Router Policy dropdown

Replace the "Enable Learning" checkbox with a "Learning" section containing:

**Part A: Router Policy** (all agent types)

Dropdown with descriptions:
- **None** — "No learning. Agent always uses the selected model." (default)
- **Heuristic** — "Rule-based model selection. Picks models based on query type (code, math, length, urgency)."
- **Trace-Driven** — "Learns from past runs. Builds query-type to model mapping over time. Requires 5+ runs to activate."

### Agent Strategies (MonitorOperative only)

**Part B: Strategy dropdowns** (shown only when agent_type is `monitor_operative`)

Four dropdowns, each with a help icon tooltip:

| Strategy | Options | Default | Tooltip |
|----------|---------|---------|---------|
| Memory Extraction | Causality Graph, Scratchpad, Structured JSON, None | Scratchpad | "How the agent extracts and stores findings between runs" |
| Observation Compression | Summarize, Truncate, None | Summarize | "How long tool outputs are compressed to fit context" |
| Retrieval Strategy | Hybrid + Self-Eval, Keyword, Semantic, None | Hybrid + Self-Eval | "How the agent retrieves relevant past context" |
| Task Decomposition | Phased, Monolithic, Hierarchical | Phased | "How the agent breaks down complex instructions into subtasks" |

For non-monitor-operative agent types, Part B is hidden.

### Wizard review display

```
Learning: Trace-Driven Router
Strategies: Scratchpad memory, Summarize compression, Hybrid retrieval, Phased decomposition
```

### Config mapping

The router policy maps to `config.router_policy` (new field). The strategies map to existing MonitorOperativeAgent config fields: `memory_extraction`, `observation_compression`, `retrieval_strategy`, `task_decomposition`.

### Files changed

- `frontend/src/pages/AgentsPage.tsx` — Wizard Step 2 learning section, Step 3 review
- `src/openjarvis/agents/executor.py` — Wire router_policy from agent config when building system

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

- Unit tests for new `GET /v1/tools` endpoint
- Unit tests for credential persistence endpoints
- Unit tests for structured error_detail in executor
- Frontend: manual testing of wizard flow end-to-end
- Frontend: verify "Run Now" error handling with intentionally broken engine config
- Frontend: verify "Recover" shows feedback toast
- Frontend: verify interval serialization (hours/minutes/seconds → string)
- Frontend: verify credential gating blocks wizard progression
