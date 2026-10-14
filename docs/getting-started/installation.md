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
    uv sync --extra desktop
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
| macOS (Universal) | [:material-download: **OpenJarvis.dmg**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-v1.0.2/OpenJarvis_1.0.1_universal.dmg) |
| Windows (64-bit) | [:material-download: **OpenJarvis-setup.exe**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-v1.0.2/OpenJarvis_1.0.1_x64-setup.exe) |
| Linux (DEB) | [:material-download: **OpenJarvis.deb**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-v1.0.2/OpenJarvis_1.0.1_amd64.deb) |
| Linux (RPM) | [:material-download: **OpenJarvis.rpm**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-v1.0.2/OpenJarvis-1.0.1-1.x86_64.rpm) |
| Linux (AppImage) | [:material-download: **OpenJarvis.AppImage**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-v1.0.2/OpenJarvis_1.0.1_amd64.AppImage) |

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

## Hardware

OpenJarvis has no special hardware requirements of its own — the CLI, server, and
SDK run anywhere the software [Requirements](#requirements) below are met.
`jarvis init` detects your CPU, RAM, and GPU, then recommends an inference engine
and local model for the generated config. You can choose a different engine during
setup.

```bash
jarvis init          # detect hardware, write a matching config
```

### Recommended configurations

These are the Qwen3.5 recommendations for `llamacpp`, `mlx`, `ollama`, `vllm`, and
`sglang`. `jarvis init` can offer an already-running engine first, and your engine
choice can change the model. The bands use whole-number GB values and assume one
GPU; the formulas below determine the exact result.

| System RAM (no reported VRAM) | GPU VRAM (one GPU) | Recommended model | Download estimate |
|-------------------------------|--------------------|-------------------|-------------------|
| 5–14 GB | 1–8 GB | `qwen3.5:2b` | ~1.1 GB |
| 15–24 GB | 9–17 GB | `qwen3.5:4b` | ~2.2 GB |
| 25–44 GB | 18–35 GB | `qwen3.5:9b` | ~5.0 GB |
| 45 GB or more | 36 GB or more | `qwen3.5:27b` | ~14.9 GB |

The two memory columns are alternatives: when a GPU reports VRAM, the recommendation
uses VRAM across all detected GPUs; otherwise it uses system RAM. On Apple Silicon,
detection reports unified system memory as GPU memory.

### How the model is chosen

`jarvis init` first computes usable memory:

| Detected | Usable memory |
|----------|---------------|
| GPU reporting VRAM | `VRAM × max(GPU count, 1) × 0.9` |
| No GPU, or VRAM unavailable | `(total RAM − 4 GB) × 0.8` |

For the Qwen3.5 tier engines, a positive usable-memory value selects the first
tier it fits:

| Usable memory | Model |
|---------------|-------|
| Up to 8 GB | `qwen3.5:2b` |
| Up to 16 GB | `qwen3.5:4b` |
| Up to 32 GB | `qwen3.5:9b` |
| More than 32 GB | `qwen3.5:27b` |

All four recommended Qwen3.5 models are dense. The table describes the current
selection rule, not a guarantee that a model will fit or run well on every device
in a band.

### Inference engine

The detected GPU vendor and reported name select the engine:

| Detected GPU | Engine |
|--------------|--------|
| None or unrecognized GPU vendor | `llamacpp` |
| Apple GPU | `mlx` |
| NVIDIA name containing A100, H100, H200, L40, A10, or A30 | `vllm` |
| Other NVIDIA | `ollama` |
| Windows ARM + NVIDIA (RTX Spark / N1X) | `foundry_local` |
| AMD name containing MI300, MI325, MI350, or MI355 | `vllm` |
| Other AMD (including Radeon) | `lemonade` |

When `lemonade` is selected and usable memory is positive, `jarvis init` instead
recommends `Qwen3.6-35B-A3B-GGUF`. The Qwen3.5 tier and download tables above do
not apply to that default.

See [Setting Up an Inference Backend](#setting-up-an-inference-backend) for
installing the engine `jarvis init` picks.

### Minimum

The recommendation code imposes no CPU minimum. CPU-only inference speed depends
on your processor and core count.

Memory is the real floor. With 4 GB of RAM or less and no GPU, usable memory
is zero or less and no local model is recommended.

!!! tip "Low-memory and headless machines"
    You do not need a local model at all. Point OpenJarvis at a hosted API with the
    [cloud quick-path](install.md#cloud-quick-path) and the hardware tiers above
    stop applying.

### Storage

Model weights dominate disk usage — the estimates above range from ~1.1 GB to
~14.9 GB for the Qwen3.5 defaults. Budget additional space for the Python
environment and whichever inference engine you install.

!!! note "Overriding the detected defaults"
    These are defaults, not limits. The generated config records what was detected
    in a comment at the top of the file, and `default_model` under `[intelligence]`
    in `~/.openjarvis/config.toml` can be set to anything larger or smaller — see
    the [Configuration guide](configuration.md). Re-run `jarvis init --force` to
    re-detect and overwrite an existing config.

---

## Requirements

| Requirement | Version | Install | Notes |
|-------------|---------|---------|-------|
| Python | 3.10–3.13 | [python.org](https://www.python.org/downloads/) | Required. 3.14+ not yet supported (a core dependency lacks 3.14 wheels). |
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
| `desktop` | `uv sync --extra desktop` | Desktop/API server plus local speech input |
| `server` | `uv sync --extra server` | OpenAI-compatible API server (`jarvis serve`) |
| `dev` | `uv sync --extra dev` | Development and testing tools |
| `docs` | `uv sync --extra docs` | Documentation build tools |

Combine extras:

```bash
uv sync --extra desktop --extra memory-faiss --extra inference-cloud
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
