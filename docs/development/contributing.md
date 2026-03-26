# Contributing Guide

This guide covers how to set up a development environment, run tests, and
contribute code to OpenJarvis.

---

## Development Setup

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | Required |
| [uv](https://docs.astral.sh/uv/) | Latest | Package manager |
| Node.js | 22+ | Only needed for ClaudeCodeAgent and WhatsApp channel |

### Clone and Install

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync --extra dev
```

This installs the package in editable mode along with all development
dependencies (pytest, ruff, respx, pytest-asyncio, pytest-cov).

!!! tip "Optional extras"
    Install additional extras for specific backends you want to work on:

    ```bash
    # Memory backends
    uv sync --extra dev --extra memory-faiss --extra memory-colbert --extra memory-bm25

    # Cloud inference
    uv sync --extra dev --extra inference-cloud --extra inference-google

    # API server
    uv sync --extra dev --extra server

    # Documentation
    uv sync --extra dev --extra docs
    ```

### Verify Installation

```bash
uv run jarvis --version   # Should print 0.1.0
uv run jarvis --help      # Show all subcommands
```

---

## Running Tests

OpenJarvis uses [pytest](https://docs.pytest.org/) with approximately 1,000+
tests organized by module.

### Full Test Suite

```bash
uv run pytest tests/ -v
```

### Run a Specific Test File

```bash
uv run pytest tests/core/test_registry.py -v
uv run pytest tests/engine/test_ollama.py -v
uv run pytest tests/memory/test_sqlite.py -v
```

### Run a Specific Test

```bash
uv run pytest tests/core/test_registry.py::test_register_and_get -v
```

### Run Tests by Module

```bash
uv run pytest tests/agents/ -v       # All agent tests
uv run pytest tests/tools/ -v        # All tool tests
uv run pytest tests/learning/ -v     # All learning tests
```

### Test Coverage

```bash
uv run pytest tests/ --cov=openjarvis --cov-report=html
```

### Test Markers

Tests that require specific hardware or running services are gated behind
pytest markers. By default, these tests are collected but will skip
gracefully if the requirement is not met.

| Marker | Description | Example |
|---|---|---|
| `live` | Requires a running inference engine (Ollama, vLLM, etc.) | `@pytest.mark.live` |
| `cloud` | Requires cloud API keys (`OPENAI_API_KEY`, etc.) | `@pytest.mark.cloud` |
| `nvidia` | Requires an NVIDIA GPU | `@pytest.mark.nvidia` |
| `amd` | Requires an AMD GPU with ROCm | `@pytest.mark.amd` |
| `apple` | Requires Apple Silicon | `@pytest.mark.apple` |
| `slow` | Long-running test | `@pytest.mark.slow` |

Run only tests matching a specific marker:

```bash
uv run pytest tests/ -m live -v          # Only live engine tests
uv run pytest tests/ -m "not slow" -v    # Skip slow tests
uv run pytest tests/ -m "not cloud" -v   # Skip cloud tests
```

!!! info "Registry isolation in tests"
    The test `conftest.py` includes an `autouse` fixture that clears all
    registries and resets the event bus before every test. This ensures
    complete isolation between tests. Modules that need their registrations
    to survive clearing use the `ensure_registered()` pattern described
    below.

---

## Linting

OpenJarvis uses [Ruff](https://docs.astral.sh/ruff/) for linting, configured
in `pyproject.toml`:

```bash
uv run ruff check src/ tests/
```

The Ruff configuration targets Python 3.10 and enables the following rule sets:

- **E** -- pycodestyle errors
- **F** -- Pyflakes
- **I** -- isort (import ordering)
- **W** -- pycodestyle warnings

Fix auto-fixable issues:

```bash
uv run ruff check src/ tests/ --fix
```

---

## Building Documentation

The documentation site uses [MkDocs Material](https://squidfunnel.com/mkdocs-material/).

```bash
# Install docs dependencies
uv sync --extra docs

# Serve locally with hot reload
uv run mkdocs serve --dev-addr 127.0.0.1:8001

# Build static site
uv run mkdocs build
```

The site configuration lives in `mkdocs.yml`. API reference pages use
[mkdocstrings](https://mkdocstrings.github.io/) to auto-generate from
docstrings with the NumPy docstring style.

---

## Project Structure

The source code is organized under `src/openjarvis/`:

```
src/openjarvis/
    __init__.py                 # Package root, __version__
    sdk.py                      # Jarvis class — high-level Python SDK

    core/                       # Shared infrastructure
        config.py               # JarvisConfig, hardware detection, TOML loader
        events.py               # EventBus pub/sub system
        registry.py             # RegistryBase[T] and all typed registries
        types.py                # Message, ModelSpec, ToolResult, Trace, etc.

    intelligence/               # Model management and query routing
        model_catalog.py        # BUILTIN_MODELS, register/merge helpers
        router.py               # HeuristicRouter, build_routing_context

    engine/                     # Inference engine backends
        _stubs.py               # InferenceEngine ABC
        _base.py                # EngineConnectionError, messages_to_dicts
        _discovery.py           # discover_engines, discover_models, get_engine
        _openai_compat.py       # OpenAI-compatible wrapper
        ollama.py               # OllamaEngine
        openai_compat_engines.py   # Data-driven registration (vLLM, SGLang, llama.cpp, MLX, LM Studio)
        cloud.py                # CloudEngine (OpenAI/Anthropic/Google)

    agents/                     # Agent implementations
        _stubs.py               # BaseAgent ABC, ToolUsingAgent, AgentContext, AgentResult
        simple.py               # SimpleAgent — single-turn, no tools
        orchestrator.py         # OrchestratorAgent — multi-turn tool calling (function_calling + structured)
        native_react.py         # NativeReActAgent — Thought-Action-Observation loop
        native_openhands.py     # NativeOpenHandsAgent — CodeAct-style code execution
        rlm.py                  # RLMAgent — recursive LM with persistent REPL
        openhands.py            # OpenHandsAgent — wraps real openhands-sdk
        react.py                # Backward-compat shim (re-exports NativeReActAgent)
        claude_code.py          # ClaudeCodeAgent — Claude Agent SDK via Node.js subprocess
        claude_code_runner/     # Bundled Node.js runner for the Claude Agent SDK

    memory/                     # Memory / retrieval backends
        _stubs.py               # MemoryBackend ABC, RetrievalResult
        sqlite.py               # SQLiteMemory — FTS5 default backend
        faiss_backend.py        # FAISS vector backend
        colbert_backend.py      # ColBERTv2 backend
        bm25.py                 # BM25 backend
        hybrid.py               # Hybrid (RRF fusion) backend
        chunking.py             # ChunkConfig, chunk_text
        context.py              # ContextConfig, inject_context
        ingest.py               # ingest_path, read_document

    tools/                      # Tool system
        _stubs.py               # BaseTool ABC, ToolSpec, ToolExecutor
        calculator.py           # CalculatorTool — safe AST math
        think.py                # ThinkTool — reasoning scratchpad
        retrieval.py            # RetrievalTool — memory search
        llm_tool.py             # LLMTool — sub-model calls
        file_read.py            # FileReadTool — safe file reading
        web_search.py           # WebSearchTool
        code_interpreter.py     # CodeInterpreterTool

    learning/                   # Router policies and reward functions
        _stubs.py               # RouterPolicy ABC, RewardFunction ABC
        heuristic_policy.py     # Wire HeuristicRouter to registry
        trace_policy.py         # TraceDrivenPolicy — learns from traces
        grpo_policy.py          # GRPORouterPolicy — RL training stub
        heuristic_reward.py     # HeuristicRewardFunction

    traces/                     # Full interaction recording
        store.py                # TraceStore — SQLite persistence
        collector.py            # TraceCollector — wraps agents
        analyzer.py             # TraceAnalyzer — aggregated queries

    telemetry/                  # Inference telemetry
        store.py                # TelemetryStore — SQLite persistence
        aggregator.py           # TelemetryAggregator — per-model/engine stats
        wrapper.py              # instrumented_generate() wrapper

    bench/                      # Benchmarking framework
        _stubs.py               # BaseBenchmark ABC, BenchmarkSuite
        latency.py              # LatencyBenchmark
        throughput.py           # ThroughputBenchmark

    server/                     # OpenAI-compatible API server
        app.py                  # FastAPI application factory
        routes.py               # /v1/chat/completions, /v1/models, /health

    mcp/                        # MCP (Model Context Protocol) layer

    cli/                        # Click CLI commands
        __init__.py             # main group
        ask.py                  # jarvis ask
        init_cmd.py             # jarvis init
        model.py                # jarvis model list/info
        memory_cmd.py           # jarvis memory index/search/stats
        telemetry_cmd.py        # jarvis telemetry stats/export/clear
        bench_cmd.py            # jarvis bench run
        serve.py                # jarvis serve
```

---

## Code Conventions

### File Naming

| Pattern | Purpose | Examples |
|---|---|---|
| `_stubs.py` | ABC definitions and dataclasses | `engine/_stubs.py`, `agents/_stubs.py`, `tools/_stubs.py` |
| `_discovery.py` | Auto-detection and probing logic | `engine/_discovery.py` |
| `_base.py` | Shared utilities and re-exports | `engine/_base.py` |
| `*_cmd.py` | CLI command modules | `init_cmd.py`, `memory_cmd.py`, `bench_cmd.py` |

### Registry Pattern

All extensible components use the decorator-based registry pattern. New
implementations are added by decorating a class -- no factory modifications
needed:

```python
from openjarvis.core.registry import EngineRegistry

@EngineRegistry.register("my_engine")
class MyEngine(InferenceEngine):
    ...
```

Available registries:

| Registry | Stores | Key examples |
|---|---|---|
| `ModelRegistry` | `ModelSpec` objects | `"qwen3:8b"`, `"llama3.1:70b"` |
| `EngineRegistry` | `InferenceEngine` classes | `"ollama"`, `"vllm"`, `"llamacpp"` |
| `MemoryRegistry` | `MemoryBackend` classes | `"sqlite"`, `"faiss"`, `"bm25"` |
| `AgentRegistry` | `BaseAgent` classes | `"simple"`, `"orchestrator"` |
| `ToolRegistry` | `BaseTool` classes | `"calculator"`, `"think"`, `"retrieval"` |
| `RouterPolicyRegistry` | `RouterPolicy` classes | `"heuristic"`, `"learned"` |
| `BenchmarkRegistry` | `BaseBenchmark` classes | `"latency"`, `"throughput"` |

### Optional Dependencies

Backends that depend on optional packages use the `try/except ImportError`
pattern to fail gracefully when deps are not installed:

```python
# In __init__.py — import to trigger registration
try:
    import openjarvis.memory.faiss_backend  # noqa: F401
except ImportError:
    pass
```

This ensures the package always loads, even if `faiss-cpu` or other optional
dependencies are not installed.

### The `ensure_registered()` Pattern

Benchmark and learning modules use lazy registration so that their entries
survive registry clearing in tests:

```python
def ensure_registered() -> None:
    """Register the latency benchmark if not already present."""
    if not BenchmarkRegistry.contains("latency"):
        BenchmarkRegistry.register_value("latency", LatencyBenchmark)
```

This pattern checks `contains()` before registering, making it safe to call
multiple times without raising a duplicate-key error.

### Dataclass Conventions

- Use `slots=True` on all dataclasses for memory efficiency:

```python
@dataclass(slots=True)
class BenchmarkResult:
    benchmark_name: str
    model: str
    ...
```

### Type Hints

- All function signatures must have type annotations
- Use `from __future__ import annotations` at the top of every module
- Use `Optional[X]` for nullable types
- Use `Sequence` for read-only collections, `List` for mutable ones

### Import Style

- Absolute imports only (`from openjarvis.core.registry import ...`)
- Sort imports with `ruff` (isort rules enabled)
- Place `from __future__ import annotations` as the first import

---

## PR Guidelines

### Before Submitting

1. **Run the full test suite** and verify no regressions:
    ```bash
    uv run pytest tests/ -v
    ```

2. **Run the linter** and fix all issues:
    ```bash
    uv run ruff check src/ tests/
    ```

3. **Add tests** for new functionality. Place them in the corresponding
   `tests/` subdirectory (e.g., new engine tests go in `tests/engine/`).

4. **Follow the registry pattern** for any new extensible component.

### Commit Messages

- Use the imperative mood (e.g., "Add FAISS memory backend")
- Keep the first line under 72 characters
- Reference relevant issues or PRs

### What Makes a Good PR

- **Focused**: One feature, fix, or refactor per PR
- **Tested**: Include unit tests that cover the new code paths
- **Documented**: Update docstrings and documentation pages if adding
  public API
- **Backwards compatible**: Avoid breaking existing interfaces without
  discussion

### Adding a New Primitive Component

When adding a new engine, memory backend, agent, tool, benchmark, or router
policy:

1. Implement the corresponding ABC
2. Register with the appropriate `@XRegistry.register("key")` decorator
3. Add an import in the module's `__init__.py` (with `try/except ImportError`
   if the component has optional deps)
4. Add tests in the matching `tests/` subdirectory
5. Add an entry in `pyproject.toml` under `[project.optional-dependencies]`
   if the component requires new packages

See the [registry pattern](#registry-pattern) section above for complete examples.
