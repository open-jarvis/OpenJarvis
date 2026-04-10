---
title: OpenJarvis
description: Personal AI, On Personal Devices
search:
  boost: 2
hide:
  - navigation
---

# Personal AI, On Personal Devices

<p align="center">
  <a href="https://github.com/open-jarvis/OpenJarvis/releases"><img src="https://img.shields.io/github/downloads/open-jarvis/OpenJarvis/total?label=Desktop%20Downloads&logo=github&color=blue" alt="Desktop Downloads"></a>
  <a href="https://pypistats.org/packages/openjarvisai"><img src="https://img.shields.io/pypi/dm/OpenJarvisAI?label=PyPI%20Installs/month&logo=python&color=blue" alt="PyPI Downloads"></a>
  <a href="https://github.com/open-jarvis/OpenJarvis"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/open-jarvis/OpenJarvis/main/.github/clone-stats/badge.json" alt="Git Clones"></a>
  <a href="https://github.com/open-jarvis/OpenJarvis"><img src="https://img.shields.io/github/stars/open-jarvis/OpenJarvis?style=social" alt="GitHub Stars"></a>
</p>

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

## Five Primitives for Personal AI

OpenJarvis is built around five composable layers. Each has a clean interface and can be swapped independently.

1. **Intelligence** — Pick a model, or let OpenJarvis pick one for your hardware. Manages the full catalog of local models across providers.
2. **Agents** — Multi-step reasoning with tool use. Seven built-in agent types from simple chat to orchestrated workflows.
3. **Tools** — Web search, calculator, file I/O, code interpreter, retrieval, and any external MCP server.
4. **Engine** — The inference runtime: [Ollama](https://ollama.com), [vLLM](https://github.com/vllm-project/vllm), [SGLang](https://github.com/sgl-project/sglang), [llama.cpp](https://github.com/ggerganov/llama.cpp), cloud APIs, and more. Auto-detects your hardware and recommends the best fit.
5. **Learning** — Your AI gets better over time. Every interaction generates traces that drive automatic improvements to model weights, prompts, and agent behavior.

---

## Key Features

<div class="grid cards" markdown>

-   **10+ Engine Backends**

    ---

    [Ollama](https://ollama.com), [vLLM](https://github.com/vllm-project/vllm), [SGLang](https://github.com/sgl-project/sglang), [llama.cpp](https://github.com/ggerganov/llama.cpp), [MLX](https://github.com/ml-explore/mlx), [Exo](https://github.com/exo-explore/exo), [LiteLLM](https://github.com/BerriAI/litellm), cloud (OpenAI/Anthropic/Google), and more. Same `InferenceEngine` interface, swap freely.

-   **Automated Workflows**

    ---

    Cron-based agents that monitor, summarize, and act. Code review, email triage, research digests — running 24/7 on your hardware.

-   **Hardware-Aware**

    ---

    Auto-detects GPU vendor, model, and VRAM. Recommends the optimal engine for your hardware.

-   **Offline-First**

    ---

    All core functionality works without a network connection. Cloud APIs are optional extras.

-   **OpenAI-Compatible API**

    ---

    `jarvis serve` starts a FastAPI server with SSE streaming. Drop-in replacement for OpenAI clients.

-   **Energy & Cost Tracking**

    ---

    Built-in telemetry for GPU power draw, token costs, and latency. See exactly what each query costs in watts and dollars.

</div>

---

## Documentation

<div class="grid cards" markdown>

-   **[Getting Started](getting-started/installation.md)**

    ---

    Install OpenJarvis, configure your first engine, and run your first query.

-   **[User Guide](user-guide/cli.md)**

    ---

    CLI, Python SDK, and guides for [Morning Digest](user-guide/morning-digest.md), [Deep Research](user-guide/deep-research.md), [Code Assistant](user-guide/code-assistant.md), [Scheduled Monitor](user-guide/scheduled-monitor.md), [Simple Chat](user-guide/chat-simple.md), agents, memory, tools, and telemetry.

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

## Research

OpenJarvis is part of [Intelligence Per Watt](https://www.intelligence-per-watt.ai/), a research initiative studying the efficiency of on-device AI systems. Developed at [Hazy Research](https://hazyresearch.stanford.edu/) and the [Scaling Intelligence Lab](https://scalingintelligence.stanford.edu/) at [Stanford SAIL](https://ai.stanford.edu/).

Read the [blog post](https://scalingintelligence.stanford.edu/blogs/openjarvis/) for the full research motivation, architecture details, and experimental results.

## Citation

```bibtex
@misc{saadfalcon2026openjarvis,
  title={OpenJarvis: Personal AI, On Personal Devices},
  author={Jon Saad-Falcon and Avanika Narayan and Herumb Shandilya and Hakki Orhun Akengin and Robby Manihani and Gabriel Bo and John Hennessy and Christopher R\'{e} and Azalia Mirhoseini},
  year={2026},
  howpublished={\url{https://scalingintelligence.stanford.edu/blogs/openjarvis/}},
}
```

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
