# Friday TTS Options

Friday keeps local-first TTS by default. `macos_say` remains the fallback and no
API keys are stored in config or committed to the repo.

Supported modes:

- `macos_say`: local macOS system TTS.
- `piper`: local Piper TTS using your own installed binary and voice model.
- `gemini_tts`: optional Gemini 2.5 Flash Preview TTS using environment variables.
- `edge_tts`: optional Microsoft Edge neural TTS through the `edge-tts` package.
- `elevenlabs`: optional cloud TTS using environment variables.
- `disabled`: do not speak replies.

## Default Local Config

```toml
[voice]
tts_enabled = true
tts_mode = "macos_say"
tts_fallback_mode = "macos_say"
tts_voice = "Yuna"
tts_rate = 165
tts_max_chars = 400
tts_naturalize = true
```

## ElevenLabs

ElevenLabs can sound more natural, but it sends assistant response text to an
external service. The free plan has limited monthly credits and may change.

Set the API key only in your shell environment:

```bash
export ELEVENLABS_API_KEY="..."
```

Then configure a voice ID:

```toml
[voice]
tts_mode = "elevenlabs"
tts_fallback_mode = "macos_say"
elevenlabs_voice_id = "your_voice_id"
elevenlabs_model = "eleven_v3"
tts_max_chars = 400
tts_naturalize = true
```

If the key or voice ID is missing, Friday returns a Korean setup message and
falls back to local `macos_say`.

For the most human-like short assistant replies, use `eleven_v3`. For longer or
more stable narration, switch `elevenlabs_model` to `eleven_multilingual_v2`.

## Gemini 2.5 Flash Preview TTS

Gemini TTS can sound much more conversational than local system voices. It sends
assistant response text to Google's Gemini API.

For web mode, enter the key in **Settings > Speech > Gemini API key**. The key is
stored in this browser's local settings and is sent only when `TTS mode` is
`Gemini 2.5 Flash TTS`.

For app/server mode, you can also set one of these environment variables before
starting Friday:


```bash
export GEMINI_API_KEY="..."
# or
export GOOGLE_API_KEY="..."
```

Then configure:

```toml
[voice]
tts_mode = "gemini_tts"
tts_fallback_mode = "macos_say"
gemini_model = "gemini-2.5-flash-preview-tts"
gemini_voice = "Sulafat"
tts_max_chars = 400
tts_naturalize = true
```

If the API key is missing or the Gemini request fails, Friday falls back to
local `macos_say`.

## Edge TTS

Edge TTS uses the `edge-tts` Python package and sends assistant response text to
Microsoft's online neural TTS service. It does not require an API key.

Install the speech extra:

```bash
uv sync --extra speech
```

Then configure:

```toml
[voice]
tts_mode = "edge_tts"
tts_fallback_mode = "macos_say"
edge_voice = "ko-KR-SunHiNeural"
tts_max_chars = 400
tts_naturalize = true
```

Recommended Korean voices:

- `ko-KR-SunHiNeural`
- `ko-KR-InJoonNeural`

If `edge-tts` is missing or the request fails, Friday falls back to
local `macos_say`.

## Piper

Piper is local and free, but quality depends on the voice model. Friday does not
download Piper or voice models automatically.

Install Piper and a compatible local voice model, then configure:

```toml
[voice]
tts_mode = "piper"
tts_fallback_mode = "macos_say"
piper_path = "/opt/homebrew/bin/piper"
piper_model = "/Users/guru/.openjarvis/models/ko_KR-voice.onnx"
tts_max_chars = 400
tts_naturalize = true
```

If the Piper binary or model is missing, Friday falls back to `macos_say`.

## Text Cleanup

Before any provider receives text, Friday strips code blocks, raw URLs, markdown
tables, stack traces, HTTP/debug output, and token/cost metadata. It also limits
text length and can naturalize dense Korean weather replies.

## Test

```bash
curl -X POST http://127.0.0.1:8000/v1/voice/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"안녕하세요. 프라이데이입니다."}'
```

Text chat continues even if TTS fails.
