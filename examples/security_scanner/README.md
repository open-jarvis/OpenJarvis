# Security Scanner

Scan a local project directory for hardcoded secrets, vulnerability patterns,
and dependency issues using an AI-powered ReAct agent.

## Requirements

- FridayAI installed (`git clone https://github.com/open-jarvis/FridayAI.git && cd FridayAI && uv sync` or `uv sync --extra dev`)
- An inference engine running (Ollama, cloud API, vLLM, etc.)

## Usage

```bash
python examples/security_scanner/security_scanner.py --help
python examples/security_scanner/security_scanner.py --path ./my_project
python examples/security_scanner/security_scanner.py --path /home/user/app \
    --model gpt-4o --engine cloud --max-turns 30
```

## How It Works

The script creates a `Friday` instance configured with the `native_react` agent
and four tools:

- **shell_exec** -- runs shell commands to explore the project tree and search
  for patterns (e.g., `grep` for API keys)
- **file_read** -- reads source files and configs to inspect for secrets
- **code_interpreter** -- analyzes dependency manifests for vulnerable packages
- **think** -- reasons about severity and prioritizes findings

The ReAct agent follows a Thought-Action-Observation loop, adaptively exploring
the project until it can produce a structured security report with risk levels
and prioritized recommendations.
