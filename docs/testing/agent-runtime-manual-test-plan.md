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

### Commands exist

| # | Test | Expected |
|---|------|----------|
| 1 | `jarvis agents --help` | Shows all commands: `launch`, `start`, `stop`, `run`, `status`, `logs`, `daemon`, `watch`, `recover`, `errors`, `ask`, `instruct`, `messages` plus existing `list`, `info`, `create`, `pause`, `resume`, `delete` |

### Agent lifecycle: create → run → pause → resume → delete

| # | Test | Expected |
|---|------|----------|
| 2 | `jarvis agents launch` | Wizard: template list → name/schedule/tools/budget/learning prompts → creates agent, prints ID |
| 3 | `jarvis agents list` | Agent appears, status=`idle` |
| 4 | `jarvis agents status` | Table: name, status dot, schedule, last run, runs=0, cost=$0 |
| 5 | `jarvis agents run <id>` | Prints progress then "Tick complete. Status: idle, runs: 1" |
| 6 | `jarvis agents status` | runs=1, last run time updated |
| 7 | `jarvis agents pause <id>` then `status` | Status shows `paused` |
| 8 | `jarvis agents resume <id>` then `status` | Status back to `idle` |
| 9 | `jarvis agents delete <id>` then `list` | Agent gone |

### Scheduling

| # | Test | Expected |
|---|------|----------|
| 10 | Create agent with `schedule_type=interval`, `schedule_value=30` | Created |
| 11 | `jarvis agents start <id>` | "Agent registered with scheduler" |
| 12 | `jarvis agents stop <id>` | "Agent deregistered from scheduler" |
| 13 | `jarvis agents daemon` | Starts, prints agent count, blocks. Ctrl+C → "Daemon stopped." clean exit |

### Interaction: ask / instruct / messages

| # | Test | Expected |
|---|------|----------|
| 14 | `jarvis agents ask <id> "What is 2+2?"` | Runs tick, prints agent response inline |
| 15 | `jarvis agents messages <id>` | Shows user→agent ask + agent→user response |
| 16 | `jarvis agents instruct <id> "Focus on ML papers"` | "Instruction queued for next tick" |
| 17 | `jarvis agents messages <id>` | Queued instruction shows `[queued]`, status=pending |
| 18 | `jarvis agents run <id>` then `messages <id>` | Queued message now delivered |

### Error recovery & monitoring

| # | Test | Expected |
|---|------|----------|
| 19 | `jarvis agents errors` | Lists agents in error/needs_attention/stalled (or empty) |
| 20 | `jarvis agents recover <id>` (on errored agent) | Restores checkpoint, status → `idle` |
| 21 | `jarvis agents logs <id>` | Recent traces with tick IDs and timestamps |
| 22 | `jarvis agents watch` (then run a tick in another terminal) | Events stream live. Ctrl+C to stop. |
| 23 | `jarvis agents watch <id>` | Same, filtered to one agent |

### CLI aesthetics

| # | Check | Expected |
|---|-------|----------|
| 24 | `status` table formatting | Columns aligned, readable at 80-char terminal width |
| 25 | Error messages (run with no engine configured) | Clear human-readable message, no Python tracebacks |
| 26 | `launch` wizard prompts | Clear labels, sensible defaults, no confusing jargon |
| 27 | `watch` event stream | Color-coded, event type + agent name visible, timestamps |

---

## Part 2: Web Frontend

### Setup

```bash
# Terminal 1                    # Terminal 2
uv run jarvis serve             cd frontend && npm install && npm run dev
```

Open http://localhost:5173, navigate to **Agents** page.

### List view

| # | Test | Expected |
|---|------|----------|
| 28 | Page loads | No console errors, agent list renders |
| 29 | Agent cards | Name, color status dot, schedule, last run, runs count, cost |
| 30 | "Run Now" button | Triggers tick, card updates |
| 31 | Pause/Resume button | Toggles status, dot color changes |

### Launch wizard

| # | Test | Expected |
|---|------|----------|
| 32 | Click "Launch Agent" | Modal: Step 1 template picker (templates + "Custom Agent") |
| 33 | Next → Step 2 | Config form: name, schedule_type dropdown, schedule_value, tools checkboxes, budget, learning toggle (off) |
| 34 | Next → Step 3 | Review summary of all config |
| 35 | Click Launch | Agent created, modal closes, appears in list |
| 36 | Back button | Returns to previous step, inputs preserved |

### Detail view (click an agent)

