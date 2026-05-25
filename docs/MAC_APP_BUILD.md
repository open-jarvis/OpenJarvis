# macOS Desktop App Build

OpenJarvis already includes a Tauri desktop shell in `frontend/src-tauri`.
The app is named **OpenJarvis Friday** and wraps the existing local frontend.

## How It Runs

- Dev mode loads the Vite frontend from `http://localhost:5173`.
- Production builds package the static frontend from `frontend/dist`.
- The app talks to local services only, such as `127.0.0.1:8000` for the
  OpenJarvis backend and `127.0.0.1:11434` for Ollama.
- No cloud API keys are required by the desktop wrapper.

## Development

From the repository root:

```bash
cd frontend
npm run tauri -- dev
```

Tauri will run the configured `beforeDevCommand`, which starts the Vite
frontend with `npm run dev`, then opens the native app window.

If you already have the frontend running separately on port `5173`, the app
still uses the same local URL configured in `frontend/src-tauri/tauri.conf.json`.

## Production Build

From the repository root:

```bash
cd frontend
npm run tauri -- build
```

The production build runs `npm run build:tauri`, which creates `frontend/dist`,
then Tauri packages the macOS `.app` bundle.

For local personal builds, updater artifact generation is disabled and the
bundle target is limited to the `.app` bundle in
`frontend/src-tauri/tauri.conf.json`. This means `TAURI_SIGNING_PRIVATE_KEY` is
not required. Future release builds can re-enable updater artifacts and DMG
packaging by setting `bundle.createUpdaterArtifacts` back to `true`, restoring
the desired bundle targets, and providing the appropriate Tauri signing key
environment variables.

The `.app` bundle is produced under:

```text
frontend/src-tauri/target/release/bundle/macos/
```

Local builds do not create updater artifacts or DMGs by default.

To install the local app bundle after a successful build:

```bash
cp -R "src-tauri/target/release/bundle/macos/OpenJarvis Friday.app" /Applications/
```

## Microphone Permission

Friday voice input and wake listening use the browser Web Speech API inside the
Tauri webview. macOS may prompt for microphone permission the first time voice
features are used. Grant microphone access to **OpenJarvis Friday** in:

```text
System Settings -> Privacy & Security -> Microphone
```

Speech synthesis for replies uses local browser `speechSynthesis`; no cloud TTS
service is required by the desktop wrapper.

The macOS bundle includes `NSMicrophoneUsageDescription` so the app can appear
in the microphone privacy list after it requests access. If **OpenJarvis
Friday** does not appear in System Settings, launch the rebuilt app and click
the microphone button or enable Friday Listening once. The app explicitly calls
`navigator.mediaDevices.getUserMedia({ audio: true })` before starting voice
recognition so macOS can show the permission prompt.

If permission was denied, open:

```text
System Settings -> Privacy & Security -> Microphone -> OpenJarvis Friday
```

If the app says Web Speech recognition is unavailable in macOS app mode, the
current WKWebView does not expose browser speech recognition. The mic button can
fall back to the local backend listen-once STT endpoint when `[voice]` local STT
is configured. See [Local STT](LOCAL_STT.md).

## LaunchAgents

The desktop app does not replace the existing LaunchAgent setup. The existing
LaunchAgents can continue to start Ollama, the OpenJarvis backend, and the
frontend automatically.

For normal **OpenJarvis Friday.app** use, the frontend dev server on port 5173
is not required. App-mode status reports `frontend dev server (5173): 꺼짐, 앱
모드에서는 정상` when the bundled Tauri UI is being used.

In production app builds, the frontend assets are bundled into the app, but the
backend and Ollama are still local services. Make sure the backend is reachable
at `127.0.0.1:8000` before using chat features.

## Useful Checks

```bash
cd frontend
npm run build
npm run tauri -- info
```

Use `npm run tauri -- build` when you want the actual `.app` bundle.
