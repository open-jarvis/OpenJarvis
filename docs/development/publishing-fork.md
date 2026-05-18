# Publishing a sanitized fork

Before pushing to a public fork, ensure **no personal infrastructure** is in git:

## Never commit

- `~/.openjarvis/config.toml` (local install path)
- `.env`, `.env.*`, API keys, OAuth JSON, `vault.enc`
- MCP `servers` blocks with real URLs/tokens
- Hardware-specific paths (`/home/you/...`)
- Test artifacts (`.mcp_*_test.txt`)

These are listed in `.gitignore`. Config templates live under `configs/openjarvis/`.

## Pre-push check

```bash
./scripts/check-no-secrets.sh
```

## Recommended local setup

```bash
jarvis init --preset chat-simple
# Edit ~/.openjarvis/config.toml — engines, SearXNG, MCP, file_allowed_directories
```

MCP tokens belong in **environment variables** referenced from config, not literal secrets in TOML.
