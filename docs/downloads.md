---
title: Downloads
description: Download the OpenJarvis desktop app, browser app, CLI, or Python SDK
---

# Downloads

OpenJarvis runs entirely on your hardware. Choose the interface that fits your workflow.

---

## Desktop App

The desktop app is a native window for the OpenJarvis chat UI. All inference and backend
processing happens on your local machine — the app connects to the backend you start locally.

!!! info "Backend required"
    Start the backend before opening the desktop app. The quickstart script handles everything:
    ```bash
    git clone https://github.com/open-jarvis/OpenJarvis.git && cd OpenJarvis
    ./scripts/quickstart.sh
    ```

### Download

| Platform | Download | Notes |
|----------|----------|-------|
| macOS (Apple Silicon) | [:material-download: **OpenJarvis.dmg**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_1.0.0_aarch64.dmg) | M1/M2/M3/M4 Macs |
| Windows (64-bit) | [:material-download: **OpenJarvis-setup.exe**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_1.0.0_x64-setup.exe) | Windows 10+ |
| Linux (DEB) | [:material-download: **OpenJarvis.deb**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_1.0.0_amd64.deb) | Ubuntu, Debian |
| Linux (RPM) | [:material-download: **OpenJarvis.rpm**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis-1.0.0-1.x86_64.rpm) | Fedora, RHEL |
| Linux (AppImage) | [:material-download: **OpenJarvis.AppImage**](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_1.0.0_amd64.AppImage) | Any distro |

!!! tip "All releases"
    Browse all versions on the [GitHub Releases](https://github.com/open-jarvis/OpenJarvis/releases) page.

### macOS: "app is damaged" fix

macOS Gatekeeper quarantines apps downloaded from the internet that aren't notarized
by Apple. If you see **"OpenJarvis is damaged and can't be opened"**, run this in
Terminal to clear the quarantine flag:

```bash
xattr -cr /Applications/OpenJarvis.app
```

Then open the app normally. If you installed from the DMG but haven't moved it to
`/Applications` yet, point the command at wherever the `.app` bundle is:

```bash
xattr -cr ~/Downloads/OpenJarvis.app
```

!!! note
    This is standard for open-source macOS apps distributed outside the App Store.
    The command removes the quarantine extended attribute — it does not modify the app.

### What's included

The desktop app provides:

- **Full chat UI** — same interface as the browser app, in a native window
- **Energy monitoring** — real-time power consumption tracking
- **Telemetry dashboard** — token throughput, latency, and cost comparison vs. cloud models
- **System tray** — quick access without keeping a terminal open

The backend (Ollama, Python API server, inference) runs separately on your machine.

### Build from source

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis/desktop
npm install
npm run tauri build
```

The built installer will be in `desktop/src-tauri/target/release/bundle/`.

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

1. Checks for Python 3.10+ and Node.js 22+
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
    cd frontend && npm install && cd ..
    ```

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

### What you get

- **Chat interface** — markdown rendering, streaming responses, conversation history
- **Tool use** — calculator, web search, code interpreter, file I/O
- **System panel** — live telemetry, energy monitoring, cost comparison vs. cloud models
- **Dashboard** — energy graphs, trace debugging, cost breakdown
- **Settings** — model selection, agent configuration, theme toggle

---

## CLI

The command-line interface is the fastest way to interact with OpenJarvis
programmatically. Every feature is accessible from the terminal.

### Install

=== "uv (recommended)"

    ```bash
    uv pip install openjarvis
    ```

=== "pip"

    ```bash
    pip install openjarvis
    ```

=== "From source"

    ```bash
    git clone https://github.com/open-jarvis/OpenJarvis.git
    cd OpenJarvis
    uv sync
    ```

### Verify

```bash
jarvis --version
# jarvis, version 1.0.0
```

### First commands

```bash
# Ask a question
jarvis ask "What is the capital of France?"

# Use an agent with tools
jarvis ask --agent orchestrator --tools calculator "What is 137 * 42?"

# Start the API server
jarvis serve --port 8000

# Run diagnostics
jarvis doctor

# List available models
jarvis model list

# Interactive chat
jarvis chat
```

!!! info "Inference backend required"
    The CLI requires a running inference backend (e.g., Ollama). See the
    [Installation guide](getting-started/installation.md#setting-up-an-inference-backend)
    for setup instructions.

---

## Python SDK

For programmatic access, the `Jarvis` class provides a high-level sync API.

### Install

```bash
pip install openjarvis
```

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

See the [Python SDK guide](user-guide/python-sdk.md) for the full API reference.
