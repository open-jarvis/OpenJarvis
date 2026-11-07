# Scheduled Personal Ops

This tutorial demonstrates how to use FridayAI to run **autonomous scheduled agents** that perform recurring personal tasks on a cron-like schedule.

## What This Demonstrates

- Using the `Friday` SDK with different agent types (`orchestrator`, `native_react`) and tool sets
- Configuring recurring schedules via TOML and the `friday scheduler` CLI
- Integrating with the `TaskScheduler` Python API for programmatic task registration
- Graceful error handling when an inference engine is not available

## Scripts

| Script | Agent | Tools | Schedule | Purpose |
|---|---|---|---|---|
| `daily_digest.py` | `orchestrator` | `web_search`, `think` | Daily 9:00 AM | Search and summarize top news for chosen topics |
| `code_review.py` | `native_react` | `git_log`, `git_diff`, `file_read`, `think` | Monday 8:00 AM | Review the past week of commits in a repository |
| `gym_scheduler.py` | `orchestrator` | `web_search`, `think` | MWF 6:00 AM | Check gym hours and class availability |

## Quick Start

### 1. Run a script manually

```bash
# News digest for AI and robotics
uv run python examples/scheduled_ops/daily_digest.py --topics "AI,robotics"

# Code review of the current repo (last 7 days)
uv run python examples/scheduled_ops/code_review.py --repo-path .

# Gym schedule check
uv run python examples/scheduled_ops/gym_scheduler.py --gym "24 Hour Fitness"
```

All scripts accept `--model` and `--engine` flags to select a specific model or backend:

```bash
uv run python examples/scheduled_ops/daily_digest.py \
    --model qwen3:8b --engine ollama --topics "AI,finance"
```

### 2. Set up schedules using the CLI

Register each script as a recurring task with `friday scheduler create`:

```bash
# Morning digest every day at 9 AM
friday scheduler create "Run daily news digest" \
    --type cron --value "0 9 * * *"

# Weekly code review every Monday at 8 AM
friday scheduler create "Run weekly code review" \
    --type cron --value "0 8 * * 1"

# Gym check on MWF at 6 AM
friday scheduler create "Check gym schedule" \
    --type cron --value "0 6 * * 1,3,5"
```

Then start the scheduler daemon:

```bash
friday scheduler start
```

### 3. Use the TOML configuration

The `schedules.toml` file defines all three schedules in one place:

```toml
[schedules.daily_digest]
type = "cron"
value = "0 9 * * *"
description = "Morning news and social media digest"
script = "daily_digest.py"
```

You can point your own tooling or a custom loader at this file to register tasks in bulk.

### 4. Register via the Python API

The `gym_scheduler.py` script includes a `--register` flag that demonstrates programmatic task registration:

```bash
uv run python examples/scheduled_ops/gym_scheduler.py --register --gym "Planet Fitness"
```

This uses `TaskScheduler` and `SchedulerStore` directly:

```python
from friday_ai.scheduler import TaskScheduler
from friday_ai.scheduler.store import SchedulerStore

store = SchedulerStore()
scheduler = TaskScheduler(store)
task = scheduler.create_task(
    prompt="Check gym schedule for 'Planet Fitness'",
    schedule_type="cron",
    schedule_value="0 6 * * 1,3,5",
    agent="orchestrator",
    tools="web_search,think",
)
print(f"Task registered: {task.id}, next run: {task.next_run}")
```

## Adding Slack or Channel Output

To send results to a Slack channel (or any other supported channel), pipe the output or extend the scripts:

```bash
# Pipe output to a channel
uv run python examples/scheduled_ops/daily_digest.py | friday channel send slack

# Or add channel output inside the script:
# from friday_ai.channels import ChannelRegistry
# channel = ChannelRegistry.create("slack", webhook_url="https://hooks.slack.com/...")
# channel.send(response)
```

See `friday channel list` for all available channels.

## Customization Tips

- **Change topics**: Use `--topics "finance,healthcare,sports"` for different digest subjects.
- **Review window**: Use `--days 14` with `code_review.py` for a two-week review cycle.
- **Different agents**: Swap `orchestrator` for `native_react` (or vice versa) in the scripts to compare agent behavior.
- **Add tools**: Extend the `tools` list in any script (e.g., add `"calculator"` or `"file_write"` for saving reports to disk).
- **Model selection**: Use `--model` to target a specific model, or let FridayAI auto-select from what is available.
- **Cron expressions**: Standard five-field cron syntax is supported. Install `croniter` for full expression parsing; without it, basic hour/minute patterns still work.
