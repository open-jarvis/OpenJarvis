---
title: Run OpenJarvis Offline
description: Prepare a local OpenJarvis installation for offline inference
---

# Run OpenJarvis Offline

OpenJarvis can answer chat requests without internet when its local runtime,
Python dependencies, and model are already installed. Downloads, updates, web
search, cloud engines, and online connectors are not available offline.

## Prepare while online

Install OpenJarvis before disconnecting. For command-line chat from a source
checkout, install the locked Python dependencies:

```bash
uv sync
```

For the Desktop app, run the dependency command it uses on startup, from the
repository root:

```bash
uv sync --extra desktop --extra inference-cloud --extra inference-google --group desktop-native
```

This includes the native extension and Desktop's Python dependencies. Run it
while online so uv can fetch packages that are not already cached.

Install Ollama, start it, and download the model you plan to use:

```bash
ollama pull qwen3.5:4b
ollama list
```

The model must appear in `ollama list` before going offline. Choose a smaller
or larger model based on your machine, and use that exact installed tag as
`intelligence.default_model` below. Model pulls require internet and are not
retried successfully while offline.

For the Desktop app, complete its first launch and backend setup while online
as well. Its startup sync needs the dependencies to be installed already or
present in uv's cache for offline launch.

## Use the local-only configuration

Start from
[`offline-local.toml`](../../configs/openjarvis/examples/offline-local.toml).
It selects Ollama, disables online tools and update checks, and turns off
optional analytics, telemetry, and traces. It does not overwrite your existing
OpenJarvis config.

To try it from this repository in PowerShell:

```powershell
$env:OPENJARVIS_CONFIG = (Resolve-Path .\configs\openjarvis\examples\offline-local.toml).Path
$env:UV_OFFLINE = "1"
uv run --offline jarvis ask "Answer using the local model."
```

On macOS or Linux:

```bash
export OPENJARVIS_CONFIG="$PWD/configs/openjarvis/examples/offline-local.toml"
export UV_OFFLINE=1
uv run --offline jarvis ask "Answer using the local model."
```

`UV_OFFLINE=1` prevents uv from trying to fetch missing packages. If it reports
a missing cached dependency, reconnect and run the install step before trying
again. The same applies to the model: download it first, then disconnect.

For an existing config, keep your current settings and apply only the local
engine/model and disable online tools such as `web_search` and cloud/MCP
connectors. Disable the CLI version check with `[updates] auto_update = false`.
The Tauri Desktop updater may still attempt a best-effort update check; this
does not provide inference or model downloads.

## What works offline

- Chat and inference through a running local engine such as Ollama, using a
  model already present on disk.
- Local files and local memory, when their tools/backends are configured.
- The browser and Desktop UI when their local frontend and backend are already
  installed and running.

Cloud inference, web search, OAuth sign-in, online connectors, package/model
downloads, and application updates require connectivity. Keep an internet
connection available when updating OpenJarvis or refreshing dependencies.
