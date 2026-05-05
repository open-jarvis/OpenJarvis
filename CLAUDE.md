# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

OpenJarvis is a local-first personal AI agent framework. The Python package lives in `src/openjarvis/`, with a Rust workspace under `rust/` (built via PyO3/maturin) and a bundled Node.js runner for the Claude Agent SDK. The CLI entry point is `jarvis` → `openjarvis.cli:main`.

## Commands

Use `uv` for everything Python; the package is installed editable into the project venv on `uv sync`.

### Setup

```bash
uv sync --extra dev                                                 # core + dev tools (pytest, ruff, respx, pytest-cov)
uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml  # required for memory + security features
uv run pre-commit install                                           # ruff lint + format on commit
```

For optional backends, layer extras: `uv sync --extra dev --extra memory-faiss --extra inference-cloud --extra server` (full list in `pyproject.toml`).

> **Python 3.14+:** prefix the maturin command with `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`.

### Test

```bash
uv run pytest tests/ -v                              # full suite
uv run pytest tests/core/test_registry.py -v         # one file
uv run pytest tests/core/test_registry.py::test_register_and_get -v   # one test
uv run pytest tests/ -m "not live and not cloud"     # what CI runs
uv run pytest tests/ --cov=openjarvis --cov-report=term-missing
```

Markers gate hardware/network-dependent tests: `live` (running engine), `cloud` (API keys), `nvidia`, `amd`, `apple`, `macos15`, `slow`, `live_channel`. CI runs `not live and not cloud` with `--cov-fail-under=60`.

### Lint

```bash
uv run ruff check src/ tests/          # CI gate
uv run ruff check src/ tests/ --fix
uv run ruff format --check src/ tests/
```

Ruff targets py310 with rule sets `E`, `F`, `I`, `W` (pycodestyle, pyflakes, isort, warnings).

### Rust

```bash
cd rust && cargo clippy --workspace --all-targets -- -D warnings   # CI gate (warnings = errors)
cd rust && cargo test --workspace
```

The Rust workspace at `rust/Cargo.toml` mirrors Python module names (`openjarvis-core`, `openjarvis-engine`, `openjarvis-agents`, etc.). `openjarvis-python` is the PyO3 bridge crate that gets built into the Python package via maturin; the bridge lives at `src/openjarvis/_rust_bridge.py`.

## Architecture

### Registry pattern (load-bearing)

Every extensible primitive — engines, agents, tools, memory backends, channels, router policies, benchmarks, connectors, skills, speech/TTS, compression — is registered through a typed registry in `src/openjarvis/core/registry.py` with the decorator form:

```python
@EngineRegistry.register("my_engine")
class MyEngine(InferenceEngine): ...
```

Registry lookups are how the CLI, SDK, and config files resolve string keys (`"ollama"`, `"orchestrator"`, `"sqlite"`) to implementations. **Adding a new primitive without a registry decorator means it is invisible to the rest of the system.**

### Test isolation: registries get cleared every test

`tests/conftest.py` has an `autouse` fixture that calls `.clear()` on every registry and resets the event bus before each test. Modules whose registrations must survive clearing — typically benchmarks and learning policies — expose an idempotent `ensure_registered()` helper guarded by `XRegistry.contains(...)`. Tests call `ensure_registered()` themselves.

Practical implication: if a test fails because some component "isn't registered," the fix is usually to call the module's `ensure_registered()` or to import the module inside the test/fixture, not to touch `conftest.py`.

### Optional dependencies fail soft

Backends with optional packages live behind `try / except ImportError` at import time, typically in the parent `__init__.py`:

```python
try:
    import openjarvis.memory.faiss_backend  # noqa: F401  (registers on import)
except ImportError:
    pass
```

The package always loads even when extras like `faiss-cpu`, `vllm`, `colbert-ai` are missing. Don't wrap registry decorators themselves — wrap the import that triggers them.

### Primitives map (where to look)

