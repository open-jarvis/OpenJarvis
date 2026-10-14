---
title: WinUI 3 desktop (ARM64)
description: Build and run the unpackaged WinUI 3 OpenJarvis app on Windows ARM64
---

# WinUI 3 desktop (ARM64)

OpenJarvis on Windows ARM64 is an unpackaged WinUI 3 app. After the user approves local setup, it starts Foundry Local (Windows ML), loads the selected model, launches `jarvis serve --engine foundry_local --agent simple`, and uses the same FastAPI contracts as the Tauri desktop.

End users install from the ARM64 bundle. They do not need a terminal, Visual Studio, or the .NET SDK.

## What you get

- Native WinUI 3 chat with Markdown, streaming and cancellation, per-message copy, tool-activity cards, Deep Research, speech dictation, and read-aloud
- Conversation history with search and delete in the upper part of the app-wide navigation pane
- A resizable app navigation pane (width is saved) and the circular OpenJarvis icon on the window, taskbar, and installer
- Native **Dashboard**, **Data Sources** (Connectors and Memory), **Agents** (including managed-agent messaging), **Approvals**, and **Logs** pages
- A Ctrl+K command palette (quick switcher for pages, conversations, models, and agents)
- Cloud and tool API key management in Settings (OpenAI/Anthropic/Google/OpenRouter/Atlas Cloud/Minimax/Tavily)
- Native speech (dictate into chat, read replies aloud) via Windows' own speech APIs, not the backend
- Automatic Foundry Local + `jarvis serve` process supervision (job object, backoff restart)
- A launch-time consent and progress screen; setup installs Foundry Local (ARM64 MSIX via `Add-AppxPackage`) when it is missing
- Local inference by default; cloud engines stay off until Settings opts in
- Offline chat after the first model and execution-provider download

The native pages do not yet cover every React-client feature. See [known issues](windows-winui-known-issues.md) for the remaining gaps, feature limits, and verification status. The local API remains available at `http://127.0.0.1:8000`.

## End-user install

1. Run `OpenJarvis-1.0.0-arm64.exe` (Burn bundle) or the MSI from the GitHub Actions `winui-arm64` workflow (artifacts are unsigned unless signing is configured).
2. The installer refuses x64 Windows. It requires ARM64.
3. On first launch, review the local-AI notice and select **Use Foundry Local and continue**. Nothing is installed, started, or downloaded before this confirmation.
4. The launch screen then installs and starts Foundry Local if necessary, downloads/loads `Phi-4-mini-instruct`, and starts the OpenJarvis API. On a machine without a usable GPU, model loading can fall back to a `*-generic-cpu` catalog entry.
5. The app opens Chat when all three setup steps are ready. Later launches reuse the saved consent and show live progress while checking the engine, model, and API server. Settings → **Setup** shows the current supervisor status and offers **Retry setup**.
6. After the model and execution-provider assets have been downloaded, local chat can run without a network connection.
7. Uninstall from Apps & Features. Conversations under `%USERPROFILE%\.openjarvis` and Foundry models stay unless you run [`windows/scripts/uninstall-cleanup.ps1`](../../windows/scripts/uninstall-cleanup.ps1) `-RemoveData`.

## Demo walkthrough (re-record on Ultra)

1. Install the Burn bundle → launch OpenJarvis.
2. On a fresh profile, approve local setup and watch the Inference Engine, AI Model, and API Server steps complete.
3. Chat: send a short prompt → watch streamed tokens → Stop to cancel.
4. Confirm conversation appears in history; restart the app and reopen it.
5. Change the model; confirm status returns to Ready.
6. Settings: theme light/dark; cloud toggle off; hardware line shows engine, model, execution provider.
7. Approvals page loads (empty is OK if no pending tools).
8. Open Dashboard, Data Sources, Agents, and Logs. Create or open an agent and inspect its detail tabs.
9. Press Ctrl+K and switch to a page, conversation, model, or agent.
10. Drag the navigation-pane splitter; restart and confirm its width persists. Confirm the window, taskbar, and Apps & Features icons.
11. Kill `jarvis` in Task Manager; confirm the UI stays responsive and the supervisor recovers.

