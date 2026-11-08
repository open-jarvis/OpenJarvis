# Messaging Hub

A smart inbox assistant that triages incoming messages, classifies them by
priority, drafts replies, and produces end-of-day summaries — all powered by an
FridayAI orchestrator agent.

## What This Demonstrates

- **Channel integration** — connecting FridayAI to messaging platforms (Slack, WhatsApp, etc.)
- **Message triage** — automatic classification into URGENT, ACTION_REQUIRED, FYI, or SPAM
- **Smart replies** — context-aware reply drafting for actionable messages
- **Memory-backed summaries** — key information stored in memory for end-of-day rollups

## Prerequisites

- Python 3.10+
- FridayAI installed: `uv sync --extra dev`
- An inference engine running (e.g., Ollama with `qwen3:8b` pulled)

For live channel mode you also need the relevant channel credentials (see
[Setting Up Real Channels](#setting-up-real-channels) below).

## Quick Start

### Demo Mode

Run with sample messages — no channel setup or credentials needed:

```bash
python examples/messaging_hub/smart_inbox.py --demo
```

This processes five sample messages through the orchestrator agent, prints a
classification table, and generates an end-of-day summary.

### Override Model or Engine

```bash
python examples/messaging_hub/smart_inbox.py --demo --model gpt-4o --engine cloud
```

## How Message Classification Works

Each incoming message is sent to an orchestrator agent with a structured prompt
that asks for:

1. **Category** — one of `URGENT`, `ACTION_REQUIRED`, `FYI`, or `SPAM`
2. **Reply** — a concise professional response (or `N/A` for spam)

The agent uses the `think` tool for internal reasoning and `memory_store` /
`memory_search` to persist key details. After all messages are processed, a
second prompt asks the agent to summarize the inbox grouped by category.

## Setting Up Real Channels

### Slack

1. Add the Slack MCP server:
   ```bash
   friday add slack
   ```
2. Set credentials in your `.env`:
   ```
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_APP_TOKEN=xapp-...
   ```
3. Invite the bot to the target Slack channel.
4. Run:
   ```bash
   python examples/messaging_hub/smart_inbox.py --channel slack
   ```

### WhatsApp

1. Ensure Node.js 22+ is installed.
2. Configure the WhatsApp Baileys bridge (see the FridayAI channel docs).
3. Scan the QR code to authenticate.
4. Run:
   ```bash
   python examples/messaging_hub/smart_inbox.py --channel whatsapp
   ```

### Other Channels

FridayAI supports many channels — LINE, Viber, Mastodon, Rocket.Chat, and
more. List all available channels with:

```bash
friday channel list
```

## Channel Configuration via TOML

The `messaging.toml` recipe in this directory defines the default channel,
agent type, tools, and system prompt. You can customize it or point to your own:

```toml
[channel]
default = "slack"

[agent]
type = "orchestrator"
max_turns = 5
temperature = 0.3
tools = ["think", "memory_store", "memory_search"]
```

Refer to `configs/friday_ai/config.toml` for the full list of channel and agent
options.

## Adding Custom Triage Rules

To extend the classification categories or change how messages are routed, edit
the `CLASSIFICATION_PROMPT` in `smart_inbox.py`. For example, to add a
`FOLLOW_UP` category:

```python
CLASSIFICATION_PROMPT = (
    "Classify the following message into exactly one category: "
    "URGENT, ACTION_REQUIRED, FOLLOW_UP, FYI, or SPAM.\n"
    "Then draft a short reply if appropriate (not for SPAM).\n\n"
    "Respond in this exact format:\n"
    "CATEGORY: <category>\n"
    "REPLY: <reply or N/A>\n\n"
    "Message:\n{message}"
)
```

You can also add domain-specific rules by extending the system prompt in
`messaging.toml` — for instance, routing messages mentioning "P0" or
"incident" directly to URGENT regardless of phrasing.

## End-of-Day Summary

After processing all messages, the agent produces a grouped summary. In demo
mode this is printed to the terminal. In a production setup you could schedule
this via the FridayAI scheduler:

```bash
friday scheduler create "Daily inbox summary" --type cron --value "0 17 * * *"
```

Or use the operator recipe pattern to run a persistent triage agent on a
schedule. See `src/friday_ai/recipes/data/operators/` for examples.
