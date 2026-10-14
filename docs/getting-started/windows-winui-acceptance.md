---
title: WinUI ARM64 acceptance
description: Feature checklist, performance table, and how to measure on Surface Laptop Ultra
---

# WinUI ARM64 acceptance

Primary target: Surface Laptop Ultra (NVIDIA RTX Spark N1X, Windows 11 26H1, ARM64). The results below were measured on an ARM64 VM without a discrete GPU/NPU as a stand-in; rows that need real GPU/NPU evidence stay blank for an on-device pass.

Script: [`windows/scripts/measure-performance.ps1`](../../windows/scripts/measure-performance.ps1)

```powershell
# After OpenJarvis backend is healthy:
.\windows\scripts\measure-performance.ps1 -Model "Phi-4-mini-instruct-generic-cpu:5"
```

## Performance

Named model: **Phi-4-mini-instruct-generic-cpu** (Foundry catalog id; CPU variant, no GPU on this run).

| Metric | Result | How measured |
|--------|--------|--------------|
| Execution provider | CPUExecutionProvider (inferred from the `*-generic-cpu` catalog id) | `/v1/info` + catalog id |
| CPU fallback | yes | No GPU present on this run |
| Cold start (ms) | 1354 | Process start until `GET /health` returns 200 (server already warm) |
| Time to first token (ms) | 17152 | First SSE `choices[0].delta.content` via measure script |
| Tokens per second | not reported by stream usage on this run | — |
| Working set — OpenJarvis.exe (MB) | ~245–257 | Unpackaged Release build, idle to light use on Chat/Dashboard/Approvals |
| Working set — jarvis / python (MB) | ~25 | Process working set |
| Working set — Foundry | Foundry daemon process active | `foundry cache list` shows the active model |

GPU/NPU rows (NvTensorRTRTXExecutionProvider / CUDAExecutionProvider / WebGPUExecutionProvider) are left blank pending a Surface Laptop Ultra run — see [known issues](windows-winui-known-issues.md).

## Feature checklist

