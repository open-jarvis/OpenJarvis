# Local TTS for Friday

Friday can speak replies without cloud TTS.

## Modes

- Browser mode can keep using local browser `speechSynthesis`.
- Tauri app mode can use the local macOS `/usr/bin/say` backend.
- TTS can also be disabled from settings.

No OpenAI, ElevenLabs, Google Cloud, Azure, or other cloud TTS API is required.

## Recommended macOS Settings

In Friday settings:

```text
TTS mode: macos_say
macOS voice: Yuna
TTS rate: 165
TTS max length: 400
TTS pause: 250ms
Naturalize Korean speech: true
```

Good Korean speech rates are usually around `165` to `185`. Friday defaults to
`165` with a short pause between spoken chunks to make Korean replies less
robotic.

In `~/.openjarvis/config.toml`:

```toml
[voice]
tts_enabled = true
tts_mode = "macos_say"
tts_voice = "Yuna"
tts_rate = 165
tts_max_chars = 400
tts_pause_ms = 250
tts_naturalize = true
```

## Check Installed Voices

Run:

```bash
say -v '?'
```

Look for a Korean voice such as `Yuna`. If it is missing, install Korean system
voices in macOS:

1. Open System Settings.
2. Go to Accessibility.
3. Open Spoken Content.
4. Choose System Voice.
5. Manage Voices and install a Korean voice.

## API Test

```bash
curl -X POST http://127.0.0.1:8000/v1/voice/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"안녕하세요. 프라이데이입니다.","voice":"Yuna","rate":165,"pause_ms":250}'
```

Stop current speech:

```bash
curl -X POST http://127.0.0.1:8000/v1/voice/speak \
  -H 'Content-Type: application/json' \
  -d '{"stop":true}'
```

## Privacy

The macOS `say` backend runs locally through `/usr/bin/say`. Friday strips code
blocks, raw URLs, markdown tables, emoji, HTTP/debug output, stack traces, and
token/cost metadata before speaking. Text chat still works even if TTS fails.

This is still macOS system TTS, not a neural voice model. A future local-only
upgrade can add a local neural Korean TTS engine behind the same router without
using cloud TTS APIs.
