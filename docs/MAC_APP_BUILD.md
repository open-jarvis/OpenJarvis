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
then Tauri packages the macOS app.

The `.app` bundle is produced under:

```text
frontend/src-tauri/target/release/bundle/macos/
```

Tauri may also produce disk images or archives under sibling directories in
`frontend/src-tauri/target/release/bundle/`, depending on installed tooling and
target settings.

## Microphone Permission

Friday voice input and wake listening use the browser Web Speech API inside the
Tauri webview. macOS may prompt for microphone permission the first time voice
features are used. Grant microphone access to **OpenJarvis Friday** in:

```text
System Settings -> Privacy & Security -> Microphone
```

Speech synthesis for replies uses local browser `speechSynthesis`; no cloud TTS
service is required by the desktop wrapper.

## LaunchAgents

The desktop app does not replace the existing LaunchAgent setup. The existing
LaunchAgents can continue to start Ollama, the OpenJarvis backend, and the
frontend automatically.

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
