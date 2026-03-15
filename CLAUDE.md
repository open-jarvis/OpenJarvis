# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenJarvis is a local-first personal AI framework built on five core primitives (Intelligence, Engine, Agents, Memory, Learning), developed at Stanford's Hazy Research and Scaling Intelligence Lab. Python 3.10+ with Rust extensions via PyO3/maturin.

## Common Commands

### Setup
```bash
uv sync                    # Core dependencies
uv sync --extra dev        # + testing & linting tools
uv sync --extra server     # + FastAPI server
```

### Linting (matches CI)
```bash
uv run ruff check src/ tests/
```

### Testing
```bash
uv run pytest tests/ -v --tb=short              # Full suite (matches CI)
uv run pytest tests/core/test_registry.py -v     # Single file
uv run pytest tests/agents/ -v                   # Single directory
uv run pytest tests/ --cov=openjarvis --cov-report=html  # With coverage
```

### Building Rust Extension
```bash
uv run maturin develop --manifest-path rust/crates/openjarvis-python/Cargo.toml
```

### Rust (run from `rust/` directory)
```bash
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

### Running
```bash
uv run jarvis ask "question"   # Single query
uv run jarvis chat             # Interactive mode
uv run jarvis serve            # API server
uv run jarvis doctor           # Diagnose setup
```

## Test Markers

Tests use pytest markers to gate on hardware/service availability:
- `@pytest.mark.live` — requires running inference engine
- `@pytest.mark.cloud` — requires cloud API keys
- `@pytest.mark.nvidia` / `amd` / `apple` — requires specific GPU
- `@pytest.mark.slow` — long-running

The `conftest.py` autouse fixture `_clean_registries()` clears all registries and resets the EventBus between tests. Use the `mock_engine` fixture factory to create mock `InferenceEngine` instances.

## Architecture

### Five Primitives (connected via EventBus)

1. **Intelligence** (`src/openjarvis/intelligence/`) — Model catalog (60+ models), metadata (params, context length, VRAM), auto-discovery from running engines.

2. **Engine** (`src/openjarvis/engine/`) — Inference runtime abstraction. Backends: Ollama, vLLM, SGLang, llama.cpp, Cloud (OpenAI/Anthropic/Google). Uniform interface: `generate()`, `stream()`, `list_models()`, `health()`.

3. **Agents** (`src/openjarvis/agents/`) — 9 agent types. Hierarchy: `BaseAgent` (ABC) → `ToolUsingAgent` → concrete agents. Agent registry via decorators.

4. **Memory** (`src/openjarvis/tools/storage/`) — 5 backends: SQLite/FTS5 (default), FAISS, ColBERTv2, BM25, Hybrid (RRF). Document chunking + embedding + retrieval with source attribution.

5. **Learning** (`src/openjarvis/learning/`) — Trace-driven feedback loop. Router policies: HeuristicRouter (default), TraceDrivenPolicy, SFTPolicy, GRPORouterPolicy. Query analysis → model selection with reward functions.

### Key Patterns

- **Registry Pattern** (`core/registry.py`): Decorator-based runtime discovery. Typed registries: Model, Engine, Memory, Agent, Tool, RouterPolicy, Benchmark, Channel, Speech. Tests must clear registries (handled by autouse fixture).

- **EventBus** (`core/events.py`): Thread-safe pub/sub. Event types cover inference, tool calls, memory ops, agent turns, telemetry, traces, channels, security.

- **System Composition** (`src/openjarvis/system.py`): `JarvisSystem` dataclass is the single source of truth wiring all primitives together. `ask()` orchestrates context injection → agent selection → tool execution.

- **SDK** (`src/openjarvis/sdk.py`): `Jarvis` class is the high-level user-facing API. `SystemBuilder` for construction.

### Other Major Components

- **CLI** (`src/openjarvis/cli/`) — Click-based, entry point `jarvis` → `openjarvis.cli:main`
- **API Server** (`src/openjarvis/server/`) — FastAPI, OpenAI-compatible endpoints (`/v1/chat/completions`, `/v1/models`)
- **Channels** (`src/openjarvis/channels/`) — 14 messaging integrations (Telegram, Discord, Slack, etc.), `BaseChannel` ABC
- **Tools** (`src/openjarvis/tools/`) — 20+ tools (calculator, file I/O, code interpreter, retrieval, shell, MCP adapter)
- **Traces** (`src/openjarvis/traces/`) — SQLite-backed trace storage, collection, and analysis
- **Telemetry** (`src/openjarvis/telemetry/`) — Per-model/engine stats, energy profiling
- **Security** (`src/openjarvis/security/`) — Secret scanning, PII detection, guardrails, audit logging
- **Scheduler** (`src/openjarvis/scheduler/`) — Background task scheduling (cron/interval/one-shot), SQLite persistence
- **Rust extension** (`rust/`) — 17-crate workspace, PyO3 bindings in `rust/crates/openjarvis-python/`
- **Frontend** (`frontend/`) — React 19 + Vite + TypeScript + Tailwind
- **Desktop** (`desktop/`) — Tauri 2.0 native app with auto-updates

## Ruff Configuration

Target: Python 3.10. Rules: E, F, I, W. Long lines allowed in `src/openjarvis/evals/datasets/*.py` and `src/openjarvis/evals/scorers/*.py` (E501 ignored).

## Important Rules

- **Never commit spec or plan files** (`docs/superpowers/`, `docs/plans/`, `.superpowers/`). These are local-only artifacts used during development. They are in `.gitignore` — do not `git add -f` them. Keep them on disk for reference but never include them in commits or PRs.
