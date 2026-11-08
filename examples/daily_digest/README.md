# Daily Digest

A morning briefing operator that searches the web for current news on your
chosen topics and produces a concise, structured summary.

## Requirements

- FridayAI installed (`git clone https://github.com/open-jarvis/FridayAI.git && cd FridayAI && uv sync` or `uv sync --extra dev`)
- An inference engine running (Ollama, cloud API, vLLM, etc.)

## Usage

```bash
python examples/daily_digest/daily_digest.py --help
python examples/daily_digest/daily_digest.py --topics "AI,robotics,space"
python examples/daily_digest/daily_digest.py --topics "finance,crypto" \
    --model gpt-4o --engine cloud --output digest.md
```

## How It Works

The script creates a `Friday` instance configured with the `orchestrator` agent
and two tools:

- **web_search** -- searches the web for current news on each topic
- **think** -- internal reasoning scratchpad to organize and prioritize findings

The orchestrator agent searches for each topic, reasons about what is most
newsworthy, and composes a daily briefing with per-topic bullet points and a
closing outlook paragraph. Optionally saves the output to a file.