| # | Test | Expected |
|---|------|----------|
| 37 | **Overview** tab | Stat cards (Runs, Success Rate, Cost), config display, action buttons |
| 38 | **Interact** tab | Chat message list, textarea, "Immediate" and "Queue" send buttons |
| 39 | Send immediate message | Appears in chat, agent responds after tick |
| 40 | Send queued message | Shows with "queued" badge, status=pending |
| 41 | **Tasks** tab | Task list with status badges |
| 42 | **Memory** tab | summary_memory text displayed |
| 43 | **Learning** tab | Toggle (off by default), placeholder for events |
| 44 | **Logs** tab | Placeholder / empty state (not a crash) |

### Error states

| # | Test | Expected |
|---|------|----------|
| 45 | Agent in `error` status | Red badge, "Recover" button visible |
| 46 | Click Recover | Status resets to `idle` |
| 47 | Agent in `needs_attention` | Amber badge visible |

### Web aesthetics

| # | Check | Expected |
|---|-------|----------|
| 48 | Status dot colors | idle=green, running=blue, paused=gray, error=red, needs_attention=amber, budget_exceeded=orange, stalled=yellow |
| 49 | Launch wizard spacing/alignment | Modal centered, steps clearly numbered, form inputs aligned |
| 50 | Detail view tab switching | Instant, no layout shift or flash |
| 51 | Interact tab chat feel | Messages visually distinct (user vs agent), auto-scroll, clear input area |
| 52 | Responsive at different widths | No overflow or cut-off content at 1024px and 1440px |
| 53 | Empty states | "No agents yet" / "No messages" / "No tasks" — not blank white space |

---

## Part 3: Desktop App

### Setup

```bash
# Terminal 1                    # Terminal 2
uv run jarvis serve             cd desktop && npm install && npm run tauri dev
```

Navigate to the **Agents** tab.

### Functionality

| # | Test | Expected |
|---|------|----------|
| 54 | Left panel: agent list | Status dots, schedule descriptions, last run times |
| 55 | Click agent → right panel | Tabbed detail view (Overview, Interact, Tasks, Memory, Learning, Logs) |
| 56 | "Launch Agent" button | Opens wizard, same 3-step flow as web |
| 57 | **Overview** tab | Stats table, action buttons (Run Now, Pause, Resume, Recover) |
| 58 | **Interact** tab | Chat UI, mode toggle (immediate/queued), Enter shortcut works |
| 59 | Send immediate message | Response appears |
| 60 | Send queued message | Shows as pending |

### Desktop aesthetics

| # | Check | Expected |
|---|-------|----------|
| 61 | Catppuccin color scheme consistent | idle=#a6e3a1, running=#89b4fa, paused=#6c7086, error=#f38ba8, needs_attention=#fab387, stalled=#f9e2af |
| 62 | Left/right panel split | Resizable or fixed at reasonable ratio, no overlap |
| 63 | Tab switching | Smooth, no flicker |
| 64 | Launch wizard modal | Properly overlays content, dismissible |
| 65 | Text readability | Font sizes consistent, sufficient contrast against dark background |

---

## Part 4: Cross-Platform Consistency

| # | Test | Expected |
|---|------|----------|
| 66 | Create agent via CLI → check web + desktop | Same name, status, config everywhere |
| 67 | Run tick via CLI → check web + desktop | Run count and last run time update |
| 68 | Send message via web Interact → check CLI `messages` | Same content, direction, mode |
| 69 | Pause via desktop → check CLI `status` + web | `paused` everywhere |
| 70 | Delete via web → check CLI `list` + desktop | Gone everywhere |

---

## Deliverables

**1. Test results** — Spreadsheet with columns: #, Status (Pass/Fail/Partial/Blocked), Actual Behavior, Screenshot (for UI issues).

**2. Bug list** — Each bug: steps to reproduce, expected vs actual, severity (Critical/Major/Minor), screenshot.

**3. UX & aesthetics feedback** — Is the launch wizard clear? Are status colors distinguishable? Does the Interact tab feel like chat? Is CLI output readable? Are error messages helpful?

**4. Deferred features check** — Confirm these show placeholders (not crashes): budget enforcement, stall detection, learning event timeline, logs trace replay, `jarvis agents learning <id>`, `jarvis agents trace <id>`.

---

## Notes

- Backend (`jarvis serve`) must be running for web and desktop.
- Without an engine configured, `run`/`ask` will error — document whether the error message is clear.
- `daemon` and `watch` block — Ctrl+C to exit.
