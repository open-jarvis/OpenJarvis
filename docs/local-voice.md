# Local JARVIS voice

JARVIS implements one three-tier German speech pipeline:

1. ElevenLabs (`eleven_flash_v2_5`, `language_code="de"`) when a key and a
   real selected voice ID are configured.
2. Chatterbox Multilingual v3 (`language_id="de"`, `t3_model="v3"`) on CUDA.
3. Piper `de_DE-thorsten-high` as the final CPU emergency voice.

Kokoro is not used for German. Browser `SpeechRecognition` and
`window.speechSynthesis` are not automatic fallback paths.

The configuration is stored below
`%OPENJARVIS_HOME%\voice\voice-config.json`. Audio chunks and auditions have
separate caches. The current schema is `voice-v11-elevenlabs-hybrid`.

## Profiles and fallback chains

| Profile | Chain |
| --- | --- |
| `jarvis-elevenlabs` | ElevenLabs → Chatterbox → Piper |
| Chatterbox profiles | Chatterbox → Piper |
| `jarvis-piper-fast` | Piper only |

The frontend shows the provider that actually produced each chunk. A failed
provider never causes an already played chunk to be repeated. A chunk that all
providers fail to synthesize is counted and shown as skipped; the turn is not
reported as a normal successful playback completion.

## ElevenLabs setup and secrets

The voice ID is never invented. In the voice settings, load the voices exposed
by the authenticated ElevenLabs account, select one, validate it, and save the
ID. Until both key and ID exist the UI reports that ElevenLabs is not set up and
the worker starts with the local fallback.

In the desktop app, save `ELEVENLABS_API_KEY` through the secure key input. The
Tauri keyring is preferred; an environment variable with the same name is the
manual fallback. The backend APIs return only key-present status and voice
metadata, never the key. Saving or removing a key restarts the isolated voice
worker so it inherits the updated environment.

Only the text chosen for spoken output is sent to ElevenLabs. Microphone audio,
screenshots, files, clipboard data, tool arguments and unrelated memory are not
part of the synthesis request.

## Cost controls and cache

- `monthly_char_limit` defaults to 100,000 characters.
- `per_response_char_limit` defaults to 4,000 characters.
- The local monthly counter is an estimate stored in
  `%OPENJARVIS_HOME%\voice\elevenlabs-usage.json`.
- Reservation is made before the paid request under a process- and
  thread-safe file lock, so concurrent chunks cannot pass the configured limit.
- Cache hits do not reserve or increment character usage.
- Reaching a limit is reported and switches only the pending chunk to the local
  chain.

Also configure a credit limit for the API key in the ElevenLabs dashboard. The
local counter is a safety estimate, not provider billing authority.

No ElevenLabs synthesis request is required during installation.

## Chatterbox and Piper

The Windows requirements file pins Chatterbox to the repository's known
official commit. Reference WAVs are accepted only when their deployed SHA-256
matches the repository manifest and allowlist. The setup script verifies both
source and deployed files. Chatterbox explicitly selects CUDA and multilingual
v3. Piper remains labelled as the synthetic emergency provider.

The setup script is intentionally separate from the application:

```powershell
$runtimeRoot = (Resolve-Path ..\openjarvis-runtime).Path
.\scripts\windows\setup-local-voice.ps1 -RuntimeRoot $runtimeRoot -Warmup
```

It creates the voice environment, installs the pinned requirements, verifies
and deploys references, prepares Piper, and optionally warms Chatterbox. Do not
run it while merely reviewing the implementation.

## Turn-taking and interruption

Local STT owns exactly one `MediaStream` per recording. The level analyser uses
that stream. A stable 50 ms timer first calibrates the noise floor, then
requires at least 180 ms of real speech, and only afterwards permits the 900 ms
silence window to end the turn. Manual stop, silence stop and the maximum
recording timer share a single completion guard.

Stop and barge-in cancel the active HTTP request where possible, terminate a
blocked local worker request, discard prefetched chunks, stop audio playback and
its analyser, invalidate callbacks, and stop the processing tone. The text
answer is independent of TTS and remains usable after a speech failure.

Playback events now drive the abstract star/core visualization; there is no
portrait, mouth layer or avatar animation.

## Manual verification

The implementation has not been installed, built, warmed or exercised as part
of this change. Follow [the manual JARVIS runbook](jarvis-manual-verification.md)
after installing the declared dependencies and configuring your own key and
voice ID.

Microphone transcription is documented separately in
[`local-speech.md`](local-speech.md).
