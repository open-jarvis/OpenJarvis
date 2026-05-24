# OpenJarvis Agent Instructions

## Project Goal
This repository is used to build a local-first Korean personal AI assistant named Friday/Jarvis.

## Token-Saving Policy
- Prefer local Ollama models for normal runtime assistant responses.
- Do not add new cloud API calls unless explicitly requested.
- Do not expose or create API keys.
- Keep changes small and isolated.
- Use Codex for code editing and implementation.
- Use Claude mainly for architecture review, planning, and diff review.

## Build and Test
- Python package manager: uv
- Install core dependencies: `uv sync`
- Install server/cloud extras: `uv sync --extra server --extra inference-cloud`
- Run CLI: `uv run jarvis ask "hello"`
- Run tests if available: `uv run pytest tests/ -q`

## Coding Rules
- Do not modify unrelated files.
- Do not commit cache files, build outputs, or secrets.
- Explain every changed file in the final summary.
- Preserve existing OpenAI, Anthropic, Gemini, and OpenRouter support unless specifically asked to remove them.
