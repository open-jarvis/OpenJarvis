---
title: Python SDK
description: High-level Python interface for local inference, memory, and agent workflows
search:
  boost: 2
---

# Python SDK

The OpenJarvis Python SDK provides a high-level interface for interacting with local inference engines, managing memory, and running agent workflows. The primary entry point is the `Jarvis` class.

## Installation

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync
```

## Quick Start

```python
from openjarvis import Jarvis

j = Jarvis()
response = j.ask("What is the capital of France?")
print(response)
j.close()
```

---

## Jarvis Class

### Constructor

```python
Jarvis(
    *,
    config: JarvisConfig | None = None,
    config_path: str | None = None,
    engine_key: str | None = None,
    model: str | None = None,
)
```

| Parameter     | Type             | Default | Description                                                    |
|---------------|------------------|---------|----------------------------------------------------------------|
| `config`      | `JarvisConfig`   | `None`  | Provide a pre-built configuration object                       |
| `config_path` | `str`            | `None`  | Path to a TOML configuration file                              |
| `engine_key`  | `str`            | `None`  | Override the engine backend (`"ollama"`, `"vllm"`, etc.)       |
| `model`       | `str`            | `None`  | Override the default model (e.g., `"qwen3:8b"`)               |

If no `config` or `config_path` is provided, the SDK loads configuration from the default location (`~/.openjarvis/config.toml`), falling back to built-in defaults.

**Examples:**

```python
# Default configuration — auto-detects engine
j = Jarvis()

# Override the model
j = Jarvis(model="qwen3:8b")

# Override the engine
j = Jarvis(engine_key="ollama")

# Load from a specific config file
j = Jarvis(config_path="/path/to/config.toml")
```

### Properties

| Property  | Type           | Description                       |
|-----------|----------------|-----------------------------------|
| `config`  | `JarvisConfig` | The active configuration object   |
| `version` | `str`          | The OpenJarvis version string     |
| `memory`  | `MemoryHandle` | Proxy for memory operations       |

---

## `ask()` Method

Send a query and receive a plain-text response.

```python
ask(
    query: str,
    *,
    model: str | None = None,
    agent: str | None = None,
    tools: list[str] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    context: bool = True,
) -> str
```

| Parameter     | Type         | Default | Description                                          |
|---------------|--------------|---------|------------------------------------------------------|
| `query`       | `str`        | --      | The question or prompt to send                       |
| `model`       | `str`        | `None`  | Override the model for this call                     |
| `agent`       | `str`        | `None`  | Route through an agent (`"simple"`, `"orchestrator"`) |
| `tools`       | `list[str]`  | `None`  | Tool names to enable (requires agent mode)           |
| `temperature` | `float`      | `0.7`   | Sampling temperature                                 |
| `max_tokens`  | `int`        | `1024`  | Maximum tokens to generate                           |
| `context`     | `bool`       | `True`  | Whether to inject memory context                     |

**Returns:** A `str` containing the model's response text.

**Examples:**

```python
# Simple query
response = j.ask("What is machine learning?")

# Override model for this call
response = j.ask("Hello", model="llama3.2:3b")

# Disable memory context injection
response = j.ask("Tell me about Python", context=False)

# Adjust generation parameters
response = j.ask("Write a haiku", temperature=0.3, max_tokens=50)
```

---

## `ask_full()` Method

Send a query and receive a detailed result dictionary with metadata.

```python
ask_full(
    query: str,
    *,
    model: str | None = None,
    agent: str | None = None,
    tools: list[str] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    context: bool = True,
) -> dict[str, Any]
```

The parameters are identical to `ask()`.

**Returns:** A dictionary with the following keys:

=== "Direct Mode"

    | Key       | Type   | Description                              |
    |-----------|--------|------------------------------------------|
    | `content` | `str`  | The response text                        |
    | `usage`   | `dict` | Token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`) |
    | `model`   | `str`  | The model used                           |
    | `engine`  | `str`  | The engine backend used                  |

=== "Agent Mode"

    | Key            | Type         | Description                              |
    |----------------|--------------|------------------------------------------|
    | `content`      | `str`        | The response text                        |
    | `usage`        | `dict`       | Token usage (may be empty in agent mode) |
    | `tool_results` | `list[dict]` | Tool execution results                   |
    | `turns`        | `int`        | Number of agent turns taken              |
    | `model`        | `str`        | The model used                           |
    | `engine`       | `str`        | The engine backend used                  |

**Example:**

```python
result = j.ask_full("What is 2+2?")
print(result["content"])       # "4"
print(result["model"])         # "qwen3:8b"
print(result["engine"])        # "ollama"
print(result["usage"])         # {"prompt_tokens": 10, ...}
```

