---
title: Quick Start
description: Get up and running with FridayAI in minutes
search:
  boost: 3
---

# Quick Start

!!! tip "Running `friday` commands"
    Every `friday ...` example below assumes you have either activated the project venv
    (`source .venv/bin/activate`) or are prefixing each command with `uv run`. A bare
    `friday init --preset ...` from a fresh clone will fail with `command not found`.

## What You Can Build

FridayAI is a modular AI assistant framework. Here's what developers build with it:

=== "Chat with Any Model"

    ```bash
    friday ask "Explain quantum entanglement" -m qwen3.5:4b   # use qwen3.5:9b or larger on GPU
    ```

=== "Agent + Tools"

    ```bash
    friday ask --agent orchestrator --tools calculator,web_search "What is the GDP of France in USD?"
    ```

=== "Index Docs & Ask"

    ```bash
    friday memory index ./docs/
    friday ask "How do I configure the engine?"
    ```

    !!! warning "Requires the Rust extension"
        `friday memory index` and `friday memory search` import `friday_ai_rust`. If you
        skipped the `uv run maturin develop -m rust/crates/friday_ai-python/Cargo.toml`
        step in [Installation](installation.md), these commands fail with
        `ModuleNotFoundError: No module named 'friday_ai_rust'`. Build the extension
        once and any preset (including `deep-research`) will work.

=== "5-Line Python SDK"

    ```python
    from friday_ai import Friday
    with Friday() as j:
        print(j.ask("Hello!"))
    ```

=== "API Server"

    ```bash
    friday serve --port 8000
    # Now use any OpenAI-compatible client
    ```

=== "Morning Digest"

    ```bash
    cp configs/friday_ai/examples/morning-digest-mac.toml ~/.friday_ai/config.toml
    friday connect gdrive       # one OAuth flow for Gmail, Calendar, Tasks
    CARTESIA_API_KEY="..." friday digest --fresh
    # Plays a spoken daily briefing with your email, calendar, health, and news
    ```

=== "Deep Research"

    ```bash
    friday init --preset deep-research --force
    friday memory index ~/Documents/papers/
    friday ask "Summarize all documents about transformer architectures"
    # Multi-hop search across your indexed docs with citations
    ```

=== "Code Assistant"

    ```bash
    friday init --preset code-assistant --force
    friday ask "Write a Python script that parses CSV files"
    # Orchestrator agent with code execution, file I/O, and shell access
    ```

=== "Scheduled Monitor"

    ```bash
    friday init --preset scheduled-monitor --force
    friday memory index ~/Documents/
    friday scheduler start
    friday scheduler create \
      --prompt "Check for new emails about Project X" \
      --schedule "0 9 * * 1-5" --agent operative
    # Persistent agent that runs on a cron schedule
    ```

For complete copy-paste patterns, see [Code Snippets](snippets.md).

## Starter Configs

Copy one of these to `~/.friday_ai/config.toml` to get a pre-configured setup:

