# Task Scheduler

The task scheduler lets you run agent queries automatically on a schedule -- once at a future time, on a recurring interval, or via a cron expression. Scheduled tasks are persisted in SQLite so they survive process restarts, and execution is handled by a background daemon thread that polls for due tasks every 60 seconds.

!!! note "Optional component"
    To run tasks with `jarvis serve` or `jarvis start`, set `enabled = true` under `[scheduler]` in `config.toml`. Alternatively, run `jarvis scheduler start` as a standalone worker. Only one worker can poll a given scheduler database.

---

## Schedule Types

| `schedule_type` | `schedule_value` format            | Example                     | Meaning                             |
|-----------------|------------------------------------|-----------------------------|-------------------------------------|
| `once`          | ISO 8601 datetime                  | `"2026-03-01T10:00:00+01:00"` | Run once at 09:00 UTC. No offset means UTC. |
| `interval`      | Seconds as a string                | `"3600"`                    | Run every hour, first run in one hour |
| `cron`          | Standard 5-field cron expression   | `"0 9 * * 1-5"`             | 09:00 UTC, Monday–Friday            |

!!! tip "Cron support"
    Cron expressions use `croniter`, an OpenJarvis dependency. Use `--timezone` with an IANA timezone such as `Europe/Madrid` for local wall-clock time. Cron defaults to UTC.

---

## CLI Commands

The `jarvis scheduler` subcommand group manages tasks and the daemon from the terminal.

### Start the daemon

```bash
jarvis scheduler start
```

The standalone worker runs scheduled prompts through your configured inference engine and stays in the foreground until interrupted (++ctrl+c++). It uses `[scheduler].db_path` and `[scheduler].poll_interval`; pass `--poll-interval` to override the latter. Do not start a separate worker for a database already polled by `jarvis serve`.

### Create a task

```bash
# Run once at a specific time
jarvis scheduler create "Generate the weekly summary report" \
  --type once \
  --value "2026-03-01T09:00:00Z"

# Run every hour
jarvis scheduler create "Check for new emails and summarize" \
  --type interval \
  --value "3600" \
  --agent orchestrator \
  --tools retrieval,think

# Run on a cron schedule
jarvis scheduler create "Summarize overnight logs" \
  --type cron \
  --value "0 8 * * 1-5" \
  --timezone Europe/Madrid
```

### List tasks

```bash
# All tasks
jarvis scheduler list

# Active tasks only
jarvis scheduler list --status active

# Paused tasks
jarvis scheduler list --status paused
```

Example output:

```
ID               AGENT     TYPE       VALUE          STATUS   NEXT RUN
a3f9b12c4d8e    simple    cron       0 8 * * 1-5    active   2026-02-26T08:00:00+00:00
b7c2e56f1a3d    orchestr  interval   3600           active   2026-02-25T14:05:00+00:00
```

### Pause and resume tasks

```bash
# Pause a running task
jarvis scheduler pause a3f9b12c4d8e

# Resume -- next_run is recomputed from the current time
jarvis scheduler resume a3f9b12c4d8e
```

### Cancel a task

```bash
# Permanently cancel (status -> "cancelled", next_run cleared)
jarvis scheduler cancel a3f9b12c4d8e
```

### View run logs

```bash
# Last 10 executions for a task
jarvis scheduler logs a3f9b12c4d8e
```

Example output:

```
Run 1: started=2026-02-25T08:00:01Z finished=2026-02-25T08:00:04Z success=True
  Result: Overnight logs contain 3 warnings and no errors.
Run 2: started=2026-02-24T08:00:00Z finished=2026-02-24T08:00:05Z success=True
  Result: Logs are clean.
```

---

## Python API

```python title="scheduler_example.py"
from openjarvis.scheduler.store import SchedulerStore
from openjarvis.scheduler.scheduler import TaskScheduler

# Set up storage
store = SchedulerStore(db_path="~/.openjarvis/scheduler.db")  # (1)!

# Wire in a JarvisSystem for task execution
from openjarvis import Jarvis
jarvis = Jarvis()

scheduler = TaskScheduler(
    store=store,
    system=jarvis,         # (2)!
    poll_interval=60,      # (3)!
)

# Create tasks
daily_summary = scheduler.create_task(
    prompt="Summarize the latest news headlines",
    schedule_type="cron",
    schedule_value="0 8 * * *",
    agent="simple",
)
print(f"Created task {daily_summary.id}, next run: {daily_summary.next_run}")

# List active tasks
for task in scheduler.list_tasks(status="active"):
    print(f"  {task.id}: {task.prompt} @ {task.next_run}")

# Manage task state
scheduler.pause_task(daily_summary.id)
scheduler.resume_task(daily_summary.id)   # next_run recomputed from now
scheduler.cancel_task(daily_summary.id)  # permanent

# Start the background thread
scheduler.start()   # (4)!

# ... application runs ...

scheduler.stop()
jarvis.close()
```

