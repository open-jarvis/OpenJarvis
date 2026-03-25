# Tools

The tool system enables agents to perform actions beyond text generation -- calculations, memory lookups, file reading, and sub-model calls. Tools follow a spec-driven design with a central dispatch engine and OpenAI function-calling format support.

## Architecture

```
Agent  -->  Engine (with tool defs)  -->  tool_calls response  -->  ToolExecutor  -->  Tool.execute()
  ^                                                                                          |
  |                                                                                          v
  +-------------------------------  ToolResult  <--------------------------------------------+
```

---

## BaseTool ABC

All tools implement the `BaseTool` abstract base class.

```python
from abc import ABC, abstractmethod
from openjarvis.tools._stubs import ToolSpec
from openjarvis.core.types import ToolResult

class BaseTool(ABC):
    tool_id: str

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """Return the tool specification."""

    @abstractmethod
    def execute(self, **params) -> ToolResult:
        """Execute the tool with the given parameters."""

    def to_openai_function(self) -> dict:
        """Convert to OpenAI function-calling format."""
```

The `to_openai_function()` method is provided by the base class and converts the tool's spec into the format expected by OpenAI-compatible APIs:

```json
{
  "type": "function",
  "function": {
    "name": "calculator",
    "description": "Evaluate a mathematical expression safely.",
    "parameters": {
      "type": "object",
      "properties": {
        "expression": {
          "type": "string",
          "description": "Math expression to evaluate"
        }
      },
      "required": ["expression"]
    }
  }
}
```

---

## ToolSpec

The `ToolSpec` dataclass describes a tool's interface and characteristics.

| Field                  | Type             | Default | Description                                        |
|------------------------|------------------|---------|----------------------------------------------------|
| `name`                 | `str`            | --      | Unique tool identifier                             |
| `description`          | `str`            | --      | Human-readable description (sent to the model)     |
| `parameters`           | `dict[str, Any]` | `{}`    | JSON Schema for the tool's parameters              |
| `category`             | `str`            | `""`    | Tool category (e.g., `math`, `memory`, `reasoning`) |
| `cost_estimate`        | `float`          | `0.0`   | Estimated cost per invocation                      |
| `latency_estimate`     | `float`          | `0.0`   | Estimated latency per invocation                   |
| `requires_confirmation`| `bool`           | `False` | Whether the tool requires user confirmation        |
| `metadata`             | `dict[str, Any]` | `{}`    | Additional metadata                                |

---

## ToolResult

The `ToolResult` dataclass holds the result of a tool execution.

| Field             | Type             | Default | Description                              |
|-------------------|------------------|---------|------------------------------------------|
| `tool_name`       | `str`            | --      | Name of the tool that was called         |
| `content`         | `str`            | --      | The tool's output (text)                 |
| `success`         | `bool`           | `True`  | Whether the execution succeeded          |
| `usage`           | `dict[str, Any]` | `{}`    | Token usage (for LLM tool)               |
| `cost_usd`        | `float`          | `0.0`   | Actual cost of the invocation            |
| `latency_seconds` | `float`          | `0.0`   | Measured execution latency               |
| `metadata`        | `dict[str, Any]` | `{}`    | Additional metadata                      |

---

## ToolExecutor

The `ToolExecutor` is the central dispatch engine for tool calls. It manages a set of tool instances, parses JSON arguments, measures execution latency, and publishes events on the event bus.

```python
from openjarvis.tools._stubs import ToolExecutor

executor = ToolExecutor(tools=[calculator, think_tool], bus=event_bus)

# Get OpenAI-format tool definitions
openai_tools = executor.get_openai_tools()

# Execute a tool call
from openjarvis.core.types import ToolCall
tc = ToolCall(id="call_1", name="calculator", arguments='{"expression": "2+2"}')
result = executor.execute(tc)
print(result.content)  # "4"
```

### Execution Flow