---

## Agent Mode

Pass the `agent` parameter to route queries through an agent. Agents can manage multi-turn conversations and use tools.

```python
# Simple agent — single turn, no tools
response = j.ask("Hello", agent="simple")

# Orchestrator agent — multi-turn with tool calling
response = j.ask(
    "What is sqrt(144) + 3^2?",
    agent="orchestrator",
    tools=["calculator", "think"],
)
```

When using agent mode with `ask_full()`, the result includes `tool_results` showing each tool invocation:

```python
result = j.ask_full(
    "Calculate 15% of 340",
    agent="orchestrator",
    tools=["calculator"],
)

print(result["content"])       # "15% of 340 is 51.0"
print(result["turns"])         # 2
print(result["tool_results"])
# [{"tool_name": "calculator", "content": "51.0", "success": True}]
```

Available agents: `simple`, `orchestrator`, `operative`, `monitor_operative`

Available tools: `calculator`, `think`, `retrieval`, `llm`, `file_read`

---

## MemoryHandle

The `Jarvis.memory` attribute provides a `MemoryHandle` for document indexing, search, and statistics. The memory backend is lazily initialized on first use.

### `index()`

Index a file or directory into the memory store.

```python
index(
    path: str,
    *,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> dict[str, Any]
```

| Parameter       | Type  | Default | Description                           |
|-----------------|-------|---------|---------------------------------------|
| `path`          | `str` | --      | Path to a file or directory to index  |
| `chunk_size`    | `int` | `512`   | Chunk size in tokens                  |
| `chunk_overlap` | `int` | `64`    | Overlap between chunks in tokens      |

**Returns:** A dictionary with `chunks` (count), `doc_ids` (list), and `path`.

```python
result = j.memory.index("./docs/")
print(f"Indexed {result['chunks']} chunks")
# Indexed 42 chunks

# Custom chunking parameters
result = j.memory.index("./notes/", chunk_size=256, chunk_overlap=32)
```

### `search()`

Search the memory store for relevant chunks.

```python
search(
    query: str,
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]
```

| Parameter | Type  | Default | Description                    |
|-----------|-------|---------|--------------------------------|
| `query`   | `str` | --      | The search query               |
| `top_k`   | `int` | `5`     | Number of results to return    |

**Returns:** A list of dictionaries, each containing `content`, `score`, `source`, and `metadata`.

```python
results = j.memory.search("neural networks")
for r in results:
    print(f"[{r['score']:.4f}] {r['source']}: {r['content'][:80]}...")
```

### `stats()`

Return memory backend statistics.

```python
stats() -> dict[str, Any]
```

**Returns:** A dictionary with `backend` (name) and `count` (document count, if available).

```python
info = j.memory.stats()
print(f"Backend: {info['backend']}, Documents: {info.get('count', 'N/A')}")
```

### `close()`

Release the memory backend and its resources.

```python
j.memory.close()
```

---

## Model and Engine Discovery

### `list_models()`

Return a list of model identifiers available on the active engine.

```python
models = j.list_models()
print(models)  # ["qwen3:8b", "llama3.2:3b", ...]
```

### `list_engines()`

Return a list of registered engine keys.

```python
engines = j.list_engines()
print(engines)  # ["ollama", "vllm", "llamacpp", ...]
```

---

## Resource Management

### `close()`

Release all resources held by the `Jarvis` instance, including the memory backend, telemetry store, and engine connection.

```python
j.close()
```

!!! tip "Context Manager Pattern"
    While `Jarvis` does not implement `__enter__`/`__exit__` directly, you should always call `close()` when done to free database connections and other resources:

    ```python
    j = Jarvis()
    try:
        response = j.ask("Hello")
        print(response)
    finally:
        j.close()
    ```

---

## Complete Example

```python
from openjarvis import Jarvis

# Initialize with auto-detected engine
j = Jarvis(model="qwen3:8b")

# Index documents for context-augmented responses
result = j.memory.index("./docs/")
print(f"Indexed {result['chunks']} chunks from {result['path']}")

# Simple query with memory context
response = j.ask("What are the main features?")
print(response)

# Detailed query with agent and tools
full_result = j.ask_full(
    "Calculate the square root of 256 and add 10",
    agent="orchestrator",
    tools=["calculator"],
)
print(f"Answer: {full_result['content']}")
print(f"Turns: {full_result['turns']}")
print(f"Tools used: {[t['tool_name'] for t in full_result['tool_results']]}")

# Search memory directly
results = j.memory.search("configuration")
for r in results:
    print(f"  [{r['score']:.3f}] {r['source']}")

# List available models
print("Models:", j.list_models())

# Clean up
j.close()
```
