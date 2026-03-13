---
title: OpenJarvis
description: Personal AI, On Personal Devices
hide:
  - navigation
---

# Personal AI, On Personal Devices

<p class="hero-tagline">
OpenJarvis is a research framework for composable, on-device AI systems.
Build personal AI that runs on your hardware. Cloud APIs are optional.
</p>

---

## Why OpenJarvis?

Personal AI agents are exploding in popularity, but nearly all of them still route intelligence through cloud APIs. Your "personal" AI continues to depend on someone else's server. At the same time, our [Intelligence Per Watt](https://www.intelligence-per-watt.ai/) research showed that local language models already handle 88.7% of single-turn chat and reasoning queries, with intelligence efficiency improving 5.3× from 2023 to 2025. The models and hardware are increasingly ready. What has been missing is the software stack to make local-first personal AI practical.

OpenJarvis is that stack. It is an opinionated framework for local-first personal AI, built around three core ideas: shared primitives for building on-device agents; evaluations that treat energy, FLOPs, latency, and dollar cost as first-class constraints alongside accuracy; and a learning loop that improves models using local trace data. The goal is simple: make it possible to build personal AI agents that run locally by default, calling the cloud only when truly necessary. OpenJarvis aims to be both a research platform and a production foundation for local AI, in the spirit of PyTorch.

---

## Get Started

=== "Browser App"

    Run the full chat UI locally with one script:

    ```bash
    git clone https://github.com/open-jarvis/OpenJarvis.git
    cd OpenJarvis
    ./scripts/quickstart.sh
    ```

    This installs dependencies, starts Ollama + a local model, launches the backend
    and frontend, and opens `http://localhost:5173` in your browser.

=== "Desktop App"

    The desktop app is a native window for the OpenJarvis UI.
    The backend (Ollama + inference) runs on your machine — start it first, then open the app.

    **Step 1.** Start the backend:

    ```bash
    git clone https://github.com/open-jarvis/OpenJarvis.git
    cd OpenJarvis
    ./scripts/quickstart.sh
    ```

    **Step 2.** Download and open the desktop app:

    [Download for macOS](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_0.1.0_universal.dmg){ .md-button .md-button--primary }

    Also available for [Windows](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_0.1.0_x64-setup.exe), [Linux (DEB)](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis_0.1.0_amd64.deb), and [Linux (RPM)](https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/OpenJarvis-0.1.0-1.x86_64.rpm). See the [Downloads](downloads.md) page for details.

    The app connects to `http://localhost:8000` automatically.

    !!! warning "macOS: run `xattr -cr /Applications/OpenJarvis.app` if the app shows as \"damaged\"."

=== "Python SDK"

    ```python
    from openjarvis import Jarvis

    j = Jarvis()                              # auto-detect engine
    response = j.ask("Explain quicksort.")
    print(response)
    ```

    For more control, use `ask_full()` to get usage stats, model info, and tool results:

    ```python
    result = j.ask_full(
        "What is 2 + 2?",
        agent="orchestrator",
        tools=["calculator"],
    )
    print(result["content"])       # "4"
    print(result["tool_results"])  # [{tool_name: "calculator", ...}]
    ```

=== "CLI"

    ```bash
    jarvis ask "What is the capital of France?"

    jarvis ask --agent orchestrator --tools calculator "What is 137 * 42?"

    jarvis serve --port 8000

    jarvis memory index ./docs/
    jarvis memory search "configuration options"
    ```

---

## Five Primitives

1. **Intelligence** — The LM: model catalog, generation defaults, quantization, preferred engine.
2. **Agents** — The agentic harness: system prompt, tools, context, retry and exit logic. Seven agent types.
3. **Tools** — MCP interface: web search, calculator, file I/O, code interpreter, retrieval, and any external MCP server.
4. **Engine** — The inference runtime: Ollama, vLLM, SGLang, llama.cpp, cloud APIs. Same `InferenceEngine` ABC.
5. **Learning** — Improvement loop: SFT weight updates, agent advisor, ICL updater. Trace-driven feedback.

---

## Key Features

<div class="grid cards" markdown>

-   **Five Composable Primitives**

    ---

    Intelligence, Agents, Tools, Engine, and Learning — each with a clear ABC interface and decorator-based registry.

-   **5 Engine Backends**

    ---

    Ollama, vLLM, SGLang, llama.cpp, and cloud (OpenAI/Anthropic/Google). Same `InferenceEngine` ABC.

-   **Hardware-Aware**

    ---

    Auto-detects GPU vendor, model, and VRAM. Recommends the optimal engine for your hardware.

-   **Offline-First**

    ---

    All core functionality works without a network connection. Cloud APIs are optional extras.

-   **OpenAI-Compatible API**

    ---

    `jarvis serve` starts a FastAPI server with SSE streaming. Drop-in replacement for OpenAI clients.

-   **Trace-Driven Learning**

    ---

    Every interaction is traced. The learning system improves models (SFT) and agents (prompt, tools, logic).

</div>

---

## Documentation

<div class="grid cards" markdown>

-   **[Getting Started](getting-started/installation.md)**

    ---

    Install OpenJarvis, configure your first engine, and run your first query.

-   **[User Guide](user-guide/cli.md)**

    ---

    CLI, Python SDK, agents, memory, tools, telemetry, and benchmarks.

-   **[Architecture](architecture/overview.md)**

    ---

    Five-primitive design, registry pattern, query flow, and cross-cutting learning.

-   **[API Reference](api-reference/openjarvis/index.md)**

    ---

    Auto-generated reference for every module.

-   **[Deployment](deployment/docker.md)**

    ---

    Docker, systemd, launchd. GPU-accelerated container images.

-   **[Development](development/contributing.md)**

    ---

    Contributing guide, extension patterns, roadmap, and changelog.

</div>

## Sponsors

<p>
  <a href="https://www.laude.org/">Laude Institute</a> &bull;
  <a href="https://datascience.stanford.edu/marlowe">Stanford Marlowe</a> &bull;
  <a href="https://cloud.google.com/">Google Cloud Platform</a> &bull;
  <a href="https://lambda.ai/">Lambda Labs</a> &bull;
  <a href="https://ollama.com/">Ollama</a> &bull;
  <a href="https://research.ibm.com/">IBM Research</a> &bull;
  <a href="https://hai.stanford.edu/">Stanford HAI</a>
</p>