1. **Parse arguments:** The `arguments` JSON string from the `ToolCall` is deserialized.
2. **Publish start event:** `TOOL_CALL_START` is emitted on the event bus with tool name and arguments.
3. **Execute:** The tool's `execute()` method is called with the parsed parameters.
4. **Measure latency:** Execution time is recorded in `result.latency_seconds`.
5. **Publish end event:** `TOOL_CALL_END` is emitted with success status and latency.
6. **Return result:** The `ToolResult` is returned to the caller.

If the tool name is unknown, a `ToolResult` with `success=False` is returned. If JSON parsing fails or the tool raises an exception, the error is captured and returned as a failed `ToolResult`.

### Methods

| Method              | Returns                | Description                                |
|---------------------|------------------------|--------------------------------------------|
| `execute(tool_call)`| `ToolResult`           | Parse args, dispatch, measure, emit events |
| `available_tools()` | `list[ToolSpec]`       | Return specs for all registered tools      |
| `get_openai_tools()`| `list[dict]`           | Return tools in OpenAI function format     |

---

## build_tool_descriptions()

The `build_tool_descriptions()` function is the **single source of truth** for generating enriched tool descriptions used in agent system prompts. All text-based agents (`NativeReActAgent`, `NativeOpenHandsAgent`, `RLMAgent`, `OrchestratorAgent` in structured mode) use this function to produce Markdown-formatted tool sections.

### Parameters

| Parameter          | Type             | Default | Description                                          |
|--------------------|------------------|---------|------------------------------------------------------|
| `tools`            | `list[BaseTool]` | --      | List of tool instances to describe                   |
| `include_category` | `bool`           | `True`  | Whether to include the `Category:` line              |
| `include_cost`     | `bool`           | `False` | Whether to include cost and latency estimate lines   |

### Usage

```python
from openjarvis.tools._stubs import build_tool_descriptions
from openjarvis.tools.calculator import CalculatorTool
from openjarvis.tools.think import ThinkTool

tools = [CalculatorTool(), ThinkTool()]
desc = build_tool_descriptions(tools)
print(desc)
# ### calculator
# Evaluate a mathematical expression safely.
# Category: math
# Parameters:
#   - expression (string, required): Math expression to evaluate
#
# ### think
# Reasoning scratchpad ...
```

### Agents using this builder

- **NativeReActAgent** -- Injects descriptions into the ReAct system prompt
- **NativeOpenHandsAgent** -- Injects descriptions into the CodeAct system prompt
- **RLMAgent** -- Adds an `## Available Tools` section to the REPL system prompt
- **OrchestratorAgent** (structured mode) -- Passes `tools=` to `build_system_prompt()` which delegates to this builder

---

## Built-in Tools Summary

All built-in tools are registered via `@ToolRegistry.register()` and are available by name to agents and the CLI.

| Category | Registry Key | Description |
|----------|-------------|-------------|
| **Reasoning** | `think` | Zero-cost reasoning scratchpad for chain-of-thought |
| **Math** | `calculator` | Safe math expression evaluator (ast-based) |
| **Code** | `code_interpreter` | Execute Python code in a sandboxed subprocess |
| **Code** | `code_interpreter_docker` | Execute Python code in a disposable Docker container |
| **Code** | `repl` | Persistent Python REPL with state across calls |
| **Search** | `web_search` | Web search returning result summaries |
| **File I/O** | `file_read` | Read file contents with safety validations |
| **HTTP** | `http_request` | Make HTTP requests with SSRF protection |
| **Memory** | `retrieval` | Search the memory backend for relevant context |
| **Memory** | `memory_store` | Store content in the memory backend |
| **Memory** | `memory_retrieve` | Retrieve relevant content from the memory backend |
| **Memory** | `memory_search` | Full-text search across stored memory |
| **Memory** | `memory_index` | Index a file or directory into the memory backend |
| **Inference** | `llm` | Delegate a sub-query to an inference engine |
| **Channel** | `channel_send` | Send a message via a channel (Telegram, Discord, etc.) |
| **Channel** | `channel_list` | List available messaging channels |
| **Channel** | `channel_status` | Check the connection status of a messaging channel |
| **Scheduler** | `schedule_task` | Schedule a task for future or recurring execution |
| **Scheduler** | `list_scheduled_tasks` | List all scheduled tasks |
| **Scheduler** | `pause_scheduled_task` | Pause an active scheduled task |
| **Scheduler** | `resume_scheduled_task` | Resume a paused scheduled task |
| **Scheduler** | `cancel_scheduled_task` | Cancel a scheduled task permanently |
| **Integration** | `mcp_adapter` | Bridge to external MCP tool servers (see [External MCP Servers](mcp-external-servers.md)) |

