# Data-boundary scan

`jarvis scan --data-boundaries` reports application-level data boundaries in the
current OpenJarvis configuration. It complements the existing host/environment
scan, which checks OS posture such as disk encryption, cloud-sync agents, remote
access tools, and exposed engine ports.

The data-boundary scan is a configuration diagnostic. It is not a vulnerability
scanner, a legal privacy assessment, a network monitor, or an OAuth-scope audit.

## Run the scan

```bash
jarvis scan --data-boundaries
jarvis scan --data-boundaries --json
jarvis scan --data-boundaries --json --show-paths
jarvis scan --data-boundaries --strict
```

`--strict` exits with status code `1` when the report contains either a `fail`
or a `warn` finding. Use it when CI or pre-demo checks need to enforce a
conservative local-only posture.

Without `--strict`, the command always exits `0` even when fail or warn findings
are present. This is useful for exploratory review.

On a fresh `jarvis init` configuration, common warn findings include
`server.host = "0.0.0.0"` and `telemetry.enabled = true`. Running
`jarvis scan --data-boundaries --strict` after init therefore exits `1` until
those defaults are tightened.

Absolute paths and connector file basenames are redacted by default so JSON
reports can be pasted into issues without revealing local usernames, mount
points, or account labels. Use `--show-paths` only for local debugging.

## What it checks

The scan inspects configuration values, environment-variable presence, and the
existence of known local runtime files. It does not read private content from
memory databases, trace databases, connector credentials, prompt files, logs, or
OAuth token files.

The current checks cover:

- cloud-capable model provider, engine, and default model settings
- local memory context injection combined with cloud-capable inference
- traces, telemetry, learning, training, and spec-search settings
- automatic memory service (`tools.storage.enabled` / `[memory].enabled`)
- deep research engine and model settings
- security bypass flags when cloud inference is configured
- unset `security.profile` (informational)
- web search, browser, local file, shell, code, and MCP tool surfaces
- server binding and unauthenticated A2A exposure
- channel enablement, channel credential fields, and channel credential env vars
- skills, skill auto-sync, digest sources, and cloud speech backends
- local stores such as `memory.db`, `traces.db`, `telemetry.db`, `scheduler.db`,
  embeddings, skill index, `.vault_key`, and memory files
- connector credential files under `connectors/*.json`, without reading them
- API-key environment variables such as `OPENAI_API_KEY` and `TAVILY_API_KEY`
- a scope note for frontend credential storage when cloud/API-key surfaces exist

Configured database paths (for example `traces.db_path` or `memory.db_path`)
are resolved from config when set, not only the default locations under the
OpenJarvis home directory.

## Status levels

| Status | Meaning |
| --- | --- |
| `fail` | A configuration composition is likely incompatible with strict local-only use. |
| `warn` | A configured surface may send data outside the local runtime or persist sensitive data. |
| `info` | A relevant setting or local store exists, with no immediate fail or warn condition. |

The command reports potential data paths. It does not prove that a path has been
used during a specific run.

JSON output includes `"schema_version": 1` for stable downstream parsing.

## Strict local-only checklist

For a conservative local-only setup, review these settings:

```toml
[analytics]
enabled = false

[traces]
enabled = false

[telemetry]
enabled = false

[agent]
context_from_memory = false

[intelligence]
provider = ""
preferred_engine = ""
default_model = ""  # local model name only

[engine]
default = "ollama"  # or another local engine

[tools]
enabled = ""

[tools.storage]
enabled = false

[tools.mcp]
enabled = false
servers = ""

[channel]
enabled = false

[learning]
enabled = false
auto_update = false
training_enabled = false

[learning.spec_search]
enabled = false

[server]
host = "127.0.0.1"

[security]
profile = "personal"

[a2a]
enabled = false
```

Also unset cloud and channel credentials from the process environment when they
are not needed.

## Scope and non-goals

The scan intentionally avoids reading private data. In particular, it does not:

- read connector JSON contents or OAuth scopes
- inspect browser `localStorage` or Tauri secure storage
- inspect frontend credential storage directly
- inspect installed skill source code
- intercept runtime network traffic
- classify provider retention or training policies
- prove that a configured path was used at runtime

Frontend credential storage is tracked separately from this CLI diagnostic. If a
cloud/API-key surface is present, the scan emits an informational scope note so
users know that browser/Tauri credential storage must be reviewed separately.

## Configuration resolution

The scan follows the same explicit configuration override used by the runtime:
if `OPENJARVIS_CONFIG` is set, that file is audited. Otherwise the scan uses
the default OpenJarvis config path under the resolved OpenJarvis home. If the
home directory cannot be resolved, the command reports a `config-root-error`
finding instead of crashing.

## See also

- [Security](security.md) — three-layer security model (host scan, config scan, BoundaryGuard)
- [Configuration](../getting-started/configuration.md) — full config reference
