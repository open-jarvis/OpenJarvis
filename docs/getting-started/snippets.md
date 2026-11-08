---
title: Code Snippets
description: Copy-paste patterns for common FridayAI tasks
---

# Code Snippets

Ready-to-use patterns for the most common FridayAI tasks. Each snippet is self-contained and copy-pasteable.

## Ask a Question (3 lines)

```python
from friday_ai import Friday

with Friday() as j:
    print(j.ask("What is the capital of France?"))
```

## Stream Tokens (4 lines)

```python
import asyncio
from friday_ai import Friday

async def main():
    with Friday() as j:
        async for token in j.ask_stream("Tell me a story"):
            print(token, end="", flush=True)

asyncio.run(main())
```

## Agent with Tools (5 lines)

```python
from friday_ai import Friday

with Friday() as j:
    result = j.ask_full(
        "Search the web for the latest Python release",
        agent="orchestrator",
        tools=["web_search", "think"],
    )
    print(result["content"])
```

## Memory: Index + Search (6 lines)

```python
from friday_ai import Friday

with Friday() as j:
    j.memory.index("./docs/", chunk_size=512)
    results = j.memory.search("deployment options")
    for r in results:
        print(f"[{r['score']:.3f}] {r['content'][:100]}")
```

## Recipe TOML (4 lines)

Define an agent pipeline in TOML — no code required:

```toml
[recipe]
name = "research_assistant"
agent = "orchestrator"
tools = ["web_search", "think", "file_read"]
prompt = "Research the given topic and write a summary."
```

Run with: `friday compose run research_assistant "quantum computing advances"`

## API Server (1 command)

```bash
friday serve --port 8000 --engine ollama --model qwen3:8b
```

Any OpenAI-compatible client works against this endpoint.

## Docker Deployment (2 commands)

```bash
docker build -t friday_ai .
docker run -p 8000:8000 friday_ai serve --host 0.0.0.0
```

## Custom Tool (10 lines)

```python
from friday_ai.core.registry import ToolRegistry
from friday_ai.core.types import ToolResult
from friday_ai.tools._stubs import BaseTool, ToolSpec

@ToolRegistry.register("my_tool")
class MyTool(BaseTool):
    tool_id = "my_tool"

    @property
    def spec(self):
        return ToolSpec(name="my_tool", description="My custom tool",
                        parameters={"type": "object", "properties": {"input": {"type": "string"}}})

    def execute(self, **params):
        return ToolResult(tool_name="my_tool", content=f"Processed: {params.get('input', '')}", success=True)
```

## Multi-Model Routing (5 lines)

```python
from friday_ai import Friday

j = Friday()
# Router automatically selects the best model per query
simple = j.ask("What is 2+2?")            # routes to fast/cheap model
complex = j.ask("Analyze this research paper...")  # routes to capable model
j.close()
```

## Human-in-the-Loop Confirmation (6 lines)

```python
from friday_ai import Friday

with Friday() as j:
    result = j.ask_full(
        "Delete old log files in /tmp",
        agent="orchestrator",
        tools=["shell_exec", "file_read"],
    )
    print(f"Agent took {result['turns']} turns")
    print(result["content"])
```

Tools like `shell_exec` can be configured with `requires_confirmation: true` in TOML for interactive approval.
