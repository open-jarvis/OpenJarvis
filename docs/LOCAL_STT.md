# Local STT for Friday App Mode

OpenJarvis keeps the existing browser voice path:

- Chrome/browser mode can use the free browser Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`) when the browser exposes it.
- If Web Speech is unavailable but `MediaRecorder` is available, the mic button records browser microphone audio and uploads it to `POST /v1/voice/transcribe`.
- Tauri macOS app mode tries Web Speech if available.
- If Web Speech is unavailable in the Tauri app, the mic button calls the local backend endpoint `POST /v1/voice/listen-once`.

Audio stays local. The listen-once endpoint records a short microphone clip on the Mac and sends it only to the configured local STT adapter. The upload endpoint accepts the browser-recorded clip and transcribes it with the configured local speech backend or local STT adapter.

In Settings > Speech, set **STT mode** to **Free Web Speech** for free web-mode voice input. Use Chrome or Safari for the best browser support.

## Configuration

Local backend STT is disabled by default. Add a `[voice]` section to `~/.openjarvis/config.toml`:

```toml
[voice]
stt_enabled = true
stt_engine = "whisper_cpp" # whisper_cpp, faster_whisper, custom, disabled
stt_model = "/Users/guru/.openjarvis/models/ggml-base.bin"
stt_language = "ko"
recording_seconds = 2
sample_rate = 16000
recorder_command = "/opt/homebrew/bin/rec"
whisper_cpp_path = "/opt/homebrew/bin/whisper-cli"
custom_command = ""
```

Supported engine names are:

- `web_speech`: frontend/browser Web Speech only.
- `local_backend`: local backend alias; routes to a configured local engine.
- `whisper_cpp`: runs a local whisper.cpp command.
- `faster_whisper`: uses the optional local `faster-whisper` Python backend.
- `custom`: runs `voice.custom_command`; use `{audio_path}` as a placeholder.
- `disabled`: safe default.

No cloud STT, cloud TTS, or cloud LLM API keys are required.

Friday local STT defaults to Korean (`ko`). For whisper.cpp this passes
`-l ko` to `whisper-cli`, which avoids Korean speech being translated or
misdetected as English. Set `stt_language = "auto"` to allow whisper.cpp
language auto-detection instead. Older configs may use `language = "ko"` in the
same `[voice]` section; `stt_language` takes precedence when both are set.

## Optional Engines

For whisper.cpp, build or install `whisper-cli`, download a local GGUF model, then set:

```toml
[voice]
stt_enabled = true
stt_engine = "whisper_cpp"
whisper_cpp_path = "/opt/whisper.cpp/build/bin/whisper-cli"
stt_model = "/models/ggml-base.bin"
stt_language = "ko"
recorder_command = "/opt/homebrew/bin/rec"
```

For faster-whisper, install the optional local speech dependencies:

```bash
uv sync --extra speech
```

Then set:

```toml
[voice]
stt_enabled = true
stt_engine = "faster_whisper"
stt_model = "base"
```

## Test The Endpoint

Start the backend, then run:

```bash
curl -X POST http://127.0.0.1:8000/v1/voice/listen-once
```

For browser-recorded audio:

```bash
curl -X POST http://127.0.0.1:8000/v1/voice/transcribe \
  -F file=@clip.webm \
  -F language=ko
```

Successful response:

```json
{
  "ok": true,
  "text": "오늘 일정 알려줘",
  "engine": "whisper_cpp",
  "mode": "local_backend",
  "message": ""
}
```

If STT is disabled or missing, the endpoint returns `ok: false` with a Korean setup message instead of crashing.

## Wake Listening

Browser wake listening uses Web Speech where available. In Settings > Speech,
turn on **Always-on wake** to start wake listening automatically when the app
opens. The wake button in the chat input can still start or stop listening
manually.

Default wake phrases are:

- `프라이데이`
- `헤이 프라이데이`
- `friday`
- `hey friday`

You can add custom comma-separated phrases in **Wake phrases**. For example:

```text
프라이데이, 자비스, 오케이 자비스
```

In browser mode, keep the page open and use Chrome or Safari. In Tauri macOS app
mode, Friday repeats the local `listen-once` STT endpoint while wake listening is
enabled, so local STT must be configured for continuous wake listening.
