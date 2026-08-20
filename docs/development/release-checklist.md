# Release Checklist

Before tagging a release, run through this checklist on real machines (not just CI containers).

## Manual smoke tests (~30 min total)

For each platform below, start from a fresh user account / VM snapshot. Run the install one-liner and verify the steps in the table.

| Platform | One-liner | Verify |
|---|---|---|
| macOS Intel laptop | `curl -fsSL <url> \| bash` | (1)–(8) below |
| macOS ARM laptop | same | (1)–(8) |
| Ubuntu 22.04 fresh VM | same | (1)–(8) |
| Fedora 40 fresh VM | same | (1)–(8) |
| WSL2 Ubuntu on Windows | same | (1)–(8) |

### Verification steps

1. **Install completes ≤ 5 min** on typical broadband.
2. **`jarvis` (no args)** drops into a chat session within 2 s.
3. **First chat turn returns a response** from `qwen3.5:2b` via Ollama.
4. **Banner shows background work** ("Setting up in background: …") while it's still going.
5. **Completion notification fires** between turns when the bg work finishes (Rust extension or a model).
6. **`jarvis doctor`** exits 0 once all bg work completes; shows the Background tasks table.
7. **Re-run `curl … | bash`** on the same machine. It completes ≤ 30 s, says `[ok] step already done` for every step.
8. **`jarvis-uninstall`** removes `~/.openjarvis/` and `~/.local/bin/jarvis*`. Verify with `ls`.

## Cloud quick-path verification

On any one platform:

```bash
export ANTHROPIC_API_KEY=test-fake-key
jarvis init --force
```

Verify init proposes cloud (mentions "anthropic" in the prompt), and the resulting `config.toml` has `[intelligence] provider = "anthropic"`.

## Failure-mode spot checks

Run at least one failure scenario per release; rotate which one.

- Disconnect network mid-install — verify clear error and re-run completes.
- Delete `~/.openjarvis/config.toml` — verify bare `jarvis` re-runs init.
- Delete `~/.openjarvis/.venv` — verify re-running curl heals it.
- `EUID=0 bash install.sh` — verify hard-fail with "don't run as root".

## CI gates (automated, no manual action)

- All pytest tests pass: `uv run pytest tests/`
- All bats tests pass: see `.github/workflows/bash-tests.yml`
- Container integration matrix is green: see `.github/workflows/installer-integration.yml`