1. SQLite database storing all task state and run logs.
2. The scheduler calls `system.ask(task.prompt, agent=task.agent, tools=...)` when a task is due. You can omit `system` to manage stored tasks, but the worker will not start without an execution system. To preview without consuming a task, use `jarvis scheduler run-task AGENT --dry-run`.
3. Seconds between polling cycles. Lower values increase responsiveness at the cost of more SQLite reads.
4. Starts a daemon thread named `"jarvis-scheduler"`. Daemon threads exit automatically when the main process exits.

---

## ScheduledTask Fields

Every task is represented as a `ScheduledTask` dataclass.

| Field            | Type              | Default       | Description                                       |
|------------------|-------------------|---------------|---------------------------------------------------|
| `id`             | `str`             | auto (16 hex) | Unique task identifier                            |
| `prompt`         | `str`             | --            | Query sent to the agent on execution              |
| `schedule_type`  | `str`             | --            | `"cron"`, `"interval"`, or `"once"`              |
| `schedule_value` | `str`             | --            | Cron expression, interval seconds, or ISO datetime|
| `context_mode`   | `str`             | `"isolated"`  | Execution context mode                            |
| `status`         | `str`             | `"active"`    | `"active"`, `"paused"`, `"completed"`, `"cancelled"` |
| `next_run`       | `str` or `None`   | computed      | ISO 8601 UTC datetime of the next execution       |
| `last_run`       | `str` or `None`   | `None`        | ISO 8601 UTC datetime of the last execution       |
| `agent`          | `str`             | `"simple"`    | Agent registry key to use for execution           |
| `tools`          | `str`             | `""`          | Comma-separated tool names for the agent          |
| `metadata`       | `dict`            | `{}`          | Arbitrary metadata for the task                   |

---

## Using Scheduler Tools with Agents

The five scheduler MCP tools (`schedule_task`, `list_scheduled_tasks`, `pause_scheduled_task`, `resume_scheduled_task`, `cancel_scheduled_task`) can be passed to any `ToolUsingAgent`, allowing an agent to schedule follow-up tasks autonomously.

```bash
# Let the orchestrator schedule its own follow-up
jarvis ask --agent orchestrator \
  --tools schedule_task,list_scheduled_tasks \
  "Research transformer architectures and schedule a daily summary at 8am"
```

```python
from openjarvis import Jarvis

j = Jarvis()
response = j.ask(
    "Schedule a weekly digest of research papers every Monday at 9am",
    agent="orchestrator",
    tools=["schedule_task"],
)
print(response)
```

See [Scheduler Tools](tools.md#scheduler-tools) for full parameter reference.

---

## Configuration

Scheduler settings live in the `[scheduler]` section of `~/.openjarvis/config.toml`.

```toml title="~/.openjarvis/config.toml"
[scheduler]
enabled = false
db_path = "~/.openjarvis/scheduler.db"
poll_interval = 60
default_agent = "simple"
```

| Key              | Type   | Default                          | Description                                |
|------------------|--------|----------------------------------|--------------------------------------------|
| `enabled`        | `bool` | `false`                          | Start the scheduler daemon automatically   |
| `db_path`        | `str`  | `~/.openjarvis/scheduler.db`     | SQLite database path                       |
| `poll_interval`  | `int`  | `60`                             | Seconds between polling cycles             |
| `default_agent`  | `str`  | `"simple"`                       | Default agent for tasks that omit `agent`  |

---

## See Also

- [Scheduler Tools reference](tools.md#scheduler-tools) -- MCP tool parameter details
- [Architecture: Agentic Logic](../architecture/agents.md) -- how the scheduler integrates with agents
- [Deployment: systemd](../deployment/systemd.md) -- running the scheduler as a system service
