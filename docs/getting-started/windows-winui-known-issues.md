---

## title: WinUI known issues and limitations
description: Scope vs Tauri/React desktop, Parallels caveats, and upstream Ultra notes

# WinUI known issues and limitations

## Scope vs Tauri/React desktop

The WinUI shell now covers chat (with Markdown rendering, streaming, cancellation, per-message copy, tool-activity cards, Deep Research, and native speech dictation/read-aloud), conversation history, model/agent selection, Settings (theme, cloud opt-in, provider keys), a Dashboard, Data Sources (Connectors and Memory), an Agents page (including managed-agent messaging), Approvals, Logs, and a Ctrl+K command palette. The gaps below are the parts that are still intentionally smaller than the React/Tauri desktop, or that have a real limitation worth knowing about.


| Not in WinUI (or smaller than React)                                  | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Approvals bell/badge overlay                                          | Pending approvals surface only on the dedicated Approvals page; there is no notification badge elsewhere in the shell (nav pane, title bar) when an approval is waiting.                                                                                                                                                                                                                                                                                                   |
| Backend speech recognition/synthesis (`faster-whisper`/`ctranslate2`) | No reliable Windows ARM64 wheels for these packages, so the WinUI installer's Python payload omits them (`--extra server --group desktop-native` only). Chat dictation and read-aloud instead use Windows' own `SpeechRecognizer`/`SpeechSynthesizer` APIs directly from the WinUI shell, which is a different (and in some ways more native) implementation, not a missing feature — but voice quality/accuracy depends on the Windows speech engine rather than Whisper. |
| Cloud provider key storage                                            | Settings can save OpenAI/Anthropic/Google/OpenRouter/Atlas Cloud/Minimax keys (plus Tavily via tool credentials), but they are written to a plain local file (`cloud-keys.env` under the user profile), not an OS credential vault (DPAPI/Windows Credential Locker). Treat this the same as any other locally-readable config file — it is not protected against another local process or user reading it.                                                                |




## Runtime / hardware

- **Parallels / VMs without a GPU:** falls back to `*-generic-cpu` Foundry catalog ids when GPU/WebGPU load fails. On a display-less guest, Settings and `/v1/info` correctly report `CPUExecutionProvider`, CPU fallback, and no GPU.
- **Foundry model ids:** chat completions need the versioned catalog id (for example `Phi-4-mini-instruct-generic-cpu:5`), not the bare alias (`Phi-4-mini-instruct`) — the bare alias returns "Model not found" from the `multi` engine. `foundry model info <alias>` resolves the current versioned id.
- **Tool calling on** `gemma-4-e2b-it`**:** `/v1/info` reports tools unsupported for this catalog id. Foundry Local's own packaged chat template for `gemma-4-e2b-it` returns HTTP 500 during the tool probe (a Jinja2 `NoneType` error reading `function.name`) — this is a bug in Foundry Local's shipped template, not OpenJarvis code. Avoid that catalog id for tool-using agents until Foundry ships a fix.
- **Tool-calling probe:** `check_tool_calling()` in `[foundry_local.py](../../src/openjarvis/engine/foundry_local.py)` uses `max_tokens: 512` and `tool_choice: "required"` so reasoning models and models that would otherwise decline a trivial no-op prompt are measured correctly. If a model still reports unsupported, check whether it was truncated before completing the call versus genuinely lacking the capability — the `reason` field on `/v1/info`'s `tool_calling` object distinguishes the two.
- **Tool-activity cards and** `native_react`**:** verified end-to-end against the real `/v1/chat/completions` streaming path — a calculator-requiring prompt produces `event: tool_call_start` → `event: tool_call_end` (with `tool`, JSON-text `arguments`, `success`, `result`) → the final content chunk, in that order, and `ChatPage.xaml.cs`'s `ApplySse()` renders them.
- **Backend startup diagnostics can throw a decode error:** on at least one ARM64 host, probing Foundry Local's CLI output for status during `jarvis serve` startup hit `UnicodeDecodeError: 'charmap' codec can't decode byte ...` in a subprocess-output reader thread (Windows' default `cp1252` decode choking on a non-ASCII byte in Foundry's own CLI output). It is caught and degrades to `"execution_provider": "unknown"` rather than crashing the server, but the underlying subprocess capture should be fixed to decode as UTF-8 with replacement instead of the platform default codepage.
- **Surface Laptop Ultra acceleration evidence:** not yet collected. Everything above was run on a display-less ARM64 VM (no GPU/NPU) as a stand-in; the GPU/NPU execution-provider rows in the performance table need to be filled in on the actual device before this is considered verified for Ultra.
- **RAM:** `Phi-4-mini-instruct-generic-cpu` (~4.8 GB) is the documented default and needs roughly 10 GB of system RAM headroom to load and run comfortably alongside the WinUI shell and Foundry daemon; smaller devices should fall back to `qwen3-0.6b-generic-cpu` (~600 MB).
- **Unsigned installer:** CI and local Burn/MSI builds are unsigned — there is no code-signing cert configured for the `winui-arm64` workflow or the WiX projects. This needs an explicit decision (buy a cert, self-sign and accept the SmartScreen warning, or ship unsigned and document the click-through) before a wide release; it isn't something that can be resolved in code alone.
- **CI can go green on a broken installer build:** `publish-arm64.ps1` has several `Write-Warning; return`-style early-outs around the MSI/Burn build steps, and the GitHub Actions workflow uploads the MSI/bundle artifacts with `if-no-files-found: warn`. A silent installer-build failure would not currently fail the `winui-arm64` CI job. The workflow's only automated test coverage is the Python `tests/server`/`tests/engine` suite — there is no automated build-output check or UI/integration test of the WinUI app itself.
- **Foundry version:** Setup pins Foundry Local **0.11.0** (`cli-preview-0.11.0`).



## Updates and uninstall

- In-app update checks use `UpdateManifestUrl` in `appsettings.json`. A missing `appsettings.json`, an empty URL, or a failed/404 download all skip the check safely rather than erroring — confirmed in `UpdateChecker.cs`. `[windows/scripts/make-update-manifest.ps1](../../windows/scripts/make-update-manifest.ps1)` generates the manifest the checker expects; publishing an actual GitHub release with a Burn bundle and this manifest attached is still an outstanding step, since cutting a public release is a hard-to-reverse action that needs sign-off.
- Uninstall via Apps & Features removes the app. User data under `%USERPROFILE%\.openjarvis` and `%LOCALAPPDATA%\OpenJarvis` and any downloaded Foundry models are **not** removed automatically — `[windows/scripts/uninstall-cleanup.ps1](../../windows/scripts/uninstall-cleanup.ps1)` `-RemoveData` is a separate, manual step a user or admin runs afterward. It is not wired into the MSI/Burn uninstall sequence as a custom action, so nothing invokes it automatically.



## Outstanding decisions (not code fixes)

- **Installer signing:** see above — needs a cert decision, not an engineering fix.
- **Cutting the first GitHub release:** needed before update-checking can do anything other than silently skip.

