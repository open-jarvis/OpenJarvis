# Deep Research Assistant

A tutorial example demonstrating how to build a multi-source research agent
using OpenJarvis. The assistant uses an orchestrator agent loop with web
search, memory storage, and file output to produce comprehensive research
reports with citations.

## What This Example Demonstrates

- **Orchestrator agent loop** -- the agent iterates through multiple
  tool-calling turns, deciding at each step whether to search, store, or
  synthesize.
- **Memory-augmented reasoning** -- findings from earlier searches are stored
  in memory and retrieved later for cross-referencing and deduplication.
- **Tool composition** -- five tools (`web_search`, `think`, `file_write`,
  `memory_store`, `memory_search`) are wired together through a single recipe
  config.
- **Recipe-driven configuration** -- `research.toml` captures the full
  pillar-aligned setup (model, engine, agent, tools) in a declarative file.

## Prerequisites

- Python 3.10 or later
- OpenJarvis installed (`uv sync --extra dev` from the repo root)
- An inference engine running. Either:
  - **Ollama** (local): `ollama serve` and `ollama pull qwen3:8b`
  - **Cloud API** (remote): set the appropriate key in `.env` and use
    `--engine cloud`

## Quick Start

```bash
# From the repository root
python examples/deep_research/research.py "quantum computing advances 2026"
```

Save the output to a file:

```bash
python examples/deep_research/research.py "quantum computing advances 2026" \
    --output report.md
```

Use a different model or engine:

```bash
python examples/deep_research/research.py "climate policy trends" \
    --model gpt-4o --engine cloud --max-turns 20
```

## Configuration Options

| Flag           | Default    | Description                              |
|----------------|------------|------------------------------------------|
| `--model`      | `qwen3:8b` | Model identifier passed to the engine   |
| `--engine`     | `ollama`   | Engine backend (ollama, cloud, vllm ...) |
| `--max-turns`  | `15`       | Maximum orchestrator loop iterations     |
| `--output`     | (none)     | File path to save the final report       |

The companion `research.toml` provides the same defaults as a declarative
recipe that can be loaded with `load_recipe()` or passed to the `jarvis eval`
runner.

## How It Works

```
User query
  |
  v
Jarvis SDK  (model + engine selection)
  |
  v
OrchestratorAgent  (multi-turn tool loop, up to max_turns)
  |
  +---> web_search    -- fetch recent sources from the web
  +---> think         -- internal reasoning scratchpad
  +---> memory_store  -- persist key findings for later retrieval
  +---> memory_search -- cross-reference earlier findings
  +---> file_write    -- save the final report to disk
  |
  v
Synthesized report with citations
```

Each turn, the orchestrator decides which tool to call (or whether to produce
a final answer). The `think` tool lets the model reason without side effects,
while `memory_store` / `memory_search` give it persistent scratch space across
turns.

## Customization Tips

- **Add more tools** -- append tool names to the `tools` list in
  `research.toml` or pass them on the command line. See `jarvis agent info
  orchestrator` for the full tool catalog.
- **Adjust temperature** -- lower values (0.2) produce more focused reports;
  higher values (0.8) encourage broader exploration.
- **Swap the agent** -- replace `orchestrator` with `native_react` for a
  Thought-Action-Observation loop, or `native_openhands` for a CodeAct-style
  agent.
- **Use the recipe programmatically** -- load the TOML with
  `openjarvis.recipes.load_recipe("examples/deep_research/research.toml")` and
  pass the result to `SystemBuilder`.

## Further Reading

- [Architecture: Agents](../../docs/architecture/agents.md) -- agent hierarchy (`BaseAgent`,
  `ToolUsingAgent`, `OrchestratorAgent`) and the `accepts_tools` mechanism.
- [Architecture: Tools](../../docs/user-guide/tools.md) -- tool registry, MCP adapter, and
  the `ToolExecutor` dispatch pipeline.
- [Recipes](../../src/openjarvis/recipes/) -- composable TOML configs that
  wire all five pillars.