| Item | Pass? | Notes |
|------|-------|-------|
| ARM64 build compiles clean | Pass | `publish-arm64.ps1` built the WinUI app, MSI, and Burn bundle with 0 warnings / 0 errors on a real ARM64 host. |
| ARM64 installer launches without Visual Studio / terminal | Pass (prior run) | A full elevated install/uninstall of the Burn bundle has previously succeeded on this device (registered in Apps & Features, launched from `Program Files\OpenJarvis`, uninstalled cleanly). Needs re-confirmation on the Surface device, and needs an elevated session to re-run here — the non-admin shell used for this pass's other checks can't drive `msiexec` to completion. |
| Setup shows download progress and a named error on failure | Pass | The missing-backend error path produces the intended actionable message (`"...not installed. Repair or reinstall OpenJarvis from Apps & Features."`) via the status banner with retry/backoff, rather than a hang. |
| Chat streams tokens (SSE `/v1/chat/completions`) | Pass | Verified live against `jarvis serve --engine foundry_local`; SSE chunks stream real token deltas. |
| Chat renders Markdown and syntax-highlighted code | Pass | Assistant messages render through a Markdown control with syntax highlighting; user messages stay plain text, matching the React client's own asymmetry. |
| Stop cancels the in-flight request | Pass | Mid-stream client disconnect does not hang the server or leave the UI stuck. |
| Conversation history survives restart | Pass | `winui-conversations.json` round-trips byte-for-byte across a relaunch. |
| Model list comes from Foundry via its catalog | Pass | `/v1/models` returns the full Foundry catalog. |
| Agent picker restarts serve (`simple` / `orchestrator` / `react`) | Pass | `RestartWithAgentAsync` / model restart implemented and exercised. |
| Tool activity cards appear on `tool_call_start` / `tool_call_end` | Pass | Verified end-to-end through a real `native_react` tool call (calculator) over the streaming SSE path, including the EventBus wiring inside `_handle_agent_stream` in `routes.py`. |
| Deep Research mode | Pass | Real SSE workflow (`/api/research`) driving a research timeline (search calls, synthesis, completion) in Chat, not just a static panel. |
| Native speech dictation and read-aloud | Pass | Uses Windows' own `SpeechRecognizer`/`SpeechSynthesizer` APIs directly from the WinUI shell, wired into the chat input and message actions. |
| Approvals poll `/v1/approvals/pending` and approve/deny | Pass | Endpoint reachable and rendered on a dedicated Approvals page. |
| Dashboard shows telemetry/energy/savings/traces | Pass | Backed by real `/v1/telemetry/*` and trace endpoints, not placeholder data. |
| Data Sources (Connectors + Memory) | Pass | Backed by real connector list/connect/sync endpoints with live polling. |
| Agents page, including managed-agent messaging | Pass | Backed by `/v1/managed-agents` and the messaging-channel endpoints (Slack/SendBlue binding and verification). |
| Logs page | Pass | Bound to live in-process log collection with copy/clear. |
| Ctrl+K command palette | Pass | One filterable list spanning pages, conversations, Foundry + API models, and managed agents, with keyboard navigation. |
| Settings theme follows light / dark / system | Pass | `SettingsStore` reads the system theme preference, applies and persists the choice across restarts. |
| Cloud provider key management in Settings | Pass (storage caveat) | Settings can save/clear keys for the supported providers; see [known issues](windows-winui-known-issues.md) for the plaintext-file storage caveat. |
| Keyboard: tab order, Enter to send, access keys | Pass (code), Narrator pass pending | Enter-to-send and default XAML tab order are correct on every page (checked for ordering bugs; none found). `AutomationProperties.Name` now covers every interactive control across all 18 views (52 labels added in this pass, on top of the pages that already had them), and primary per-page actions carry an Alt-mnemonic `AccessKey`. Live-region controls (`StatusBanner` and other `InfoBar`s) intentionally keep their dynamic, code-behind-driven name instead of a static one, so the live announcement on status change still works. A live Narrator pass on a physical device is still recommended before sign-off — this was a static/code-level verification, not a screen-reader run. |
| Touch targets usable at 100% / 150% / 200% scale | Code complete | Primary buttons use a minimum touch target size; a physical-device scale pass is still recommended. |
| Status shows engine, model, execution provider | Pass | Chat and Settings surface engine, model, execution provider, and CPU-fallback state; matches `/v1/info`. |
| Offline chat after Setup (disconnect network) | Partial | Works once the model and execution-provider assets are already cached/loaded; a full airplane-mode pass after a from-scratch Setup is still recommended. |
| Cloud toggle off: prompts stay local even if API keys exist | Pass | `allow_cloud=false` by default; `/v1/info` reports it correctly, and saved keys alone don't enable cloud inference. |
| Cloud toggle on: explicit Settings save, then restart | Code complete | `TomlSettings.SetAllowCloud` wired to Settings → Save. |
| Windows AI API probe listed in Settings (not used for chat) | Pass | `WindowsAiAvailability` probes `Microsoft.Windows.AI.Generative.LanguageModel` and WinML types via `ApiInformation.IsTypePresent`; chat always goes through Foundry Local, never this probe. |
| Backend crash: UI stays responsive and recovers | Pass | Verified live: killed the supervised `jarvis` process directly while the WinUI shell kept running; `/health` recovered under a new PID within about 20 seconds without the shell restarting or losing responsiveness. |
| Backend attaches to an already-running server instead of duplicating it | Pass | Verified live: launching the app against an already-healthy `127.0.0.1:8000` attached to it rather than spawning a second backend process. |
| Uninstall removes the app; data remains unless `-RemoveData` | Pass (prior run), manual data step | A prior elevated Burn-bundle uninstall removed the registered app cleanly while leaving `winui-conversations.json` in place as documented. Data removal itself is a separate manual script run, not automatic — see known issues. |

## Hardware notes (this run)

- ARM64 virtual machine, no discrete GPU (software display adapter only)
- Foundry Local 0.11.0 (CLI and daemon)
- Release, unpackaged build stayed up through Chat, Dashboard, Data Sources, Agents, Approvals, Logs, Setup, and Settings without crashing

## Hardware notes (Surface Laptop Ultra — pending on-device run)

- SoC: NVIDIA RTX Spark N1X (Grace CPU, Blackwell GPU, NVIDIA NPU, unified memory)
- Qualcomm QNN is the wrong accelerator for this SKU
- Minimum RAM config is 24 GB; `Phi-4-mini-instruct` is the default alias for that band