See the [acceptance checklist](windows-winui-acceptance.md) for what has been verified and what still requires a physical-device or visual pass.

## Build from source (developers)

### Prerequisites

See [version pins](windows-winui-versions.md). You need:

- Windows 11 24H2 (build 26100) or later on ARM64. Surface Laptop Ultra ships Windows 11 26H1 and does not take 26H2.
- Visual Studio 2022 (or Build Tools) with the **WinUI / Windows App SDK** workload
- .NET 9 SDK (or a newer SDK that can target `net9.0-windows10.0.26100.0`)
- Rust `aarch64-pc-windows-msvc` (for `openjarvis_rust`)
- WiX Toolset 5
- `uv`

```powershell
cd OpenJarvis
$env:NUGET_PACKAGES = "$env:USERPROFILE\.nuget\packages"
.\windows\scripts\publish-arm64.ps1
```

That publishes a self-contained `win-arm64` app to `dist/OpenJarvis-win-arm64`, syncs the Python backend (`--extra server --group desktop-native`), and builds the MSI + Burn bundle into `dist/` when WiX builds succeed.

Manual publish (app only):

```powershell
dotnet publish windows\OpenJarvis.WinUI\OpenJarvis.WinUI.csproj `
  -c Release -r win-arm64 --self-contained true `
  /p:Platform=ARM64 /p:WindowsAppSDKSelfContained=true
```

## Runtime layout

| Path | Role |
|------|------|
| `Program Files\OpenJarvis\OpenJarvis.exe` | WinUI 3 shell |
| `Program Files\OpenJarvis\payload\` | Staged venv + source copied on first launch |
| `%LOCALAPPDATA%\OpenJarvis\venv` | CPython 3.12 + OpenJarvis |
| `%LOCALAPPDATA%\OpenJarvis\src` | Backend tree used by `uv run` fallbacks |
| `%LOCALAPPDATA%\OpenJarvis\runtime\` | Downloaded Foundry MSIX cache |
| `%LOCALAPPDATA%\OpenJarvis\logs\jarvis-serve.log` | Supervised backend output |
| `%USERPROFILE%\.openjarvis\config.toml` | Engine host, `allow_cloud` |
| `%USERPROFILE%\.openjarvis\winui-conversations.json` | Chat history |
| `%USERPROFILE%\.openjarvis\winui-settings.json` | WinUI preferences and saved setup consent |
| `%USERPROFILE%\.openjarvis\cloud-keys.env` | Cloud-provider keys saved by Settings |

The supervisor attaches to an existing healthy `http://127.0.0.1:8000` if one is already running.

## Changing the chat agent or model

The model picker loads the selected Foundry model and restarts `jarvis serve` with the new `--model`. Chat always starts the backend with `--agent simple`, matching the Tauri desktop; it has no chat-agent picker. Managed and tool-using agents are created from the **Agents** page.

## Cloud opt-in

`[engine] allow_cloud = false` by default. Settings → **Allow cloud inference** writes that flag; restart OpenJarvis for `jarvis serve` to attach cloud engines. Provider keys can be saved and hot-reloaded separately, but prompts remain local until cloud inference is explicitly enabled.

## Windows AI APIs

Settings probes `Microsoft.Windows.AI.Generative.LanguageModel` and WinML types with `ApiInformation.IsTypePresent`. Those APIs are **not** the chat engine. Chat always goes through Foundry Local → `foundry_local` → agents and tools.

## Related docs

- [Version pins](windows-winui-versions.md)
- [Acceptance checklist](windows-winui-acceptance.md)
- [Known issues](windows-winui-known-issues.md)
