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
TTS rate: 175
TTS max length: 400
```

Good Korean speech rates are usually around `170` to `185`.

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
  -d '{"text":"안녕하세요. 프라이데이입니다.","voice":"Yuna","rate":175}'
```

Stop current speech:

```bash
curl -X POST http://127.0.0.1:8000/v1/voice/speak \
  -H 'Content-Type: application/json' \
  -d '{"stop":true}'
```

## Privacy

The macOS `say` backend runs locally through `/usr/bin/say`. Friday strips code
blocks, raw URLs, and internal debug-like metadata before speaking. Text chat
still works even if TTS fails.