---

## Built-in Tool Details

### Calculator

**Registry key:** `calculator` | **Category:** `math`

Evaluates mathematical expressions safely using Python's `ast` module. No arbitrary code execution -- only whitelisted operations are allowed.

**Parameters:**

| Parameter    | Type   | Required | Description                              |
|--------------|--------|----------|------------------------------------------|
| `expression` | string | Yes      | Math expression (e.g., `"2+3*4"`, `"sqrt(16)"`) |

**Supported operations:**

| Category     | Operations                                                    |
|--------------|---------------------------------------------------------------|
| Arithmetic   | `+`, `-`, `*`, `/`, `//` (floor div), `%` (mod), `**` (power) |
| Functions    | `abs`, `round`, `min`, `max`, `sqrt`, `log`, `log10`, `log2` |
| Trigonometry | `sin`, `cos`, `tan`                                           |
| Rounding     | `ceil`, `floor`                                               |
| Constants    | `pi`, `e`                                                     |

**Example:**

```python
from openjarvis.tools.calculator import CalculatorTool

calc = CalculatorTool()
result = calc.execute(expression="sqrt(144) + 3**2")
print(result.content)   # "21.0"
print(result.success)   # True
```

### Think

**Registry key:** `think` | **Category:** `reasoning`

A zero-cost reasoning scratchpad. The input is echoed back as the output, allowing the model to "think out loud" during a tool-calling loop. This enables chain-of-thought reasoning within the agent workflow.

**Parameters:**

| Parameter | Type   | Required | Description                              |
|-----------|--------|----------|------------------------------------------|
| `thought` | string | Yes      | The reasoning or thought process         |

**Example:**

```python
from openjarvis.tools.think import ThinkTool

think = ThinkTool()
result = think.execute(thought="Let me break this problem into steps...")
print(result.content)   # "Let me break this problem into steps..."
print(result.success)   # True
```

!!! info "Cost and Latency"
    The Think tool has zero cost and near-zero latency, making it ideal for structured reasoning without consuming additional resources.

### Retrieval

**Registry key:** `retrieval` | **Category:** `memory`

Searches the memory backend for relevant context and returns formatted results with source attribution.

**Parameters:**

| Parameter | Type    | Required | Description                              |
|-----------|---------|----------|------------------------------------------|
| `query`   | string  | Yes      | Search query                             |
| `top_k`   | integer | No       | Number of results (default: 5)           |

**Constructor parameters:**

| Parameter | Type            | Default | Description                    |
|-----------|-----------------|---------|--------------------------------|
| `backend` | `MemoryBackend` | `None`  | Memory backend to search       |
| `top_k`   | `int`           | `5`     | Default number of results      |

**Example:**

```python
from openjarvis.tools.retrieval import RetrievalTool
from openjarvis.memory.sqlite import SQLiteMemory

backend = SQLiteMemory(db_path="./memory.db")
retrieval = RetrievalTool(backend=backend)
result = retrieval.execute(query="machine learning")
print(result.content)   # Formatted context with source tags
```

### LLM

**Registry key:** `llm` | **Category:** `inference`

Delegates a sub-query to an inference engine. Useful for summarization, sub-questions, or generating structured output within an agent workflow.

**Parameters:**

| Parameter | Type   | Required | Description                              |
|-----------|--------|----------|------------------------------------------|
| `prompt`  | string | Yes      | The prompt to send to the model          |
| `system`  | string | No       | Optional system message for context      |

**Constructor parameters:**

| Parameter | Type              | Default | Description                    |
|-----------|-------------------|---------|--------------------------------|
| `engine`  | `InferenceEngine` | `None`  | Inference engine to use        |
| `model`   | `str`             | `""`    | Model identifier               |

