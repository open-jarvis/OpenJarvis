---
title: macOS Installation Guide
description: Complete step-by-step guide to installing OpenJarvis on macOS with llama.cpp, including common pitfalls and fixes
search:
  boost: 2
---

# macOS Installation Guide

This guide walks through a complete OpenJarvis installation on macOS using **llama.cpp** as
the inference engine. It covers every step from scratch — including pitfalls not documented
elsewhere — and is suitable for both Apple Silicon and Intel Macs.

!!! tip "Prefer Ollama?"
    If you want the fastest possible setup, use [Ollama](installation.md#ollama-recommended)
    instead. This guide is for users who want to run GGUF models directly with llama.cpp,
    or who want a deeper understanding of the full stack.

---

## What You'll Install

| Tool | Purpose |
|------|---------|
| Xcode Command Line Tools | Apple's compiler toolchain — required by Homebrew, Rust, and `git` |
| Homebrew | macOS package manager — installs everything else |
| uv | Python version and dependency manager |
| Git | Clones the OpenJarvis repo |
| Node.js | Required for the browser UI |
| Rust | Compiles the OpenJarvis security and memory extension |
| llama.cpp | Local inference engine that runs GGUF model files |
| OpenJarvis | The framework itself |
| A GGUF model | The actual AI model (downloaded separately) |

---

## Step-by-Step Installation

### Step 0 — Install Xcode Command Line Tools

On a fresh Mac, you need Apple's developer command line tools before anything else
(`git`, `cc`, build headers). Install them with:

```bash
xcode-select --install
```

A GUI installer will pop up — accept and let it finish. If the tools are already
installed the command instead prints
`xcode-select: error: command line tools are already installed, use "Software Update" to install updates`
and exits non-zero, which is fine — you can move on.

!!! note "Homebrew will ask too"
    Step 1's Homebrew installer also requests the Command Line Tools if it doesn't see
    them. Running `xcode-select --install` upfront avoids the second prompt and confirms
    the tools landed correctly.

---

### Step 1 — Install Homebrew

Homebrew is the standard macOS package manager. Everything else in this guide is installed
through it.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

If you already have Homebrew, skip this step.

---

### Step 2 — Install uv

`uv` replaces pip, virtualenv, and pyenv in one tool. OpenJarvis uses it to manage Python
versions, virtual environments, and project dependencies.

```bash
brew install uv
```

---

### Step 3 — Install Git

Git is used to clone the OpenJarvis source code. It may already be present if you have
Xcode Command Line Tools installed.

```bash
brew install git
```

---

### Step 4 — Install Node.js

Node.js is required to build and run the browser frontend. Without it you can still use
the CLI, but not the web UI.

```bash
brew install node
```

---

### Step 5 — Install Rust

OpenJarvis includes a Rust extension that provides security scanning, memory indexing,
rate limiting, and tool execution. It must be compiled from source.

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

After the installer finishes, reload your shell so `rustc` is available:

```bash
source "$HOME/.cargo/env"
```

Verify:

```bash
rustc --version
```

---

### Step 6 — Install llama.cpp

llama.cpp is the inference engine that loads and runs GGUF model files. It is not a model
itself — think of it as a media player and the `.gguf` file as the content.

```bash
brew install llama.cpp
```

---

### Step 7 — Clone the OpenJarvis repo

Run this from your home directory or any neutral parent folder.

```bash
cd ~
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
```

!!! warning "Do not clone from inside an existing OpenJarvis folder"
    A common mistake is running `git clone` while already inside the repo, creating deeply
    nested duplicates (`OpenJarvis/OpenJarvis/OpenJarvis`). Always clone from `~` or a
    neutral parent directory.

---

### Step 8 — Pin Python to 3.12

!!! warning "Critical step — do not skip"
    OpenJarvis requires Python 3.10–3.13. Its Rust extension uses PyO3, which does not yet
    support Python 3.14. If `uv` has Python 3.14 available, it will use it by default,
    causing the Rust extension build to fail silently and resulting in ~250 test failures
    with `ModuleNotFoundError: No module named 'openjarvis_rust'`.

Pin the project to Python 3.12:

```bash
echo "3.12" > .python-version
uv python install 3.12
rm -rf .venv
uv venv
```

**Restart your terminal**, then verify:

```bash
uv run python --version
# Must show: Python 3.12.x
```

!!! tip "Why restart the terminal?"
    Without restarting, the shell may still reference the old virtual environment. This is
    the most common reason the version pin appears not to work.

---

### Step 9 — Install Python dependencies

```bash
uv sync --extra dev --extra server
```

The `--extra server` flag adds the FastAPI backend required for the browser UI.

---

### Step 10 — Build the Rust extension

This compiles the Rust extension and installs it into the virtual environment. It provides
security scanning, memory indexing, MCP tool execution, and rate limiting. This step takes
a few minutes on first run.

```bash
uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml
```

Verify it built correctly:

```bash
uv run python -c "import openjarvis_rust; print('Rust extension OK')"
```

---

### Step 11 — Install frontend dependencies

```bash
cd frontend && npm install && cd ..
```

---

### Step 12 — Download a model

OpenJarvis needs a GGUF model file to run inference. First install the Hugging Face CLI,
then download your chosen model.

```bash
uv tool install huggingface_hub
```

!!! note "The CLI command is `hf`, not `huggingface-cli`"
    When installed via `uv tool`, the Hugging Face CLI is invoked as `hf`.

=== "Qwen3 4B (~2.5 GB)"

    Faster, lower RAM requirement. Good for most everyday tasks.

    ```bash
    hf download bartowski/Qwen_Qwen3-4B-GGUF \
      --include "Qwen_Qwen3-4B-Q4_K_M.gguf" \
      --local-dir ~/models
    ```

=== "Qwen3 8B (~4.7 GB)"

    Better reasoning and instruction following. Requires more RAM.

    ```bash
    hf download bartowski/Qwen_Qwen3-8B-GGUF \
      --include "Qwen_Qwen3-8B-Q4_K_M.gguf" \
      --local-dir ~/models
    ```

!!! warning "Use the `Qwen_` prefix"
    bartowski's Qwen3 repos use the `Qwen_` prefix (e.g. `Qwen_Qwen3-4B-GGUF`). Using
    the shorter name without the prefix returns a "repository not found" error.

!!! tip "Apple Silicon vs Intel"
    On Apple Silicon, both models benefit from Metal GPU acceleration when using the MLX
    engine. On Intel, inference runs on CPU — the 4B model is recommended for speed.

---

### Step 13 — Configure OpenJarvis

Run the init command to detect your hardware and generate a config file:

```bash
uv run jarvis init
```

Then open the config and set the default model to match the filename you downloaded:

```bash
nano ~/.openjarvis/config.toml
```

Find the `default_model` line and update it, for example:

```toml
default_model = "Qwen_Qwen3-4B-Q4_K_M.gguf"
```

---

### Step 14 — Verify the installation

```bash
uv run jarvis doctor
```

A healthy setup looks like this:

```
✓  Python version         3.12.x
✓  Config file            ~/.openjarvis/config.toml
✓  Config parsing         Config loaded successfully
✓  Engine: llamacpp       Reachable
✓  Models: llamacpp       Qwen_Qwen3-4B-Q4_K_M.gguf
✓  Default model          Qwen_Qwen3-4B-Q4_K_M.gguf (on llamacpp)
```

!!! note "Warnings for other engines are normal"
    The `!` warnings for engines like `ollama`, `vllm`, and `lmstudio` simply mean those
    backends are not running. You only need `llamacpp` to be reachable.

---

## Running OpenJarvis

### CLI

Start llama-server in one terminal, then run queries in another:

```bash
# Terminal 1 — start the inference engine
llama-server -m ~/models/Qwen_Qwen3-4B-Q4_K_M.gguf -c 4096 -t 8

# Terminal 2 — ask a question
cd ~/OpenJarvis
uv run jarvis ask "What is the capital of France?"
```

### Browser UI

```bash
# Terminal 1 — inference engine
llama-server -m ~/models/Qwen_Qwen3-4B-Q4_K_M.gguf -c 4096 -t 8

# Terminal 2 — backend
cd ~/OpenJarvis && uv run jarvis serve --port 8000

# Terminal 3 — frontend
cd ~/OpenJarvis/frontend && npm run dev
```

Then open [http://localhost:5173](http://localhost:5173).

### Skip typing `uv run` every time

Activate the virtual environment for your current terminal session:

```bash
source ~/OpenJarvis/.venv/bin/activate
```

Your prompt will show `(openjarvis)` when active, and you can type `jarvis ask "..."` directly.

---

## Performance Tips

These tips apply when using llama.cpp for CPU inference.

| Flag | Effect |
|------|--------|
| `-c 4096` | Reduces context window from the 32,768 default, freeing RAM for faster inference |
| `-t 8` | Uses all available CPU threads (default is only 4) — adjust to your machine's thread count |
| `Q4_K_M` quantization | Best balance of size, speed, and quality for CPU inference |

On Apple Silicon, switching to the [MLX engine](../architecture/engine.md) gives
significantly better performance than llama.cpp for most models.

---

## Common Errors

### `No such file or directory` when loading model

The path `path/to/model.gguf` in examples is a placeholder. Replace it with your actual
model path, e.g.:

```bash
llama-server -m ~/models/Qwen_Qwen3-4B-Q4_K_M.gguf
```

---

### `No module named 'openjarvis_rust'`

The Rust extension did not build correctly, or was built against the wrong Python version.

1. Confirm Python 3.12 is active: `uv run python --version`
2. Rebuild: `uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml`

If the version shows 3.14, go back to [Step 8](#step-8--pin-python-to-312).

---

### `PyO3 version error — Python 3.14 too new`

```
error: the configured Python interpreter version (3.14) is newer than
PyO3's maximum supported version (3.13)
```

PyO3 0.23.5 supports Python up to 3.13. Follow [Step 8](#step-8--pin-python-to-312) to
pin to 3.12, then delete `.venv`, recreate it, and restart your terminal before retrying.

---

### `Repository not found` when downloading model

bartowski's Qwen3 repos use the `Qwen_` prefix. Use:

```
bartowski/Qwen_Qwen3-4B-GGUF   ✓
bartowski/Qwen3-4B-GGUF        ✗
```

---

### `No inference engine available`

llama-server is not running. Start it in a separate terminal before running any `jarvis`
commands, and wait until you see `model loaded` in the output.

---

### Python version still shows 3.14 after recreating the venv

Close the terminal completely and reopen it. The old venv path is cached in the shell
environment and persists across commands until the session ends.

---

### `zsh: command not found: huggingface-cli`

When installed via `uv tool`, the CLI is invoked as `hf`, not `huggingface-cli`:

```bash
hf download ...   # ✓
huggingface-cli download ...   # ✗
```

---

## Next Steps

- [Quick Start](quickstart.md) — Run your first query and explore agents and tools
- [Configuration](configuration.md) — Customize engine hosts, model routing, memory, and more
- [Architecture](../architecture/overview.md) — Understand how OpenJarvis is structured
