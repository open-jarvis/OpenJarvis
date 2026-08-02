# Local JARVIS voice

The final Windows runtime uses a fully local German text-to-speech stack.
Chatterbox Multilingual V3 runs on CUDA as the natural primary engine; Piper
runs on CPU only as the bounded emergency fallback. A persistent worker in
`.venv-voice` owns both engines and communicates with the server through a
JSON-lines standard-I/O pipe. No cloud API, API key, or extra listener port is
used.

The selected profile is stored under
`%OPENJARVIS_HOME%\voice\voice-config.json`. Synthesized chunks are cached under
`%OPENJARVIS_HOME%\voice\cache`, and audition files under
`%OPENJARVIS_HOME%\voice\auditions`.

## Natural profile design

The three Chatterbox choices use three distinct, machine-generated reference
timbres. They are preset outputs from
`Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`, not recordings of a real person. Their
provenance and SHA-256 allowlist are committed in
`configs/voice/references/manifest.json`. The setup script verifies every hash
before deploying the files to `%OPENJARVIS_HOME%\voice\models\references`.

This fixes the previous profile design: all former Chatterbox choices used the
same built-in speaker and then changed pitch and tempo with resampling. That
made the choices sound nearly identical and introduced robotic artifacts. The
current profiles switch the model's speaker conditioning and do not pitch-shift
or time-stretch generated speech.

| Number | ID | Engine | Character |
| --- | --- | --- | --- |
| 1 | `jarvis-deep-calm` | Chatterbox | deep and calm; default |
| 2 | `jarvis-deep-clear` | Chatterbox | clear German articulation |
| 3 | `jarvis-balanced` | Chatterbox | balanced, natural speaking position |
| 4 | `jarvis-piper-fast` | Piper | synthetic CPU emergency voice |

An existing `jarvis-sovereign` selection migrates automatically to
`jarvis-deep-calm`. The `voice_reference` config field still rejects arbitrary
paths, so users cannot turn the feature into unrestricted voice cloning.

## Install or repair

From PowerShell in the repository:

```powershell
$runtimeRoot = (Resolve-Path ..\openjarvis-runtime).Path
.\scripts\windows\setup-local-voice.ps1 `
  -RuntimeRoot $runtimeRoot `
  -Warmup
```

The script creates only `.venv-voice`, installs pinned dependencies, downloads
`de_DE-thorsten-high`, verifies and deploys the three synthetic references, and
optionally warms Chatterbox.

## Audition and select

Start JARVIS with the final launcher, open **Einstellungen**, and use
**Stimmenauswahl**. Generate the four samples once, compare them in the embedded
WAV players, and choose **Als JARVIS-Stimme verwenden**. Auditions from an older
voice schema are treated as stale and never shown as current samples.

The fixed comparison text is:

> Guten Abend, Deaa. Alle Systeme sind betriebsbereit. Ich habe deine aktuellen
> Aufgaben analysiert und bin bereit, sie auszuführen.

## Latency and recovery

The frontend splits speech at sentence, clause, or word boundaries with a hard
limit of 110 characters. It starts playing the first completed chunk while
prefetching the next. This prevents a long sentence from blocking all audio.
Push-to-talk still interrupts playback immediately.

Worker health checks are bounded to 20 seconds, each primary synthesis request
to 28 seconds, and the single Piper recovery attempt to 15 seconds. Model
warmup has its own 90-second startup deadline. A timed-out worker is terminated
and restarted; retries are never unbounded. The interactive final runtime uses
medium reasoning effort to avoid spending answer latency on an `xhigh` pass.

Reference-conditioning measurements on the target RTX 3070 produced three
different, ASR-verified German voices in roughly 9.5 to 10.0 seconds for a
short uncached phrase after model loading. Warm cache hits remain effectively
immediate. Chatterbox peak allocation is about 3.4 GB of VRAM.

Playback emits these WebView events for avatar mouth animation:

- `openjarvis:audio-start`
- `openjarvis:audio-level` with `detail.level` from 0 to 1
- `openjarvis:audio-end`

`audio-start` comes from the real `HTMLAudioElement.onplay` callback and
includes `detail.requestToPlaybackMs`.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\speech tests\server\test_speech_routes.py tests\server\test_final_runtime.py
.\.venv\Scripts\python.exe -m ruff check src\openjarvis\speech tests\speech scripts\benchmark_local_voice.py
Set-Location frontend
npm test -- --run
npm run build
```

Pinned primary packages remain Python 3.11.9, Torch/Torchaudio 2.6.0+cu124,
Chatterbox source commit `5de7a54aa4e5e2baadb0182dde554908b48b85c2`,
and Piper TTS 1.6.0. Qwen is not installed in the runtime; only its three small,
pre-generated synthetic reference WAV files are deployed.

Microphone transcription is the separate local Faster Whisper component
documented in `docs/local-speech.md`.