- `core/` — `config.py` (JarvisConfig + hardware detection), `events.py` (EventBus), `registry.py`, `types.py` (`Message`, `ModelSpec`, `ToolResult`, `Trace`).
- `engine/` — inference backends. `_stubs.py` defines `InferenceEngine` ABC; `_discovery.py` auto-probes which engines are running; `openai_compat_engines.py` registers vLLM/SGLang/llama.cpp/MLX/LM Studio data-driven via the OpenAI-compatible wrapper.
- `agents/` — `_stubs.py` has `BaseAgent`, `ToolUsingAgent`, `AgentContext`, `AgentResult`. `claude_code.py` shells out to Node via `claude_code_runner/` (bundled into the wheel by hatch — see `[tool.hatch.build.targets.wheel.force-include]` in `pyproject.toml`).
- `intelligence/` — model catalog and routing (`HeuristicRouter`).
- `memory/` — retrieval backends, all behind `MemoryBackend` ABC: SQLite-FTS5 (default), FAISS, ColBERTv2, BM25, hybrid (RRF fusion), with shared chunking/context/ingest helpers.
- `tools/` — `BaseTool` ABC + `ToolExecutor`. Built-in: calculator, think, retrieval, llm_tool, file_read, web_search, code_interpreter.
- `learning/` — `RouterPolicy` and `RewardFunction` ABCs. Trace-driven and GRPO policies live here.
- `traces/`, `telemetry/` — SQLite-backed recording + aggregation. `telemetry/wrapper.py` instruments `generate()` calls.
- `server/` — FastAPI OpenAI-compatible server (`/v1/chat/completions`, `/v1/models`, `/health`), gated by the `server` extra.
- `cli/` — Click commands; one file per subcommand named `*_cmd.py`. `_tool_names.py` keeps tool key constants in one place.
- `channels/` — chat platform integrations; the `whatsapp_baileys_bridge/` is a Node.js subprocess (also force-included in the wheel).

The mining subsystem also includes the cpu-pearl provider (Spec B v1) for
non-CUDA hosts including Apple Silicon. It runs Pearl's pure-Rust mine()
function via py-pearl-mining plus Pearl's pearl-gateway as a sibling
subprocess; decoupled from inference (the user's MLX/Ollama/llamacpp engine
is untouched). Future v2 (Apple-GPU acceleration via PyTorch MPS) and v3
(native Metal kernel) are tracked in
docs/design/2026-05-05-apple-silicon-pearl-mining-design.md.

### File-naming conventions

- `_stubs.py` — ABC + dataclasses for that subsystem (always import from here for type hints)
- `_discovery.py` — auto-detection and probing logic
- `_base.py` — shared utilities and re-exports
- `*_cmd.py` — Click CLI command modules (one per subcommand under `cli/`)

### Dataclass + type-hint conventions

- `@dataclass(slots=True)` everywhere — memory matters because traces/telemetry are high-volume.
- `from __future__ import annotations` is the first import in every module; absolute imports only.
- Full type annotations on signatures; `Sequence` for read-only, `List` for mutable.

### Adding a new primitive (checklist)

1. Implement the ABC from the relevant `_stubs.py`.
2. Decorate with `@XRegistry.register("key")` (or pair with `ensure_registered()` if it must survive test clearing).
3. Add a soft-import line in the module's `__init__.py` (`try / except ImportError`) so registration fires when the package loads.
4. Add tests under `tests/<area>/`.
5. If new packages are needed, add an entry under `[project.optional-dependencies]` in `pyproject.toml` rather than to the core `dependencies` list.

## Review expectations

`REVIEW.md` is the explicit PR-review rubric used by automated reviewers. The high-leverage things to check on changes touching this repo:

- **Registry compliance** — new components register through the canonical registry, not ad-hoc factories.
- **PyO3 boundaries** — type conversions, error propagation, GIL handling in `rust/crates/openjarvis-python/` and consumers via `_rust_bridge.py`.
- **Async correctness** — no missing `await`, no blocking calls inside async paths.
- **Event bus integration** — lifecycle events flow through `core.events.EventBus`, not bespoke callbacks.
- **Local-first data isolation** — secrets stay out of code, validation lives at boundaries (user input, external APIs).

Don't comment on formatting (Ruff handles it) or files outside the diff.
