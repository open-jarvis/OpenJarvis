# Browser Assistant

A web browsing agent that uses FridayAI's orchestrator loop with browser,
web_search, and think tools to find and synthesize information from the web.

## Requirements

- FridayAI installed (`git clone https://github.com/open-jarvis/FridayAI.git && cd FridayAI && uv sync` or `uv sync --extra dev`)
- An inference engine running (Ollama, cloud API, vLLM, etc.)

## Usage

```bash
python examples/browser_assistant/browser_assistant.py --help
python examples/browser_assistant/browser_assistant.py --query "Find the latest Python 3.13 features"
python examples/browser_assistant/browser_assistant.py --query "Compare AWS vs GCP pricing" \
    --model gpt-4o --engine cloud --max-turns 20
```

## How It Works

The script creates a `Friday` instance configured with the `orchestrator` agent
and three tools:

- **browser** -- navigates to web pages and extracts content
- **web_search** -- searches the web for relevant results
- **think** -- internal reasoning scratchpad for the agent

The orchestrator runs a multi-turn loop: searching, browsing, reasoning, and
repeating until it has enough information to produce a comprehensive answer
with cited sources.
