# Agent Runtime Manual Test Plan

**Branch:** `main`
**PR Reference:** [#32](https://github.com/open-jarvis/OpenJarvis/pull/32)

---

## Setup

```bash
git checkout main && git pull
uv sync --extra dev
```

Create `~/.openjarvis/config.toml`:

```toml
[engine]
type = "cloud"

[intelligence]
default_model = "Qwen/Qwen3.5-35B-A3B"

[engine.cloud]
provider = "openai"
api_key = "sk-..."
```

For every test case, record: **Pass / Fail / Partial / Blocked**, what you actually saw, and screenshots for any UI issues.

---

## Part 1: CLI (`jarvis agents`)

### 1.1 Commands exist

| # | Test | Expected |
|---|------|----------|
| 1 | `jarvis agents --help` | Shows all subcommands: `launch`, `start`, `stop`, `run`, `status`, `logs`, `daemon`, `watch`, `recover`, `errors`, `ask`, `instruct`, `messages`, `list`, `info`, `create`, `pause`, `resume`, `delete`, `bind`, `channels`, `search`, `templates`, `tasks` |

### 1.2 Agent lifecycle: create → run → pause → resume → delete

| # | Test | Expected |
|---|------|----------|
| 2 | `jarvis agents launch` | Wizard: template list → name/schedule/tools/budget/learning prompts → creates agent, prints ID |
| 3 | `jarvis agents list` | Agent appears, status=`idle` |
| 4 | `jarvis agents status` | Table: name, status dot, schedule, last run, runs=0, cost=$0 |
| 5 | `jarvis agents run <id>` | Prints progress then "Tick complete. Status: idle, runs: 1" |
| 6 | `jarvis agents status` | runs=1, last run time updated |
| 7 | `jarvis agents pause <id>` then `status` | Status shows `paused` |
| 8 | `jarvis agents resume <id>` then `status` | Status back to `idle` |
| 9 | `jarvis agents delete <id>` then `list` | Agent gone (soft-deleted/archived, not in list) |

### 1.3 Agent creation variants

| # | Test | Expected |
|---|------|----------|
| 10 | `jarvis agents create "Test Agent"` | Creates agent by name, prints ID |
| 11 | `jarvis agents create --template <template_name>` | Creates from template, inherits template config |
| 12 | `jarvis agents launch` → pick a template | Wizard pre-fills config from template |
| 13 | `jarvis agents launch` → pick "Custom Agent" | Wizard starts with blank config |
| 14 | `jarvis agents templates` | Lists built-in + user templates with descriptions |

### 1.4 Scheduling

| # | Test | Expected |
|---|------|----------|
| 15 | Create agent with `schedule_type=interval`, `schedule_value=30` | Created |
| 16 | `jarvis agents start <id>` | "Agent registered with scheduler" |
| 17 | `jarvis agents stop <id>` | "Agent deregistered from scheduler" |
| 18 | `jarvis agents daemon` | Starts, prints agent count, blocks. Ctrl+C → "Daemon stopped." clean exit |
| 19 | Create agent with `schedule_type=cron`, `schedule_value="*/5 * * * *"` | Created |
| 20 | `jarvis agents start <id>` (cron agent) | Registered, next fire time displayed or logged |
| 21 | Create agent with `schedule_type=manual` then `start <id>` | Agent registered but never auto-fires |

### 1.5 Interaction: ask / instruct / messages

| # | Test | Expected |
|---|------|----------|
| 22 | `jarvis agents ask <id> "What is 2+2?"` | Runs tick, prints agent response inline |
| 23 | `jarvis agents messages <id>` | Shows user→agent ask + agent→user response |
| 24 | `jarvis agents instruct <id> "Focus on ML papers"` | "Instruction queued for next tick" |
| 25 | `jarvis agents messages <id>` | Queued instruction shows `[queued]`, status=pending |
| 26 | `jarvis agents run <id>` then `messages <id>` | Queued message now delivered, status changes from pending |
| 27 | `jarvis agents ask <id> ""` (empty message) | Graceful error or rejection, no crash |
| 28 | `jarvis agents instruct <id>` with very long message (>1000 chars) | Accepted and stored correctly |

### 1.6 Error recovery & monitoring

| # | Test | Expected |
|---|------|----------|
| 29 | `jarvis agents errors` | Lists agents in error/needs_attention/stalled/budget_exceeded (or empty table) |
| 30 | `jarvis agents recover <id>` (on errored agent) | Restores checkpoint, status → `idle` |
| 31 | `jarvis agents recover <id>` (on idle agent) | Clear message: "Agent is not in error state" or similar |
| 32 | `jarvis agents logs <id>` | Recent traces with tick IDs and timestamps |
| 33 | `jarvis agents logs <nonexistent_id>` | Clear error: "Agent not found" |
| 34 | `jarvis agents watch` (then run a tick in another terminal) | Events stream live: AGENT_TICK_START, AGENT_TICK_END visible. Ctrl+C to stop. |
| 35 | `jarvis agents watch <id>` | Same, filtered to one agent only |
| 36 | `jarvis agents watch` then Ctrl+C | Clean exit, no traceback, no hanging threads |

### 1.7 Agent info & inspection

| # | Test | Expected |
|---|------|----------|
| 37 | `jarvis agents info <id>` | Shows agent type, status, memory snippet, tasks, channels, config details |
| 38 | `jarvis agents tasks <id>` | Lists tasks with statuses (or empty state) |
| 39 | `jarvis agents channels <id>` | Lists channel bindings (or empty state) |
| 40 | `jarvis agents search "keyword"` | Searches across agent traces, returns relevant results |

### 1.8 Edge cases & invalid input

| # | Test | Expected |
|---|------|----------|
| 41 | `jarvis agents run <nonexistent_id>` | Clear error: "Agent not found" — no Python traceback |
| 42 | `jarvis agents pause <id>` twice | Second pause is no-op or clear message, no crash |
| 43 | `jarvis agents resume <id>` (already idle) | No-op or clear message, no crash |
| 44 | `jarvis agents run <id>` while another tick is running | Concurrency guard: "Agent is already running" error |
| 45 | `jarvis agents delete <id>` then `run <id>` | Clear error about deleted/archived agent |
| 46 | Create agent with invalid cron expression | Rejected with clear validation error |
| 47 | Create agent with negative budget | Rejected or clamped to 0 |

### 1.9 CLI aesthetics

| # | Check | Expected |
|---|-------|----------|
| 48 | `status` table formatting | Columns aligned, readable at 80-char terminal width |
| 49 | Error messages (run with no engine configured) | Clear human-readable message, no Python tracebacks |
| 50 | `launch` wizard prompts | Clear labels, sensible defaults, no confusing jargon |
| 51 | `watch` event stream | Color-coded, event type + agent name visible, timestamps |
| 52 | `list` table with 0 agents | "No agents found" or empty table — not a crash |
| 53 | `list` table with 10+ agents | Table remains readable, no column overflow |
| 54 | All commands with `--help` | Every subcommand has a help string |

---

## Part 2: Web Frontend

### 2.0 Setup

```bash
# Terminal 1                    # Terminal 2
uv run jarvis serve             cd frontend && npm install && npm run dev
```

Open http://localhost:5173, navigate to **Agents** page via sidebar.

### 2.1 Navigation & routing

| # | Test | Expected |
|---|------|----------|
| 55 | Click "Agents" in sidebar | AgentsPage renders, URL is `/agents` |
| 56 | Direct navigation to `/agents` | Page loads correctly (no blank screen) |
| 57 | Browser back/forward after visiting agent detail | Navigation works, state preserved |

### 2.2 List view

| # | Test | Expected |
|---|------|----------|
| 58 | Page loads with backend running | No console errors, agent list renders |
| 59 | Page loads with backend **down** | User-visible error message (not blank white screen), no console exceptions |
| 60 | Agent cards | Name, color status dot, schedule description, last run time, runs count, cost |
| 61 | "Run Now" button | Triggers tick, card updates (runs count increments, last run time updates) |
| 62 | Pause/Resume button | Toggles status, dot color changes immediately |
| 63 | Agent list auto-refresh | After running a tick via CLI, the web list eventually reflects the updated state |
| 64 | 10+ agents in list | Cards render without performance issues, scroll works |

### 2.3 Launch wizard

| # | Test | Expected |
|---|------|----------|
| 65 | Click "Launch Agent" | Modal appears: Step 1 template picker with templates + "Custom Agent" option |
| 66 | Templates load from API | Template cards display with names and descriptions |
| 67 | Select template → Next → Step 2 | Config form: name (pre-filled from template), schedule_type dropdown, schedule_value, tools checkboxes, budget, learning toggle (off) |
| 68 | Select "Custom Agent" → Next → Step 2 | Config form with blank name, no pre-filled values |
| 69 | Next → Step 3 | Review summary of all config values |
| 70 | Click Launch | Agent created, modal closes, new agent appears in list |
| 71 | Back button at Step 2 | Returns to Step 1, template selection preserved |
| 72 | Back button at Step 3 | Returns to Step 2, all form inputs preserved |
| 73 | Launch with empty name | Inline error: "Agent name is required" — modal stays open |
| 74 | Launch with all tools selected | All tools included in review and in created agent config |
| 75 | Click outside modal / press Escape | Modal closes (or stays open — document behavior) |
| 76 | Schedule type = "Manual" | schedule_value input is disabled/hidden |
| 77 | Schedule type = "Cron" | schedule_value placeholder shows cron example |
| 78 | Schedule type = "Interval" | schedule_value placeholder shows seconds example |

### 2.4 Detail view (click an agent)

| # | Test | Expected |
|---|------|----------|
| 79 | Click agent card | Detail view opens with tabbed interface |
| 80 | **Overview** tab | Stat cards (Total Runs, Success Rate, Total Cost), config display, channels list, action buttons |
| 81 | **Overview** action buttons | Run Now, Pause, Resume visible and functional |
| 82 | **Interact** tab | Chat message list, textarea, "Immediate" and "Queue" send buttons |
| 83 | Send immediate message | Appears in chat with user styling, agent responds after tick |
| 84 | Send queued message | Shows with "queued" badge, status=pending |
| 85 | Send empty message | Button disabled or graceful rejection — no empty message sent |
| 86 | Rapid-fire send (click Send multiple times quickly) | No duplicate messages, no race condition errors |
| 87 | Chat auto-scroll | New messages scroll into view automatically |
| 88 | **Tasks** tab | Task list with status badges (completed=green, failed=red, active=blue, pending=gray) |
| 89 | **Tasks** tab (no tasks) | Empty state: "No tasks assigned." |
| 90 | **Memory** tab | summary_memory text displayed in readable format |
| 91 | **Memory** tab (no memory) | Empty state: "Agent has no stored memory yet." |
| 92 | **Learning** tab | Toggle switch (read-only, off by default), placeholder text for future events |
| 93 | **Logs** tab | Placeholder / empty state message (not a crash or blank) |
| 94 | Tab switching — rapid clicks | All 6 tabs render instantly, no layout shift, no flash of wrong content |

### 2.5 Error states

| # | Test | Expected |
|---|------|----------|
| 95 | Agent in `error` status | Red status dot/badge, "Recover" button visible |
| 96 | Click Recover | Status resets to `idle`, dot turns green |
| 97 | Agent in `needs_attention` status | Amber badge visible |
| 98 | Agent in `budget_exceeded` status | Orange badge visible |
| 99 | Agent in `stalled` status | Yellow badge visible |
| 100 | Backend goes down while page is open | Next refresh/action shows error — not silent failure |
| 101 | Delete agent → confirm it disappears from list | Agent removed from list immediately (or on next refresh) |
| 102 | Delete agent (no confirmation dialog in web) | **Document:** Is instant delete OK or should there be a confirm? |

### 2.6 Overflow menu

| # | Test | Expected |
|---|------|----------|
| 103 | Click "..." menu on agent card | Dropdown with Delete + other options |
| 104 | Click Delete from menu | Agent deleted, list updates |
| 105 | Click outside dropdown | Dropdown closes |

### 2.7 Web aesthetics & UX

| # | Check | Expected |
|---|-------|----------|
| 106 | Status dot colors | idle=#22c55e, running=#3b82f6, paused=#6b7280, error=#ef4444, needs_attention=#f59e0b, budget_exceeded=#f97316, stalled=#eab308 |
| 107 | Launch wizard spacing/alignment | Modal centered, steps clearly numbered, form inputs aligned, no overlap |
| 108 | Detail view tab switching | Instant, no layout shift or flash |
| 109 | Interact tab chat feel | Messages visually distinct (user=right vs agent=left or different colors), auto-scroll, clear input area |
| 110 | Responsive at 1024px width | No overflow or cut-off content, agent cards reflow |
| 111 | Responsive at 1440px width | Proper use of space, no excessive stretching |
| 112 | Responsive at 768px width (tablet) | Still usable, no broken layout |
| 113 | Empty states | "No agents yet" + CTA button / "No messages" / "No tasks" — not blank white space |
| 114 | Loading states | "Loading agents..." shown during fetch, spinner or skeleton |
| 115 | Page title / browser tab | Meaningful title (not just "Vite App") |
| 116 | Console errors | Zero console errors during normal usage flow |

---

## Part 3: Desktop App

### 3.0 Setup

```bash
# Terminal 1                    # Terminal 2
uv run jarvis serve             cd desktop && npm install && npm run tauri dev
```

Navigate to the **Agents** tab.

### 3.1 Functionality

| # | Test | Expected |
|---|------|----------|
| 117 | Left panel: agent list | Status dots, schedule descriptions, last run times |
| 118 | Click agent → right panel | Tabbed detail view (Overview, Interact, Tasks, Memory, Learning, Logs) |
| 119 | No agent selected | Right panel shows "Select an agent to view details" |
| 120 | "Launch Agent" button | Opens wizard, same 3-step flow as web |
| 121 | Launch wizard → Create agent | Agent appears in left panel list |
| 122 | **Overview** tab | Key-value stats (Status, Agent Type, Schedule, Last Run, Total Runs, Total Cost, Budget) + action buttons (Run Now, Pause, Resume, Recover) |
| 123 | **Interact** tab | Chat UI, mode toggle (immediate/queued), Enter shortcut sends message |
| 124 | Send immediate message | Response appears in chat |
| 125 | Send queued message | Shows as pending |
| 126 | **Tasks** tab | Task list with colored status badges + created-at timestamps |
| 127 | **Memory** tab | summary_memory in monospace font |
| 128 | **Learning** tab | Shows enabled/disabled status + placeholder text |
| 129 | **Logs** tab | Placeholder: "Log streaming not yet connected." |
| 130 | Auto-refresh | Agent list refreshes on ~10s interval (verify with CLI-triggered state change) |
| 131 | Delete agent via desktop | Confirmation dialog appears, agent removed on confirm |

### 3.2 Desktop edge cases

| # | Test | Expected |
|---|------|----------|
| 132 | Backend not running → open desktop app | Error state shown, not a crash |
| 133 | Backend dies while desktop is open | Graceful degradation on next action/refresh |
| 134 | Selected agent deleted via CLI → desktop refreshes | Selected agent deselects, list updates |

### 3.3 Desktop aesthetics

| # | Check | Expected |
|---|-------|----------|
| 135 | Catppuccin color scheme consistent | idle=#a6e3a1, running=#89b4fa, paused=#6c7086, error=#f38ba8, needs_attention=#fab387, stalled=#f9e2af |
| 136 | Left/right panel split | Resizable or fixed at reasonable ratio, no overlap |
| 137 | Tab switching | Smooth, no flicker |
| 138 | Launch wizard modal | Properly overlays content, dismissible with Escape or outside click |
| 139 | Text readability | Font sizes consistent, sufficient contrast against dark background |
| 140 | Window resize | Layout adapts, no overflow or clipping |
| 141 | Status badge consistency with web | Same statuses map to same semantic colors (green=idle, blue=running, etc.) |

---

## Part 4: API Backend (Direct)

### 4.1 REST endpoint smoke tests

Run with `uv run jarvis serve` and test via curl or Postman.

| # | Test | Expected |
|---|------|----------|
| 142 | `GET /v1/managed-agents` | 200, returns `[]` or agent list JSON |
| 143 | `POST /v1/managed-agents` with valid body | 200/201, returns created agent JSON with `id` |
| 144 | `POST /v1/managed-agents` with empty body | 422 or 400 with validation error |
| 145 | `GET /v1/managed-agents/<id>` | 200, returns single agent |
| 146 | `GET /v1/managed-agents/<bad_id>` | 404, returns error JSON |
| 147 | `POST /v1/managed-agents/<id>/run` | 200, tick executes |
| 148 | `POST /v1/managed-agents/<id>/pause` | 200, status changes to paused |
| 149 | `POST /v1/managed-agents/<id>/resume` | 200, status changes to idle |
| 150 | `POST /v1/managed-agents/<id>/recover` | 200 if errored, appropriate error if not |
| 151 | `DELETE /v1/managed-agents/<id>` | 200, agent archived |
| 152 | `GET /v1/templates` | 200, returns template list |
| 153 | `POST /v1/templates/<id>/instantiate` | 200, creates agent from template |
| 154 | `GET /v1/agents/errors` | 200, returns list of problem agents |
| 155 | `GET /v1/agents/health` | 200, returns health summary |

### 4.2 Message endpoints

| # | Test | Expected |
|---|------|----------|
| 156 | `POST /v1/managed-agents/<id>/messages` with `{"content":"hi","direction":"user_to_agent","mode":"immediate"}` | 200, message stored |
| 157 | `GET /v1/managed-agents/<id>/messages` | 200, returns message list |
| 158 | `POST /v1/managed-agents/<id>/messages` with `{"content":"","direction":"user_to_agent","mode":"immediate"}` | 422 or graceful handling |
| 159 | `POST /v1/managed-agents/<id>/messages` with `{"content":"cmd","direction":"user_to_agent","mode":"queued"}` | 200, message has status=pending |

### 4.3 Task & channel endpoints

| # | Test | Expected |
|---|------|----------|
| 160 | `GET /v1/managed-agents/<id>/tasks` | 200, returns task list |
| 161 | `POST /v1/managed-agents/<id>/tasks` | 200, creates task |
| 162 | `GET /v1/managed-agents/<id>/channels` | 200, returns channel bindings |
| 163 | `GET /v1/managed-agents/<id>/state` | 200, returns full agent state |

### 4.4 WebSocket events

| # | Test | Expected |
|---|------|----------|
| 164 | Connect to `ws://localhost:8222/v1/agents/events` | Connection established |
| 165 | Trigger a tick → observe WS messages | Receive AGENT_TICK_START and AGENT_TICK_END events |
| 166 | Connect with `?agent_id=<id>` filter | Only events for that agent |
| 167 | Disconnect cleanly | No server error logs |

---

## Part 5: Cross-Platform Consistency

| # | Test | Expected |
|---|------|----------|
| 168 | Create agent via CLI → check web + desktop | Same name, status, config everywhere |
| 169 | Run tick via CLI → check web + desktop | Run count and last run time update in both UIs |
| 170 | Send message via web Interact → check CLI `messages` | Same content, direction, mode |
| 171 | Pause via desktop → check CLI `status` + web | `paused` everywhere |
| 172 | Delete via web → check CLI `list` + desktop | Gone everywhere |
| 173 | Create via web wizard → check CLI `list` + desktop | Agent visible in all three |
| 174 | Recover via CLI → check web + desktop | Status back to idle in all UIs |
| 175 | Send queued message via CLI `instruct` → check web Interact | Message shows with pending/queued status |
| 176 | Multiple agents created from different clients | All agents appear correctly in all views |

---

## Part 6: Stress & Concurrency

| # | Test | Expected |
|---|------|----------|
| 177 | Run tick on same agent from two terminals simultaneously | Concurrency guard blocks second tick: "Agent is already running" |
| 178 | Create 20+ agents → check list performance | All clients render list without lag |
| 179 | Rapidly pause/resume same agent | All state transitions correct, no stuck states |
| 180 | Run daemon + manual `run` at same time | No double-ticking, concurrency guard holds |
| 181 | Delete agent while tick is in progress | Tick completes or fails gracefully, agent ends up archived |

---

## Part 7: Deferred Features (Placeholder Verification)

Confirm these show placeholders (not crashes):

| # | Feature | CLI | Web | Desktop |
|---|---------|-----|-----|---------|
| 182 | Budget enforcement | `run` still works even if cost > budget | No enforcement, budget is display-only | Same |
| 183 | Stall detection | No automatic stall detection fires | N/A | N/A |
| 184 | Learning event timeline | `Learning` tab shows placeholder text | Same | Same |
| 185 | Logs trace replay | `Logs` tab shows placeholder text | Same | Same |
| 186 | `POST /v1/skills` | N/A | N/A | Returns `"not_implemented"` |
| 187 | `POST /v1/optimize/runs` | N/A | N/A | Returns placeholder `run_id` |
| 188 | `GET /v1/feedback/stats` | N/A | N/A | Returns `{total: 0, mean_score: 0.0}` |

---

## Deliverables

**1. Test results** — Spreadsheet with columns: #, Status (Pass/Fail/Partial/Blocked), Actual Behavior, Screenshot (for UI issues).

**2. Bug list** — Each bug: steps to reproduce, expected vs actual, severity (Critical/Major/Minor), screenshot.

**3. UX & aesthetics feedback** — Is the launch wizard clear? Are status colors distinguishable? Does the Interact tab feel like chat? Is CLI output readable? Are error messages helpful? Is the delete-without-confirm behavior in web acceptable?

**4. API error handling audit** — Document all cases where the frontend silently swallows errors (currently: agent list fetch, interact tab sends). Recommend which should show user-visible errors.

**5. Deferred features check** — Confirm placeholder items in Part 7 show graceful stubs (not crashes or blank screens).

---

## Notes

- Backend (`jarvis serve`) must be running for web and desktop (default port 8222).
- Without an engine configured, `run`/`ask` will error — document whether the error message is clear.
- `daemon` and `watch` block — Ctrl+C to exit.
- Web frontend API client has unused functions (`updateManagedAgent`, `createAgentTask`, `fetchAgentState`, `fetchErrorAgents`) — not a bug, but note for future.
- Desktop API client is missing some endpoints that the web client has (`fetchAgentChannels`, `fetchAgentState`, `fetchErrorAgents`) — may affect feature parity.
- Frontend has **no automated tests** — all testing is manual per this plan.
- Both frontends silently catch API errors (`.catch(() => {})`) — this is a known UX gap to evaluate.