**Example:**

```python
from openjarvis.tools.llm_tool import LLMTool

llm = LLMTool(engine=my_engine, model="qwen3:8b")
result = llm.execute(
    prompt="Summarize: AI is transforming industries...",
    system="You are a concise summarizer.",
)
print(result.content)
```

### FileRead

**Registry key:** `file_read` | **Category:** `filesystem`

Reads file contents with safety validations. Supports optional directory restrictions, file size limits (1 MB max), and line count limiting.

**Parameters:**

| Parameter   | Type    | Required | Description                              |
|-------------|---------|----------|------------------------------------------|
| `path`      | string  | Yes      | Path to the file to read                 |
| `max_lines` | integer | No       | Maximum lines to return (default: all)   |

**Constructor parameters:**

| Parameter      | Type         | Default | Description                                   |
|----------------|--------------|---------|-----------------------------------------------|
| `allowed_dirs` | `list[str]`  | `None`  | Restrict file access to these directories     |

**Safety features:**

- Path validation against allowed directories (when configured)
- Maximum file size: 1 MB
- UTF-8 encoding required (rejects binary files)
- Existence and file-type checks

**Example:**

```python
from openjarvis.tools.file_read import FileReadTool

reader = FileReadTool(allowed_dirs=["/home/user/projects"])
result = reader.execute(path="/home/user/projects/README.md", max_lines=50)
print(result.content)
print(result.metadata)  # {"path": "/home/user/projects/README.md", "size_bytes": 1234}
```

### WebSearch

**Registry key:** `web_search` | **Category:** `search`

Searches the web and returns a result summary. Useful for queries that need current information.

**Parameters:**

| Parameter | Type   | Required | Description                              |
|-----------|--------|----------|------------------------------------------|
| `query`   | string | Yes      | Search query string                      |

### CodeInterpreter

**Registry key:** `code_interpreter` | **Category:** `code`

Executes Python code snippets in a sandboxed environment and returns the output. Used by `NativeOpenHandsAgent` for CodeAct-style execution.

**Parameters:**

| Parameter | Type   | Required | Description                              |
|-----------|--------|----------|------------------------------------------|
| `code`    | string | Yes      | Python code to execute                   |

---

## Scheduler Tools

The scheduler tools expose `TaskScheduler` operations as MCP-discoverable tools. They allow agents to programmatically create, manage, and inspect scheduled tasks. All scheduler tools are in the `scheduler` category and require a `TaskScheduler` instance to be configured in the system.

!!! info "Scheduler dependency"
    The scheduler tools only function when a `TaskScheduler` is wired into the system (via `SystemBuilder`). If no scheduler is configured, all scheduler tool calls return a `success=False` result with a message explaining that the scheduler is unavailable.

### schedule_task

**Registry key:** `schedule_task` | **Category:** `scheduler`

Schedules a new task for future or recurring execution.

**Parameters:**

| Parameter        | Type   | Required | Description                                                                  |
|------------------|--------|----------|------------------------------------------------------------------------------|
| `prompt`         | string | Yes      | The query or prompt to execute on schedule                                   |
| `schedule_type`  | string | Yes      | One of `"cron"`, `"interval"`, or `"once"`                                  |
| `schedule_value` | string | Yes      | Cron expression, interval in seconds, or ISO 8601 datetime for one-time run |
| `agent`          | string | No       | Agent to use for execution (default: `"simple"`)                             |
| `tools`          | string | No       | Comma-separated tool names for the agent (e.g., `"calculator,think"`)       |

**Schedule type examples:**

| `schedule_type` | `schedule_value`       | Meaning                              |
|-----------------|------------------------|--------------------------------------|
| `once`          | `"2026-03-01T09:00:00Z"` | Run once at that UTC time           |
| `interval`      | `"3600"`               | Run every 3600 seconds (1 hour)      |
| `cron`          | `"0 9 * * 1-5"`        | Run at 09:00 UTC, Monday–Friday      |

**Returns:** JSON with `task_id`, `next_run` (ISO 8601), and `status`.

**Example (via agent tool call):**

