# Code Companion

A set of developer-focused scripts that use FridayAI tool-using agents
to automate common coding tasks: code review, debugging, and test generation.

## What This Demonstrates

Each script wires up a `Friday` instance with the `native_react` (ReAct) agent
and a curated set of tools. The ReAct loop lets the agent reason step by step
-- reading files, running commands, and thinking -- before producing a final
structured answer. This is the same pattern you can adapt for any code
intelligence workflow.

| Script | Purpose | Tools Used |
|---|---|---|
| `reviewer.py` | Review a git diff between two branches | `git_diff`, `git_log`, `file_read`, `think` |
| `debugger.py` | Investigate an error and propose a fix | `file_read`, `shell_exec`, `think` |
| `test_gen.py` | Generate comprehensive tests for a Python module | `file_read`, `think`, `file_write` |

## Prerequisites

1. **Install FridayAI** (from the repo root):

   ```bash
   uv sync --extra dev
   ```

2. **Start an inference engine.** The default is Ollama:

   ```bash
   ollama serve
   ollama pull qwen3:8b
   ```

   Alternatively, set up a cloud engine by sourcing your API keys:

   ```bash
   source .env
   ```

## Quick Start

### Code Review

Review the diff between a feature branch and `main`:

```bash
python examples/code_companion/reviewer.py --branch feature-x
```

Review the current HEAD against a specific base:

```bash
python examples/code_companion/reviewer.py --branch HEAD --base develop
```

### Debug Assistant

Investigate an error message:

```bash
python examples/code_companion/debugger.py --error "TypeError: NoneType has no attribute 'split'"
```

Point it at the file where the error occurred for faster root-cause analysis:

```bash
python examples/code_companion/debugger.py \
    --error "KeyError: 'user_id'" \
    --file src/app/views.py
```

### Test Generation

Generate pytest tests for a module:

```bash
python examples/code_companion/test_gen.py --module src/friday_ai/tools/calculator.py
```

Use unittest instead, and write to a specific file:

```bash
python examples/code_companion/test_gen.py \
    --module src/friday_ai/tools/calculator.py \
    --framework unittest \
    --output tests/test_calculator_generated.py
```

## How the ReAct Agent Loop Works

Each script uses the `native_react` agent, which follows the
**Thought-Action-Observation** cycle:

1. **Thought** -- The agent reasons about what to do next (often using the
   `think` tool to structure its reasoning).
2. **Action** -- The agent calls a tool (e.g., `git_diff`, `file_read`,
   `shell_exec`).
3. **Observation** -- The tool result is fed back to the agent.
4. **Repeat** until the agent has enough information to produce a final answer.

This loop allows the agent to adaptively explore the codebase rather than
relying on a single prompt/response exchange. For example, the reviewer might
read a diff, notice a suspicious function call, then read the source of that
function before making its assessment.

## Customization

### Model and Engine

All three scripts accept `--model` and `--engine` flags:

```bash
python examples/code_companion/reviewer.py --model gpt-4o --engine cloud
python examples/code_companion/debugger.py --model claude-sonnet-4-20250514 --engine cloud
```

### Tools

To change which tools an agent can use, edit the `tools` list in the script.
Available tools include `calculator`, `web_search`, `shell_exec`, `code_interpreter`,
`memory_store`, `memory_search`, and more. Run `uv run friday eval list` or
inspect `src/friday_ai/tools/` for the full registry.

### Prompts

Each script contains a `prompt` string that instructs the agent. Modify this
to change the review criteria, debugging strategy, or test generation style
to match your team's conventions.

## SDK Pattern

All three scripts follow the same core pattern:

```python
from friday_ai import Friday

j = Friday(model="qwen3:8b", engine_key="ollama")
try:
    response = j.ask(
        "Your task description here...",
        agent="native_react",
        tools=["git_diff", "file_read", "think"],
    )
    print(response)
finally:
    j.close()
```
