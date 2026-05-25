# Local STT for Friday App Mode

OpenJarvis keeps the existing browser voice path:

- Chrome/browser mode uses Web Speech (`SpeechRecognition` / `webkitSpeechRecognition`) when the browser exposes it.
- Tauri macOS app mode tries Web Speech if available.
- If Web Speech is unavailable in the Tauri app, the mic button calls the local backend endpoint `POST /v1/voice/listen-once`.

Audio stays local. The listen-once endpoint records a short microphone clip on the Mac and sends it only to the configured local STT adapter.

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

Browser wake listening still uses Web Speech where available. Continuous local wake listening in the Tauri app is intentionally not implemented yet; it should be added after listen-once local STT is stable.
