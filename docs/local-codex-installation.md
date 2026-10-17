# Local OpenJarvis with native Codex

This fork is independent of the former voice-satellite deployment repository.
Its integration branch is `develop`; changes are reviewed before activation.
The official base is `091068cb94804f4dfbe57af2114adba89245612b`.

## Scope

The native CloudEngine sends Responses requests directly to ChatGPT. No CLI
inference bridge, proxy backend or old satellite process is used. ChatGPT
inference remains remote; local Whisper and Kokoro keep audio on the computer.
The interface's microphone button performs dictation. The optional desktop wake helper opens the native window on “Hey Jarvis”;
chat recording still uses the interface microphone button.

The transport correction handles ChatGPT SSE, assistant history and native
model routing. The configured Codex model remains first in the browser model
list and is accepted at startup even when the built-in catalog is outdated.

## Local account authentication (explicit opt-in)

Keep an existing `codex login` session. The following environment variables
contain configuration, not credentials:

```sh
export OPENAI_CODEX_USE_LOCAL_AUTH=1
export OPENAI_CODEX_BASE_URL=https://chatgpt.com/backend-api/codex
```

The engine reads the user's private Codex auth cache into memory for each
request. It does not copy credentials into this repository, configuration,
command arguments or logs. An explicit `OPENAI_CODEX_API_KEY` retains precedence
for existing users; unset it to use local account authentication.

Within two minutes of token expiry, the engine asks `codex app-server` to renew
its managed ChatGPT session with `account/read` and `refreshToken=true`. Codex
owns token rotation and cache writes. The helper sends initialization and
account methods only; it creates no agent thread and runs no model or tool.
The process has a 45-second deadline and is terminated/reaped afterward.
Refresh failures are sanitized and backed off for 60 seconds. Revoked sessions
or revoked access can still require the user to sign in again; no unattended
software can guarantee permanent authentication.

Reference: https://learn.chatgpt.com/docs/app-server#auth-endpoints

## Installation and startup

Use the official README/manual installation procedure in this checkout and its
own Python environment. The optional `desktop` and `voice` extras enable local
dictation and speech. CPU-only PyTorch avoids installing CUDA for Kokoro.

Keep private runtime configuration outside Git under
`~/.local/share/openjarvis-official-trial/config.toml`. On the tested notebook,
the configured speech backends are Faster-Whisper small/CPU/int8 and Kokoro
pm_alex/0.90/CPU, in Brazilian Portuguese. These are application configuration,
not source overrides.

Build the project's native Tauri application with the existing frontend and
Rust toolchains (Linux requires the official GTK/WebKit development libraries):

```sh
cd frontend
npm run tauri -- build --no-bundle
cd ..
```

After review and merge, run using this checkout's Python:

```sh
.venv/bin/python scripts/launch-local-codex.py
```

The launcher starts the official daemon with explicit cloud/model/simple-agent
arguments, binds only `127.0.0.1:8001`, waits for readiness, then opens the native Tauri desktop window.
It never opens a browser tab. The binary must already be built; the launcher
fails before starting a daemon when the desktop binary is missing.
It reuses an already-ready server and does not replace another process. It
does not create a systemd service or enable login startup.

The launcher opts into `OPENJARVIS_DESKTOP_ATTACH_PORT=8001`. In this mode,
the desktop verifies the loopback server's health and identity, and uses that
port for its native API client. It does not start Ollama, clone a backend, sync
packages, or change the managed desktop's inference credentials. Invalid ports
and unavailable servers fail closed. Closing the desktop does not terminate the
independently managed daemon. Reopening focuses the existing native window.
Without this explicit option, upstream desktop startup behavior is preserved.
In attached mode, microphone access is limited to the bundled main window and
recording begins only when its microphone button is clicked; camera, screen
capture and external-page permission requests are denied.

On Linux this is the official main desktop window. The upstream floating overlay
implementation is macOS-only; this change does not claim a Linux floating panel
with macOS overlay styling. Use the application launcher or the command above.
Do not apply upstream desktop auto-updates over this reviewed local build without
reviewing whether they preserve the local integration.

Stop only this installation:

```sh
OPENJARVIS_HOME="$HOME/.local/share/openjarvis-official-trial" .venv/bin/jarvis stop
```

Do not reactivate the old satellite or alter the pinned server/voice checkouts.

## Evidence and limits

Run the network-free contract tests with the existing installed dependencies:

```sh
PYTHONPATH=src .venv/bin/python -B tests/native_codex_contract.py
```

The tests cover Responses transport/history/errors, browser model ordering,
startup selection, private-cache rotation, refresh error backoff, helper process
cleanup, credential destination restrictions and launcher behavior. A live
isolated check also renewed the managed Codex session and obtained a correct
synthetic response through the native engine. No private transcript or audio is
part of these tests.

Chat and browser microphone/response playback were validated with the previous
reviewed transport correction. The native desktop handoff requires its own post-merge user validation; browser
voice tests do not establish desktop microphone permissions or audible playback.
The simple agent provides chat, not an autonomous executor or automatic access
to the user's Codex app plugins. Optional external connectors need their own
configuration and authorization. Reboot/login persistence is not claimed.


## Voice activation of the Linux desktop

The upstream release has no wake-word listener. This fork adds an isolated
wake-to-window helper, not the old satellite: no old checkout, environment,
service, VPS, or agent bridge is involved. It uses stock openWakeWord 0.5.1,
`hey_jarvis`, threshold 0.45, ONNX/CPU, 16 kHz/1280 samples and two-second warm-up.
Ambient frames exist only in memory and are never saved, logged or sent out.

After review/merge, install the optional detector into **this** environment:

```sh
uv pip install --python .venv/bin/python 'scipy>=1.3,<2' 'scikit-learn>=1,<2' 'tqdm>=4,<5' 'onnxruntime>=1.10,<2'
uv pip install --python .venv/bin/python --no-deps 'openwakeword==0.5.1'
```

The explicit `--no-deps` applies only to openWakeWord: its Linux metadata requires
TFLite, which has no Python 3.12 wheel, while this helper explicitly uses ONNX.
The preceding command supplies the required ONNX dependencies. The 0.5.1 wheel
contains the stock model assets. No TFLite stub, CUDA or training dependency is
installed. No model is downloaded by the running listener. Validate the model
import/load after installation before enabling voice activation.

Normal launch opens the main window. Closing it hides it to the tray and arms
the wake listener. Saying “Hey Jarvis” closes the wake microphone first, then
shows/focuses the existing window. Use its microphone button for dictation.
While the window is visible the wake helper is stopped. Response playback also
waits for wake suspension, including if the window is hidden during playback.
The tray's Quit action stops and reaps the helper before exiting.

To launch directly into listening mode after activation:

```sh
.venv/bin/python scripts/launch-local-codex.py --listen
```

No login startup is installed by this patch. An application/autostart entry may
call this command after explicit activation approval. A detector failure opens
the chat with a sanitized notice rather than retrying continuously. Hardware
wake accuracy and desktop microphone/playback remain pending real-user testing.

Additional hardware-free tests:

```sh
.venv/bin/python -B tests/native_wake_contract.py
cd frontend
npx vitest run src/lib/tts.test.ts src/lib/desktop-wake.test.ts
cd src-tauri
cargo test --release --locked --lib
```
