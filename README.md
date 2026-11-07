# Friday-AI

**Personal AI, on your own device.**

Friday-AI is a personal AI assistant that runs locally by default. It is built on top of
[OpenJarvis](https://github.com/open-jarvis/OpenJarvis) (Apache-2.0), the local-first AI
framework from Stanford's Hazy Research and Scaling Intelligence Lab.

> Friday-AI is an independent fork. It is not affiliated with or endorsed by the
> OpenJarvis maintainers, Stanford, or Marvel.

## Why Friday-AI?

Most personal AI assistants still send every request to a cloud API, so your "personal"
AI depends on someone else's server. Friday-AI follows the local-first approach of
OpenJarvis: the model runs on your own computer through Ollama, and the cloud is used only
if you choose to configure it.

The underlying framework is built around three ideas:

- **Shared building blocks** for on-device agents
- **Evaluations** that treat energy, latency and cost as important as accuracy
- **A learning loop** that improves models using your local trace data

## Installation

Friday-AI currently installs from source. You need Python 3.10 to 3.13, Git,
[uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com).

```bash
git clone https://github.com/aadityasharma2627-code/Friday-AI.git
cd Friday-AI
uv sync --extra server
ollama pull qwen3.5:2b
uv run friday doctor
```

On Windows, if `uv` is not found, use `python -m uv` instead of `uv`. Python 3.14 may fail
on Windows because some packages have no wheels yet, so use `--python 3.12`.

The browser interface (`friday gui`) also needs Node.js 22+. Memory and document search
need the Rust extension, which is an extra build step.

## Quick start

Prefix commands with `uv run`, or activate the virtual environment first.

```bash
friday                               # start chatting (default preset: chat-simple)
friday ask "What is the capital of France?"
friday doctor                        # check your installation
friday gui                           # start the browser interface (needs Node.js 22+)
friday init --preset <name> --force  # replace your config with a starter preset
```

`--force` overwrites your existing config at `~/.friday_ai/config.toml`, so back it up first.

### Presets

| Preset | What it does |
|---|---|
| `chat-simple` | Lightweight conversation, no tools (default) |
| `deep-research` | Multi-hop research across indexed documents, with citations |
| `code-assistant` | Agent with code execution, file I/O and shell access |
| `scheduled-monitor` | Stateful agent on a schedule, with memory |
| `morning-digest-mac` / `-linux` / `-minimal` | Spoken daily briefing from email, calendar, health and news |

Example:

```bash
friday init --preset morning-digest-minimal --force
friday connect gdrive      # one sign-in covers Gmail, Calendar and Tasks
friday digest --fresh      # generate your first briefing
```

## Built-in agents

Friday-AI includes eight agents that run on demand, on a schedule, or continuously.

| Agent | Type | What it does |
|---|---|---|
| `morning_digest` | Scheduled | Daily briefing from email, calendar, health and news, with audio |
| `deep_research` | On-demand | Multi-hop research with citations across web and local documents |
| `monitor_operative` | Continuous | Long-horizon monitoring with memory, compression and retrieval |
| `orchestrator` | On-demand | Multi-turn reasoning with automatic tool selection |
| `native_react` | On-demand | Thought, action, observation loop |
| `operative` | Continuous | Persistent autonomous agent with state management |
| `native_openhands` | On-demand | Generates and runs Python code |
| `simple` | On-demand | Single-turn chat, no tools |

## Skills

Skills teach agents how to use tools better. Every skill is a tool that agents can find
in a catalog and use when needed.

```bash
friday skill install hermes:arxiv
friday ask "Use the code-explainer skill to explain: for i in range(5): print(i*2)"
```

Skills can be imported from Hermes Agent, OpenClaw, or any GitHub repository.

## Privacy and safety

- With Ollama and a local model, prompts are processed on your machine.
- Cloud models, web search and integrations send data to outside services and may cost money.
- If an API key such as `OPENAI_API_KEY` is set, setup may suggest a cloud model as the default.
- Code and shell tools can act on your real files. Enable them only when you need them.
- Never commit API keys or your config file to Git.

## What changed from OpenJarvis

- Renamed the project from OpenJarvis to Friday-AI (Python package `friday_ai`, command `friday`)
- Rewrote the README

All original code is by the OpenJarvis authors. See the
[upstream repository](https://github.com/open-jarvis/OpenJarvis) for the original project,
its documentation, community and releases.

## Upstream community

- Original project: [github.com/open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
- Documentation: [open-jarvis.github.io/OpenJarvis](https://open-jarvis.github.io/OpenJarvis)

## Contributing

Issues and pull requests are welcome. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

```bash
git clone https://github.com/aadityasharma2627-code/Friday-AI.git
cd Friday-AI
uv sync --extra dev
uv run pre-commit install
uv run pytest tests/ -v
```

## Citation

Friday-AI is based on OpenJarvis. If you use the underlying framework in research, please
cite the original paper:

```bibtex
@misc{saadfalcon2026openjarvispersonalaipersonal,
      title={OpenJarvis: Personal AI, On Personal Devices},
      author={Jon Saad-Falcon and Avanika Narayan and Robby Manihani and Tanvir Bhathal and Herumb Shandilya and Hakki Orhun Akengin and Gabriel Bo and Andrew Park and Matthew Hart and Caia Costello and Chuan Li and Christopher Ré and Azalia Mirhoseini},
      year={2026},
      eprint={2605.17172},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2605.17172},
}
```

## License

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.