```python
from openjarvis.scheduler.tools import ScheduleTaskTool
from openjarvis.scheduler.scheduler import TaskScheduler
from openjarvis.scheduler.store import SchedulerStore

store = SchedulerStore(db_path="~/.openjarvis/scheduler.db")
scheduler = TaskScheduler(store=store, system=jarvis_system)
scheduler.start()

tool = ScheduleTaskTool()
tool._scheduler = scheduler

result = tool.execute(
    prompt="Summarize the daily news",
    schedule_type="cron",
    schedule_value="0 8 * * *",
    agent="simple",
)
# result.content: '{"task_id": "a3f9b12c", "next_run": "2026-02-26T08:00:00+00:00", "status": "active"}'
```

### list_scheduled_tasks

**Registry key:** `list_scheduled_tasks` | **Category:** `scheduler`

Returns all scheduled tasks, optionally filtered by status.

**Parameters:**

| Parameter | Type   | Required | Description                                                          |
|-----------|--------|----------|----------------------------------------------------------------------|
| `status`  | string | No       | Filter by status: `"active"`, `"paused"`, `"completed"`, `"cancelled"` |

**Returns:** JSON array of task objects.

### pause_scheduled_task

**Registry key:** `pause_scheduled_task` | **Category:** `scheduler`

Pauses an active scheduled task. The task is preserved and can be resumed later.

**Parameters:**

| Parameter | Type   | Required | Description         |
|-----------|--------|----------|---------------------|
| `task_id` | string | Yes      | ID of task to pause |

### resume_scheduled_task

**Registry key:** `resume_scheduled_task` | **Category:** `scheduler`

Resumes a paused task. The `next_run` time is recomputed from the current time.

**Parameters:**

| Parameter | Type   | Required | Description          |
|-----------|--------|----------|----------------------|
| `task_id` | string | Yes      | ID of task to resume |

### cancel_scheduled_task

**Registry key:** `cancel_scheduled_task` | **Category:** `scheduler`

Cancels a task permanently (sets status to `"cancelled"` and clears `next_run`). Cancelled tasks are not executed again.

**Parameters:**

| Parameter | Type   | Required | Description           |
|-----------|--------|----------|-----------------------|
| `task_id` | string | Yes      | ID of task to cancel  |

---

## Tool Registration

Tools are registered via the `@ToolRegistry.register()` decorator, making them discoverable by name at runtime.

```python
from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.core.types import ToolResult


@ToolRegistry.register("my_tool")
class MyTool(BaseTool):
    tool_id = "my_tool"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="my_tool",
            description="A custom tool that does something useful.",
            parameters={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "The input to process.",
                    },
                },
                "required": ["input"],
            },
            category="custom",
        )

    def execute(self, **params) -> ToolResult:
        value = params.get("input", "")
        return ToolResult(
            tool_name="my_tool",
            content=f"Processed: {value}",
            success=True,
        )
```

After registration, use the tool with an agent:

```bash
jarvis ask --agent orchestrator --tools my_tool "Process this data"
```

---

## Using Tools with Agents

### Via CLI

Tools are specified as a comma-separated list with the `--tools` flag. An agent (typically `orchestrator`) must be selected:

```bash
# Single tool
jarvis ask --agent orchestrator --tools calculator "What is 15% of 340?"

# Multiple tools
jarvis ask --agent orchestrator --tools calculator,think "Solve: 2x + 5 = 13"

# All available tools (list them)
jarvis ask --agent orchestrator --tools calculator,think,retrieval,file_read "..."
```

### Via Python SDK

Tools are passed as a list of name strings:

```python
from openjarvis import Jarvis

j = Jarvis()

# Use calculator and think tools
result = j.ask_full(
    "What is the area of a circle with radius 7?",
    agent="orchestrator",
    tools=["calculator", "think"],
)

for tr in result["tool_results"]:
    print(f"  {tr['tool_name']}: {tr['content']} (success={tr['success']})")

j.close()
```

The SDK automatically instantiates tool objects with appropriate dependencies. For example, the `retrieval` tool receives the configured memory backend, and the `llm` tool receives the active engine and model.
