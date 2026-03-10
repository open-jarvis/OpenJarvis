<div align="center">
  <img alt="OpenJarvis" src="assets/OpenJarvis_Horizontal_Logo.png" width="400">

  <p><i>Composable, Programmable Systems for On-Device, Personal AI.</i></p>

  <p>
    <a href="https://www.intelligence-per-watt.ai/"><img src="https://img.shields.io/badge/project-intelligence--per--watt.ai-blue" alt="Project"></a>
    <a href="https://open-jarvis.github.io/OpenJarvis/"><img src="https://img.shields.io/badge/docs-mkdocs-blue" alt="Docs"></a>
    <img src="https://img.shields.io/badge/python-%3E%3D3.10-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License">
  </p>
</div>

---

> **[Documentation](https://open-jarvis.github.io/OpenJarvis/)**
>
> **[Project Site](https://www.intelligence-per-watt.ai/)**

OpenJarvis is a framework for building AI systems that run *entirely on local hardware*. Rather than treating intelligence as a cloud service, OpenJarvis provides composable abstractions for local model selection, inference, agentic reasoning, tool use, and learning — all aware of the hardware they run on.

```python
from openjarvis import Jarvis

j = Jarvis()                                      # auto-detect hardware + engine
response = j.ask("Explain backpropagation")       # route to best local model

j.ask("Solve x^2 - 5x + 6 = 0",                  # multi-turn agent with tools
      agent="orchestrator",
      tools=["calculator", "think"])

j.memory.index("./papers/")                       # index documents into local storage
results = j.memory.search("attention mechanism")  # semantic retrieval
j.close()
```

## Installation

```bash
pip install openjarvis            # core framework
pip install openjarvis[server]    # + FastAPI server
```

You also need a local inference backend: [Ollama](https://ollama.com), [vLLM](https://github.com/vllm-project/vllm), [SGLang](https://github.com/sgl-project/sglang), or [llama.cpp](https://github.com/ggerganov/llama.cpp).

## Quick Start

The fastest path is Ollama on any machine with Python 3.10+:

```bash
# 1. Install OpenJarvis
pip install openjarvis

# 2. Detect hardware and generate config
jarvis init

# 3. Install and start Ollama (https://ollama.com)
curl -fsSL https://ollama.com/install.sh | sh
ollama serve                      # start the Ollama server

# 4. Pull a model
ollama pull qwen3:8b

# 5. Ask a question
jarvis ask "What is the capital of France?"

# 6. Verify your setup
jarvis doctor
```

`jarvis init` auto-detects your hardware and recommends the best engine. After init, it prints engine-specific next steps. Run `jarvis doctor` at any time to diagnose configuration or connectivity issues.

## Development

From source, you need the Rust extension for full functionality (security, tools, agents, etc.):

```bash
# 1. Clone and install Python deps
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync --extra dev

# 2. Build and install the Rust extension (requires Rust toolchain)
uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml

# 3. Run tests
uv run pytest tests/ -v
```

See [Contributing](docs/development/contributing.md) for more.

## About

OpenJarvis is part of [Intelligence Per Watt](https://www.intelligence-per-watt.ai/), a research initiative studying the efficiency of on-device AI systems. The project is developed at [Hazy Research](https://hazyresearch.stanford.edu/) and the [Scaling Intelligence Lab](https://scalingintelligence.stanford.edu/) at [Stanford SAIL](https://ai.stanford.edu/).

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

## License

[Apache 2.0](LICENSE)
