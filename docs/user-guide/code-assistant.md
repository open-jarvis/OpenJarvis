# Code Assistant

An orchestrator agent with code execution, file I/O, and shell access. It can write scripts, read and explain code, run tests, fix bugs, and execute shell commands -- all locally on your machine.

## Quickstart (5 minutes)

### 1. Install and initialize

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync --extra dev
jarvis init --preset code-assistant
```

This writes a pre-configured `~/.openjarvis/config.toml` for the code assistant.

### 2. Start a local LLM via Ollama

```bash
# Install Ollama: https://ollama.com
ollama pull qwen3.5:9b
```

### 3. Ask a coding question

```bash
jarvis ask "Write a Python script that reads a CSV file and prints the top 5 rows"
```

The orchestrator agent will plan the approach, write the code, and can execute it if you approve.

## CLI Commands

```bash
# Ask a coding question (uses orchestrator agent by default with this config)
jarvis ask "Write a Python script that parses JSON from stdin"

# Read and explain existing code
jarvis ask "Read main.py and explain the architecture"

# Fix a bug
jarvis ask "Find and fix the bug in test_utils.py"

# Run tests
jarvis ask "Run the test suite and summarize any failures"

# Explicitly specify agent and tools
jarvis ask --agent orchestrator --tools code_interpreter "Calculate the first 20 Fibonacci numbers"

# Interactive chat for iterative coding
jarvis chat
```

## Configuration Reference

The preset writes this to `~/.openjarvis/config.toml`:

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:9b"
# default_model = "qwen3.5:35b"    # Better for complex code tasks

[agent]
default_agent = "orchestrator"      # Multi-turn with tool selection
max_turns = 10

[tools]
enabled = ["code_interpreter", "file_read", "file_write", "shell_exec", "web_search", "think", "calculator"]
```

### Key settings

| Setting | Default | Description |
|---------|---------|-------------|
| `intelligence.default_model` | `qwen3.5:9b` | The model for code generation. Use `qwen3.5:35b` for complex tasks like refactoring or multi-file changes. |
| `agent.default_agent` | `orchestrator` | Multi-turn agent that picks tools iteratively until it has an answer. |
| `agent.max_turns` | `10` | Maximum tool-calling iterations. Increase for multi-step tasks. |
| `tools.enabled` | 7 tools | `code_interpreter` (execute Python), `file_read`, `file_write`, `shell_exec` (run shell commands), `web_search`, `think`, `calculator`. |

### Tools explained

| Tool | What it does |
|------|-------------|
| `code_interpreter` | Executes Python code in a sandboxed environment and returns output. |
| `file_read` | Reads files with path validation. The agent can inspect source code, configs, logs. |
| `file_write` | Writes or modifies files. The agent can create scripts, patch code, write configs. |
| `shell_exec` | Runs shell commands (e.g., `git status`, `pytest`, `ls`). |
| `web_search` | Searches the web for documentation, Stack Overflow answers, etc. |
| `think` | Internal reasoning scratchpad for planning multi-step solutions. |
| `calculator` | Evaluates mathematical expressions. |

## Example Tasks

```bash
# Write a new script
jarvis ask "Write a Python script that converts YAML to JSON"

# Explain existing code
jarvis ask "Read src/openjarvis/core/events.py and explain the EventBus pattern"

# Debug a failing test
jarvis ask "Run pytest tests/test_memory.py -v and fix any failures"

# Refactor code
jarvis ask "Read utils.py and refactor the parse_config function to use dataclasses"

# Generate tests
jarvis ask "Read src/openjarvis/tools/calculator.py and write unit tests for it"

# Shell tasks
jarvis ask "Find all Python files larger than 100KB in this repo"
```

## Safety Notes

The `shell_exec` and `code_interpreter` tools execute real commands on your machine. Keep these in mind:

- **shell_exec** runs commands in your current user context. It can read, write, and delete files. Avoid running the agent on directories containing sensitive data without reviewing tool calls.
- **code_interpreter** executes Python code. It has access to your Python environment and installed packages.
- The agent asks for confirmation before executing potentially destructive commands when running in interactive mode (`jarvis chat`).
- For stronger isolation, use the sandboxed agent: `jarvis ask --agent sandboxed --tools code_interpreter "..."`, which runs inside a Docker/Podman container.

## Troubleshooting

**"Tool not found: code_interpreter"** -- Make sure your `config.toml` includes `code_interpreter` in the `tools.enabled` list.

**Agent loops without progress** -- Increase `max_turns` if the task is complex, or use a larger model (`qwen3.5:35b`). The 9b model handles most single-file tasks; multi-file refactoring benefits from more parameters.

**Shell command fails** -- The `shell_exec` tool runs commands relative to where you launched `jarvis`. Use `cd /path && command` in your prompt if needed, or run `jarvis` from the project directory.

**Web search not working** -- Install with `uv sync --extra tools-search` and set `TAVILY_API_KEY`.

**Code execution hangs** -- The `code_interpreter` has a default timeout. Long-running scripts will be terminated. Break large tasks into smaller steps.
