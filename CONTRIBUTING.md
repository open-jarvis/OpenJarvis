# Contributing to OpenJarvis

Thank you for your interest in contributing to OpenJarvis! This guide covers everything you need to know — from why to contribute, to how to submit your first pull request.

---

## Why Contribute?

Contributing to OpenJarvis isn't just about code — it's about building the future of on-device AI together. Here's what you get:

### Paper Acknowledgment

All contributors with merged pull requests will be acknowledged as contributors on the OpenJarvis paper release.

### Mac Mini Giveaway

We're giving away a Mac Mini to one lucky contributor! Install OpenJarvis on your personal machine and opt in via the desktop app to share anonymized savings data (FLOPs, dollar cost, energy) for a chance to win. Your data is fully anonymous — no IP, no hardware info beyond savings metrics. You must share your email via the desktop app to be eligible.

See the [Savings Leaderboard](https://open-jarvis.github.io/OpenJarvis/leaderboard/) for details.

### Path to Maintainership

Consistent contributors can grow into project maintainers:

- **Contributor** — anyone with a merged PR
- **Reviewer** — invited after 3+ merged PRs in a domain area, can review PRs
- **Maintainer** — reviewers who demonstrate sustained engagement and good judgment

### Recognition

Contributors are recognized in release notes and on our GitHub repository.

---

## Ways to Contribute

### Good First Contributions

These are great starting points for new contributors:

- Documentation improvements and typo fixes
- Bug reports with reproducible steps
- New eval datasets and scorers
- Test coverage improvements

Look for issues labeled [`good-first-issue`](https://github.com/open-jarvis/OpenJarvis/labels/good-first-issue).

### Ideal Contributions

- Bug fixes with tests
- Performance improvements
- New tools, engines, or agents following the [registry pattern](docs/development/contributing.md#registry-pattern)
- New channel integrations (Telegram, Discord, Slack, etc.)

### Harder to Review

These require more context and review time. **Please open an issue for discussion before starting a PR:**

- New primitives or major extensions to existing ones
- Large refactors
- Changes to core abstractions (`BaseAgent`, `InferenceEngine`, etc.)

### May Not Be Accepted

To avoid wasted effort, note that PRs in these categories are unlikely to be merged:

- Changes that break backwards compatibility in the public API
- Changes that add significant new dependencies without justification
- Changes that add friction to the user experience

---

## Getting Started

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | Required |
| [uv](https://docs.astral.sh/uv/) | Latest | Package manager |
| Node.js | 22+ | Only needed for ClaudeCodeAgent and WhatsApp channel |

### Setup

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync --extra dev
```

### Pre-commit Hooks

We use [pre-commit](https://pre-commit.com/) to run linting and formatting checks before each commit:

```bash
uv run pre-commit install
```

This installs Git hooks that automatically run [Ruff](https://docs.astral.sh/ruff/) on every commit. If the hooks fail, fix the issues and commit again.

For detailed development setup, code conventions, and project structure, see the [Development Guide](docs/development/contributing.md).

---

## Claiming Issues

1. Browse the [Roadmap](https://open-jarvis.github.io/OpenJarvis/development/roadmap/) for an item that interests you
2. Check if a [GitHub issue](https://github.com/open-jarvis/OpenJarvis/issues) already exists for it — if not, [open one](https://github.com/open-jarvis/OpenJarvis/issues/new/choose) describing what you'd like to work on
3. Comment **"take"** on the issue to get auto-assigned
4. Fork, branch, and start working

If you've claimed an issue but can't finish it, please leave a comment so someone else can pick it up.

---

## Proposing Changes

### Trivial Changes

For small fixes (typos, doc improvements, simple bug fixes), go ahead and open a PR directly.

### Non-trivial Changes

For larger changes — new features, refactors, new dependencies — **open an issue first** to discuss the approach. This saves everyone time by catching design issues early.

Use the appropriate [issue template](https://github.com/open-jarvis/OpenJarvis/issues/new/choose):
- **Bug Report** — for bugs with reproduction steps
- **Feature Request** — for new functionality
- **New Eval Dataset** — for contributing benchmarks

---

## Pull Request Process

### Before Submitting

1. Run the full test suite:
   ```bash
   uv run pytest tests/ -v
   ```
2. Run the linter:
   ```bash
   uv run ruff check src/ tests/
   ```
3. Run the formatter:
   ```bash
   uv run ruff format --check src/ tests/
   ```
4. Add tests for new functionality
5. Follow the [registry pattern](docs/development/contributing.md#registry-pattern) for new components

### Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add FAISS memory backend
fix: handle empty tool responses in orchestrator
docs: update engine discovery documentation
test: add coverage for BM25 backend
refactor: simplify agent base class helpers
```

Keep the first line under 72 characters. Reference relevant issues (e.g., `fixes #42`).

### What Makes a Good PR

- **Focused** — one feature, fix, or refactor per PR
- **Tested** — includes unit tests covering new code paths
- **Documented** — updates docstrings and docs if adding public API
- **Backwards compatible** — avoids breaking existing interfaces without discussion

---

## Contribution Areas

OpenJarvis is built on five composable primitives. Here's where you can contribute:

| Area | What to Build | Guide |
|---|---|---|
| **Intelligence** | Model catalog entries, routing strategies | [Dev Guide](docs/development/contributing.md) |
| **Engines** | New inference backends (e.g., TensorRT, ONNX) | [Dev Guide](docs/development/contributing.md) |
| **Agents** | New agent types, agent improvements | [Dev Guide](docs/development/contributing.md) |
| **Tools** | New tools (browser, API clients, etc.) | [Dev Guide](docs/development/contributing.md) |
| **Learning** | Router policies, reward functions, training | [Dev Guide](docs/development/contributing.md) |
| **Evals** | New datasets, scorers, benchmark configs | [Dev Guide](docs/development/contributing.md) |
| **Channels** | Chat platform integrations | [Dev Guide](docs/development/contributing.md) |
| **Rust Port** | PyO3 bindings, crate parity with Python | See `rust/` directory |

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold this code.

---

## Questions?

- Open a [Discussion](https://github.com/open-jarvis/OpenJarvis/discussions) for questions and help
- Check the [documentation](https://open-jarvis.github.io/OpenJarvis/) for guides and API reference
