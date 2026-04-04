# Scheduled Monitor

A persistent operative agent that runs on a cron schedule, maintains state across runs, and uses memory to track changes over time. Ideal for daily inbox monitoring, recurring status checks, and long-running research projects.

## Quickstart (5 minutes)

### 1. Install and initialize

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync --extra dev
jarvis init --preset scheduled-monitor
```

This writes a pre-configured `~/.openjarvis/config.toml` for the operative agent with scheduling support.

### 2. Start a local LLM via Ollama

```bash
# Install Ollama: https://ollama.com
ollama pull qwen3.5:9b
```

### 3. Index your data

```bash
jarvis memory index ~/Documents/
```

The operative agent uses memory to track state across runs, so indexing your data gives it context for the first run.

### 4. Create a scheduled task

```bash
jarvis scheduler start

jarvis scheduler create \
  --prompt "Check for new emails about Project X and update your notes" \
  --schedule "0 9 * * 1-5" \
  --agent operative \
  --tools "knowledge_search,knowledge_sql,memory_store,think"
```

This creates a task that runs at 9 AM every weekday. The operative agent will search your indexed data, process new information, and store notes in memory for the next run.

## How Scheduling Works

The scheduler uses cron expressions to trigger agent runs at specified intervals. Each run is an independent agent session, but the operative agent persists state between sessions.

### Cron expression reference

```
 .------------ minute (0-59)
 | .---------- hour (0-23)
 | | .-------- day of month (1-31)
 | | | .------ month (1-12)
 | | | | .---- day of week (0-6, 0=Sunday)
 | | | | |
 * * * * *
```

Common examples:

| Expression | Meaning |
|------------|---------|
| `0 9 * * 1-5` | 9 AM, Monday through Friday |
| `0 6 * * *` | 6 AM every day |
| `*/30 * * * *` | Every 30 minutes |
| `0 9,17 * * *` | 9 AM and 5 PM daily |
| `0 8 1 * *` | 8 AM on the 1st of every month |

### CLI commands

```bash
# Start the scheduler daemon
jarvis scheduler start

# Create a new scheduled task
jarvis scheduler create \
  --prompt "Summarize any new research papers in my library" \
  --schedule "0 8 * * *" \
  --agent operative

# List all scheduled tasks
jarvis scheduler list

# View task details and run history
jarvis scheduler status <task-id>

# Pause / resume / delete a task
jarvis scheduler pause <task-id>
jarvis scheduler resume <task-id>
jarvis scheduler delete <task-id>

# Run a task immediately (outside its schedule)
jarvis scheduler run <task-id>

# Stop the scheduler daemon
jarvis scheduler stop
```

## Configuration Reference

The preset writes this to `~/.openjarvis/config.toml`:

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:9b"
temperature = 0.3

[agent]
default_agent = "operative"
max_turns = 20
context_from_memory = true          # Inject relevant memory into context

[tools]
enabled = ["knowledge_search", "knowledge_sql", "scan_chunks", "memory_store", "memory_search", "think", "web_search"]

[tools.storage]
default_backend = "sqlite"
```

### Key settings

| Setting | Default | Description |
|---------|---------|-------------|
| `intelligence.default_model` | `qwen3.5:9b` | The model used for reasoning. |
| `intelligence.temperature` | `0.3` | Low temperature for consistent, factual outputs across runs. |
| `agent.default_agent` | `operative` | Persistent agent that maintains state between sessions. |
| `agent.max_turns` | `20` | High turn limit for thorough processing of accumulated data. |
| `agent.context_from_memory` | `true` | Automatically injects relevant memory chunks into the agent's context. |
| `tools.enabled` | 7 tools | Search, store, scan, and reason tools for reading and writing to the knowledge base. |

### Tools explained

| Tool | What it does |
|------|-------------|
| `knowledge_search` | Semantic search across indexed documents. |
| `knowledge_sql` | Structured queries against the document store. |
| `scan_chunks` | Browse through document chunks sequentially. |
| `memory_store` | Write new facts and notes to the knowledge base. |
| `memory_search` | Search previously stored agent notes. |
| `think` | Internal reasoning scratchpad for planning. |
| `web_search` | Search the web for supplementary information. |

## Example Use Cases

### Daily inbox monitor

```bash
jarvis scheduler create \
  --prompt "Review my recent emails. Flag anything urgent and summarize the rest. Store a daily summary." \
  --schedule "0 9 * * 1-5" \
  --agent operative \
  --tools "knowledge_search,memory_store,think"
```

### Research tracker

```bash
jarvis scheduler create \
  --prompt "Search for new papers related to 'efficient transformers'. Compare with papers I've already indexed and note what's new." \
  --schedule "0 8 * * 1" \
  --agent operative \
  --tools "knowledge_search,web_search,memory_store,think"
```

### Status reporter

```bash
jarvis scheduler create \
  --prompt "Check the project status documents and generate a weekly progress summary. Note any blockers." \
  --schedule "0 17 * * 5" \
  --agent operative \
  --tools "knowledge_search,knowledge_sql,memory_store,think"
```

## How State Persistence Works

The operative agent differs from other agents in that it maintains state across runs:

- **Memory storage**: The agent uses the `memory_store` tool to save notes, summaries, and observations. These persist in the local SQLite database and are available in future runs.
- **Context injection**: With `context_from_memory = true`, the agent automatically receives relevant context from previous runs when it starts a new session.
- **Accumulated knowledge**: Over time, the agent builds a progressively richer understanding of your data. A Monday run can reference notes from the previous Friday.
- **All data stays local**: State is stored in `~/.openjarvis/` using the configured memory backend. Nothing leaves your machine.

## Troubleshooting

**"Scheduler not running"** -- Start the scheduler daemon with `jarvis scheduler start`. It must be running for scheduled tasks to execute.

**Task doesn't run on time** -- Check that Ollama is running (`ollama serve`). The scheduler triggers the agent, but the agent needs an inference engine. Verify the schedule with `jarvis scheduler status <task-id>`.

**Agent produces inconsistent results** -- Keep `temperature` at `0.3` or lower for scheduled tasks. Higher temperatures introduce randomness that compounds across runs.

**Memory grows too large** -- Periodically review with `jarvis memory stats`. Clear old entries with `jarvis memory clear --before 2026-01-01` if needed.

**Agent runs too long** -- Reduce `max_turns` or simplify the prompt. The operative agent is thorough and may use all available turns.