| Config | For | What it does |
|--------|-----|-------------|
| [`chat-simple.toml`](https://github.com/open-jarvis/FridayAI/blob/main/configs/friday_ai/examples/chat-simple.toml) | Any machine | Lightweight chat, no tools -- simplest setup |
| [`code-assistant.toml`](https://github.com/open-jarvis/FridayAI/blob/main/configs/friday_ai/examples/code-assistant.toml) | Any machine | Orchestrator agent with code execution, file I/O, shell |
| [`deep-research.toml`](https://github.com/open-jarvis/FridayAI/blob/main/configs/friday_ai/examples/deep-research.toml) | Any machine | Multi-hop research across indexed documents with citations |
| [`scheduled-monitor.toml`](https://github.com/open-jarvis/FridayAI/blob/main/configs/friday_ai/examples/scheduled-monitor.toml) | Any machine | Persistent operative agent on a cron schedule |
| [`morning-digest-mac.toml`](https://github.com/open-jarvis/FridayAI/blob/main/configs/friday_ai/examples/morning-digest-mac.toml) | Mac (Apple Silicon) | Daily spoken briefing from email, calendar, health, news |
| [`morning-digest-linux.toml`](https://github.com/open-jarvis/FridayAI/blob/main/configs/friday_ai/examples/morning-digest-linux.toml) | Linux / GPU server | Same, with vLLM support |
| [`morning-digest-minimal.toml`](https://github.com/open-jarvis/FridayAI/blob/main/configs/friday_ai/examples/morning-digest-minimal.toml) | Any machine | Just Gmail + Calendar |

Or generate a config with digest included:

```bash
friday init --digest
```

This guide walks through the core workflows of FridayAI: the browser app, CLI, Python SDK, agents with tools, memory, benchmarks, and the API server.

!!! info "Prerequisites"
    Make sure you have [installed FridayAI](installation.md) and have at least one inference backend running (e.g., `ollama serve`).

## Browser App

The quickest way to experience FridayAI is the full chat UI running in your browser:

```bash
git clone https://github.com/open-jarvis/FridayAI.git
cd FridayAI
./scripts/quickstart.sh
```

This launches the backend API server and a React frontend at [http://localhost:5173](http://localhost:5173).
You get a ChatGPT-like interface with streaming responses, tool use, energy monitoring, and a telemetry dashboard — all running locally on your hardware.

Web search works with no configuration: queries go to the You.com keyless
free tier, which is rate limited per IP and needs no signup. To raise those
limits, or to use Tavily, Serply or Firecrawl instead, add `YOUDOTCOM_API_KEY`,
`TAVILY_API_KEY`, `SERPLY_API_KEY` or `FIRECRAWL_API_KEY` under
**Settings → Tools → Web Search** after the app starts, or export one before
starting quickstart:

```bash
export YOUDOTCOM_API_KEY="..."   # free key: https://you.com/platform
export SERPLY_API_KEY="..."      # free tier: https://serply.io
export FIRECRAWL_API_KEY="..."   # free tier: https://www.firecrawl.dev/app/api-keys?utm_source=friday_ai&utm_medium=integration
./scripts/quickstart.sh
```

Set `FRIDAY_AI_WEB_SEARCH_ENGINE` to pick an engine explicitly — `youcom`,
`tavily`, `serply`, `firecrawl`, or `duckduckgo`. The default, `auto`, uses
Tavily when `TAVILY_API_KEY` is set, then You.com, then Serply, then Firecrawl,
and settles on the You.com keyless tier when no key is set at all. DuckDuckGo
remains the fallback for every engine; dropping to it is logged at `WARNING`,
since its scraped results are unranked.

Serply proxies Google itself, so Google search operators reach the index
unchanged: `site:arxiv.org` restricts the corpus and `after:2026-01-01` bounds
results by date, neither of which an AI-search index can honour. Set
`SERPLY_PROXY_LOCATION` to a two-letter country code such as `DE` to ask for
that country's result set instead of the default region. Keys and request
options are documented at [serply.io](https://serply.io) and
[serply.io/docs](https://serply.io/docs).

Firecrawl also changes what happens when a query is a URL: instead of the local
HTML strip, the page comes back as markdown, including JavaScript-rendered
pages and PDFs. Set `FIRECRAWL_API_URL` to use a
[self-hosted Firecrawl](https://docs.firecrawl.dev/contributing/self-host)
instead of the hosted API; no key is needed if your instance runs without
auth. Page fetches then run on your instance, and search queries go on to the
search backend it is configured with. Keys:
[firecrawl.dev](https://www.firecrawl.dev/app/api-keys?utm_source=friday_ai&utm_medium=integration).

The script does not automatically source `.env` files. Run `source .env`
first if that is where you keep the key. Stop any existing FridayAI server
before restarting so it inherits the updated environment.

To stop all services, press ++ctrl+c++ in the terminal.

!!! tip "Environment variable"
    Set `FRIDAY_AI_MODEL` to change the default model: `FRIDAY_AI_MODEL=deepseek-r1:14b ./scripts/quickstart.sh`

## Initialize Configuration

Start by detecting your hardware and generating a configuration file:

```bash
friday init
```

This runs hardware auto-detection (GPU vendor, VRAM, CPU, RAM) and writes a config file to `~/.friday_ai/config.toml` with sensible defaults for your system. It also selects the recommended inference engine.

```
Detecting hardware...
  Platform : linux
  CPU      : AMD EPYC 7763 (128 cores)
  RAM      : 512.0 GB
  GPU      : NVIDIA A100 (80.0 GB VRAM, x8)

Config written successfully.
```

To overwrite an existing config:

```bash
friday init --force
```

See [Configuration](configuration.md) for the full config reference.

## Your First Question

### Via CLI

The simplest way to interact with FridayAI is the `ask` command:

```bash
friday ask "What is the capital of France?"
```

FridayAI will auto-detect a running engine, select a model using the configured router policy, and return the response.

#### CLI Options

| Option | Description | Example |
|--------|-------------|---------|
| `-m`, `--model` | Override model selection | `friday ask -m qwen3:8b "Hello"` |
| `-e`, `--engine` | Force a specific engine | `friday ask -e ollama "Hello"` |
| `-t`, `--temperature` | Sampling temperature (default: 0.7) | `friday ask -t 0.2 "Hello"` |
| `--max-tokens` | Max tokens to generate (default: 1024) | `friday ask --max-tokens 2048 "Hello"` |
| `--json` | Output raw JSON result | `friday ask --json "Hello"` |
| `--no-stream` | Disable streaming | `friday ask --no-stream "Hello"` |
| `--no-context` | Disable memory context injection | `friday ask --no-context "Hello"` |
| `-a`, `--agent` | Use an agent | `friday ask -a orchestrator "Hello"` |
| `--tools` | Comma-separated tools | `friday ask --tools calculator,think "2+2"` |
| `--router` | Router policy for model selection | `friday ask --router heuristic "Hello"` |

### Via Python SDK

The `Friday` class provides a high-level Python interface:

```python
from friday_ai import Friday

j = Friday()
response = j.ask("What is the capital of France?")
print(response)
j.close()
```

For detailed results including token usage and model info:

```python
result = j.ask_full("What is the capital of France?")
print(result["content"])  # The response text
print(result["model"])    # Model that handled the query
print(result["engine"])   # Engine that ran inference
print(result["usage"])    # Token usage statistics
```

#### SDK Constructor Options

```python
# Use default config (auto-detected hardware, ~/.friday_ai/config.toml)
j = Friday()

# Override the model
j = Friday(model="qwen3:8b")

# Override the engine
j = Friday(engine_key="ollama")

# Use a custom config file
j = Friday(config_path="/path/to/config.toml")
```

!!! warning "Always call `close()`"
    The `Friday` instance holds references to telemetry stores and memory backends. Call `j.close()` when you are done to release resources.

## Using Agents with Tools

Agents add multi-turn reasoning and tool-calling capabilities. The `orchestrator` agent runs a tool-calling loop, invoking tools as needed to answer the query.

### Available Agents

| Agent | Description |
|-------|-------------|
| `simple` | Single-turn, no tools. Sends the query directly to the model. |
| `orchestrator` | Multi-turn tool-calling loop. Invokes tools iteratively until it has an answer. |
| `custom` | Template for user-defined agent logic. |
| `operative` | Task-oriented agent with structured planning and execution. |

### Available Built-in Tools

| Tool | Description |
|------|-------------|
| `calculator` | Safe mathematical expression evaluation (ast-based). |
| `think` | Reasoning scratchpad for chain-of-thought. |
| `retrieval` | Search the memory store for relevant context. |
| `llm` | Make sub-queries to another model. |
| `file_read` | Read files with path validation. |
| `web_search` | Web search via You.com (keyless by default), Tavily, Serply, or Firecrawl, with a DuckDuckGo fallback. |

### CLI Example

```bash
friday ask --agent orchestrator --tools calculator,think "What is 137 * 42?"
```

### SDK Example

```python
from friday_ai import Friday

j = Friday()
result = j.ask_full(
    "What is the square root of 144?",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(result["content"])
print(result["tool_results"])  # List of tool invocations and results
print(result["turns"])         # Number of agent turns
j.close()
```

## Memory: Indexing and Search

The memory system lets you index documents and inject relevant context into queries automatically.

### Index Documents

Index a file or directory. FridayAI chunks the content and stores it in the configured memory backend (SQLite/FTS5 by default).

=== "CLI"

    ```bash
    # Index a directory
    friday memory index ./docs/

    # Index a single file with custom chunk size
    friday memory index ./paper.txt --chunk-size 256 --chunk-overlap 32
    ```

=== "Python SDK"

    ```python
    from friday_ai import Friday

    j = Friday()
    result = j.memory.index("./docs/", chunk_size=512, chunk_overlap=64)
    print(f"Indexed {result['chunks']} chunks")
    j.close()
    ```

### Search Memory

Query the memory store to find relevant chunks:

=== "CLI"

    ```bash
    friday memory search "configuration options"
    friday memory search -k 10 "how to deploy"
    ```

=== "Python SDK"

    ```python
    results = j.memory.search("configuration options", top_k=5)
    for r in results:
        print(f"[{r['score']:.4f}] {r['source']}: {r['content'][:100]}")
    ```

### Check Memory Statistics

=== "CLI"

    ```bash
    friday memory stats
    ```

=== "Python SDK"

    ```python
    stats = j.memory.stats()
    print(f"Backend: {stats['backend']}, Documents: {stats.get('count', 'N/A')}")
    ```

### Automatic Context Injection

When you have indexed documents, FridayAI automatically injects relevant context into your queries. The memory system searches for chunks matching your query and prepends them as system context before sending to the model.

To disable this behavior:

=== "CLI"

    ```bash
    friday ask --no-context "Hello"
    ```

=== "Python SDK"

    ```python
    response = j.ask("Hello", context=False)
    ```

Context injection is controlled by `agent.context_from_memory` in `config.toml`. The retrieval parameters (`context_top_k`, `context_min_score`, `context_max_tokens`) live under `[tools.storage]`. See [Configuration](configuration.md) for details.

## Model Management

### List Available Models

See all models available on running engines:

```bash
friday model list
```

This produces a table showing each model, its engine, parameter count, context length, and VRAM requirements.

### Get Model Details

```bash
friday model info qwen3:8b
```

### Pull a Model (Ollama)

```bash
friday model pull qwen3:8b
```

### SDK Model Listing

```python
from friday_ai import Friday

j = Friday()
models = j.list_models()
engines = j.list_engines()
print(f"Models: {models}")
print(f"Engines: {engines}")
j.close()
```

## Running Benchmarks

The benchmarking framework measures inference latency and throughput against your engine.

=== "All benchmarks"

    ```bash
    friday bench run
    ```

=== "Specific benchmark"

    ```bash
    friday bench run -b latency
    friday bench run -b throughput
    ```

=== "Custom options"

    ```bash
    # 20 samples, JSON output
    friday bench run -n 20 --json

    # Specific model and engine, write to file
    friday bench run -m qwen3:8b -e ollama -o results.jsonl
    ```

Example output:

```
Running 2 benchmark(s) on ollama/qwen3:8b (10 samples)...

latency (10 samples, 0 errors)
  mean_ms: 245.3200
  p50_ms: 238.1000
  p95_ms: 312.4500
  min_ms: 201.2000
  max_ms: 345.6000

throughput (10 samples, 0 errors)
  tokens_per_second: 42.1500
  total_tokens: 4215
  total_seconds: 100.0000
```

## Starting the API Server

FridayAI provides an OpenAI-compatible API server for integration with existing tools and frontends.

!!! note "Requires the `server` extra"
    ```bash
    uv sync --extra server
    ```

### Start the Server

```bash
friday serve --port 8000
```

With custom options:

```bash
friday serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b --agent orchestrator
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | `POST` | Chat completions (streaming and non-streaming) |
| `/v1/models` | `GET` | List available models |
| `/health` | `GET` | Health check |

### Use with Any OpenAI-Compatible Client

Once the server is running, point any OpenAI-compatible client at it:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")
response = client.chat.completions.create(
    model="qwen3:8b",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

Or with `curl`:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:8b",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Telemetry

FridayAI records telemetry for every inference call (timing, tokens, cost). View aggregated statistics:

```bash
friday telemetry stats
```

Export telemetry data:

```bash
friday telemetry export --format json
friday telemetry export --format csv -o telemetry.csv
```

Clear all telemetry records:

```bash
friday telemetry clear --yes
```

## Complete Working Example

Here is a complete end-to-end session combining multiple features:

```python
from friday_ai import Friday

# Initialize with defaults (auto-detect hardware and engine)
j = Friday()

# 1. Index some documentation
index_result = j.memory.index("./docs/", chunk_size=512)
print(f"Indexed {index_result['chunks']} chunks from {index_result['path']}")

# 2. Search memory
results = j.memory.search("how to configure engines")
for r in results:
    print(f"  [{r['score']:.3f}] {r['source']}")

# 3. Ask a question (memory context is injected automatically)
answer = j.ask("How do I configure the Ollama engine host?")
print(f"\nAnswer: {answer}")

# 4. Use an agent with tools
calc_result = j.ask_full(
    "Calculate the compound interest on $10,000 at 5% for 10 years",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(f"\nCalculation: {calc_result['content']}")
print(f"Tools used: {[t['tool_name'] for t in calc_result['tool_results']]}")
print(f"Agent turns: {calc_result['turns']}")

# 5. List available models
models = j.list_models()
print(f"\nAvailable models: {models}")

# 6. Clean up
j.close()
```

## Next Steps

- [Configuration](configuration.md) — Fine-tune engine hosts, model routing, memory settings, and more
- [CLI Reference](../user-guide/cli.md) — Full reference for all CLI commands and options
- [Python SDK](../user-guide/python-sdk.md) — Detailed SDK documentation
- [Architecture Overview](../architecture/overview.md) — Understand the five-primitive design
