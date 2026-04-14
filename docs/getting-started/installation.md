---
title: Installation
description: Get OpenJarvis running — browser app, desktop app, CLI, or Python SDK
search:
  boost: 3
---

# Installation

OpenJarvis runs entirely on your hardware. Choose the interface that fits your workflow.

---

## Browser App

Run the full chat UI in your browser. Everything stays local — the backend runs on
your machine and the frontend connects via `localhost`.

### One-command setup

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
./scripts/quickstart.sh
```

The script handles everything:

1. Checks for Python 3.10+ and Node.js 18+
2. Installs Ollama if not present and pulls a starter model
3. Installs Python and frontend dependencies
4. Starts the backend API server and frontend dev server
5. Opens `http://localhost:5173` in your browser

### Manual setup

If you prefer to run each step yourself:

=== "Step 1: Clone and install"

    ```bash
    git clone https://github.com/open-jarvis/OpenJarvis.git
    cd OpenJarvis
    uv sync --extra server
    uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml
    cd frontend && npm install && cd ..
    ```

    !!! note "Prerequisites"
        Requires [Rust](https://rustup.rs/) (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`).
        On Python 3.14+, set `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` before the `maturin` command.

=== "Step 2: Start Ollama"

    ```bash
    # Install from https://ollama.com if not already installed
    ollama serve &
    ollama pull qwen3:0.6b
    ```

=== "Step 3: Start backend"

    ```bash
    uv run jarvis serve --port 8000
    ```

=== "Step 4: Start frontend"

    ```bash
    cd frontend
    npm run dev
    ```

Then open [http://localhost:5173](http://localhost:5173).

---

## Desktop App

The desktop app is a native window for the OpenJarvis chat UI. All inference and backend
processing happens on your local machine — the app connects to the backend you start locally.

### Setup

**Step 1.** Start the backend (same as Browser App):

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
./scripts/quickstart.sh
```

**Step 2.** Download and open the desktop app:

| Platform | Download |
|----------|----------|
| macOS (Apple Silicon) | [:material-download: **OpenJarvis.dmg**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_0.1.0_aarch64.dmg) |
| Windows (64-bit) | [:material-download: **OpenJarvis-setup.exe**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_0.1.0_x64-setup.exe) |
| Linux (DEB) | [:material-download: **OpenJarvis.deb**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_0.1.0_amd64.deb) |
| Linux (RPM) | [:material-download: **OpenJarvis.rpm**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis-0.1.0-1.x86_64.rpm) |
| Linux (AppImage) | [:material-download: **OpenJarvis.AppImage**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_0.1.0_amd64.AppImage) |

The app connects to `http://localhost:8000` automatically.

!!! warning "macOS: \"app is damaged\""
    If macOS says the app is damaged, clear the Gatekeeper quarantine flag:
    ```bash
    xattr -cr /Applications/OpenJarvis.app
    ```
    This is normal for open-source apps distributed outside the App Store.

!!! tip "All releases"
    Browse all versions on the [GitHub Releases](https://github.com/open-jarvis/OpenJarvis/releases) page.

### Build from source

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis/desktop
npm install
npm run tauri build
```

The built installer will be in `frontend/src-tauri/target/release/bundle/`.

---

## CLI

The command-line interface is the fastest way to interact with OpenJarvis
programmatically. Every feature is accessible from the terminal.

### Install

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync
uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml
```

Requires [Rust](https://rustup.rs/). On Python 3.14+, set `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` before the `maturin` command.

### Verify

```bash
jarvis --version
# jarvis, version 0.1.0
```

### First commands

```bash
jarvis ask "What is the capital of France?"

jarvis ask --agent orchestrator --tools calculator "What is 137 * 42?"

jarvis serve --port 8000

jarvis doctor

jarvis model list

jarvis chat
```

!!! info "Inference backend required"
    The CLI requires a running inference backend (e.g., Ollama). See
    [Setting up an inference backend](#setting-up-an-inference-backend) below.

---

## Python SDK

For programmatic access, the `Jarvis` class provides a high-level sync API.

### Install

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync
uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml
```

Requires [Rust](https://rustup.rs/). On Python 3.14+, set `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` before the `maturin` command.

### Quick example

```python
from openjarvis import Jarvis

j = Jarvis()
print(j.ask("Explain quicksort in two sentences."))
j.close()
```

### With agents and tools

```python
result = j.ask_full(
    "What is the square root of 144?",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(result["content"])       # "12"
print(result["tool_results"])  # tool invocations
print(result["turns"])         # number of agent turns
```

### Composition layer

For full control, use the `SystemBuilder`:

```python
from openjarvis import SystemBuilder

system = (
    SystemBuilder()
    .engine("ollama")
    .model("qwen3:8b")
    .agent("orchestrator")
    .tools(["calculator", "web_search", "file_read"])
    .enable_telemetry()
    .enable_traces()
    .build()
)

result = system.ask("Summarize the latest AI news.")
system.close()
```

See the [Python SDK guide](../user-guide/python-sdk.md) for the full API reference.

---

## Requirements

| Requirement | Version | Install | Notes |
|-------------|---------|---------|-------|
| Python | 3.10+ | [python.org](https://www.python.org/downloads/) | Required |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` or `brew install uv` (macOS) | Python package & project manager |
| Git | any | [git-scm.com](https://git-scm.com/) or `brew install git` (macOS) | Required |
| Rust | stable | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` | Required for the Rust extension |
| Inference backend | any | See [below](#setting-up-an-inference-backend) | At least one of Ollama, vLLM, llama.cpp, SGLang, or a cloud API |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) or `brew install node` (macOS) | Required for the browser UI; 22+ for the WhatsApp Baileys channel bridge |

!!! tip "macOS users"
    See the [macOS Installation Guide](macos.md) for a complete step-by-step walkthrough
    covering Homebrew, uv, Rust, llama.cpp, and common pitfalls.

## Optional Extras

OpenJarvis uses optional extras to keep the base installation lightweight.

### Inference Backends

| Extra | Install Command | Description |
|-------|----------------|-------------|
| `inference-cloud` | `uv sync --extra inference-cloud` | OpenAI and Anthropic APIs |
| `inference-google` | `uv sync --extra inference-google` | Google Gemini API |

!!! note "Ollama, vLLM, and llama.cpp are HTTP-based"
    These engines have no additional Python dependencies — OpenJarvis communicates over HTTP. You still need the engine software running on your machine.

### Memory Backends

| Extra | Install Command | Description |
|-------|----------------|-------------|
| `memory-faiss` | `uv sync --extra memory-faiss` | FAISS vector store |
| `memory-colbert` | `uv sync --extra memory-colbert` | ColBERTv2 late-interaction retrieval |
| `memory-bm25` | `uv sync --extra memory-bm25` | BM25 sparse retrieval |

!!! tip "SQLite memory is always available"
    The default SQLite/FTS5 memory backend requires no additional dependencies.

### Server & Other

| Extra | Install Command | Description |
|-------|----------------|-------------|
| `server` | `uv sync --extra server` | OpenAI-compatible API server (`jarvis serve`) |
| `dev` | `uv sync --extra dev` | Development and testing tools |
| `docs` | `uv sync --extra docs` | Documentation build tools |

Combine extras:

```bash
uv sync --extra server --extra memory-faiss --extra inference-cloud
```

## Setting Up an Inference Backend

OpenJarvis requires at least one inference backend. Choose the one that matches your hardware.

### Ollama (Recommended)

The easiest way to get started. Handles model downloading and serving automatically.

1. Install from [ollama.com](https://ollama.com)
2. Start the server and pull a model:

    ```bash
    ollama serve
    ollama pull qwen3:0.6b
    ```

3. Verify: `jarvis model list`

!!! tip "Best for: Apple Silicon Macs, consumer NVIDIA GPUs, CPU-only systems"

### vLLM

High-throughput serving optimized for datacenter GPUs.

1. Install following the [official guide](https://docs.vllm.ai)
2. Start: `vllm serve Qwen/Qwen2.5-7B-Instruct`
3. Auto-detected at `http://localhost:8000`

!!! tip "Best for: NVIDIA datacenter GPUs (A100, H100), AMD GPUs"

### llama.cpp

Efficient CPU and GPU inference with GGUF quantized models.

1. Build from [github.com/ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp)
2. Start: `llama-server -m /path/to/model.gguf --port 8080`
3. Auto-detected at `http://localhost:8080`

### Cloud APIs

```bash
uv sync --extra inference-cloud --extra inference-google
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Next Steps

- [Quick Start](quickstart.md) — Run your first query
- [Configuration](configuration.md) — Customize engine hosts, model routing, memory, and more
