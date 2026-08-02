# Local JARVIS voice

The final Windows runtime uses a local, German text-to-speech stack. The
primary engine is Chatterbox Multilingual V3 on CUDA. Piper runs on CPU and is
the automatic fallback. The main OpenJarvis environment does not import either
engine: a persistent worker in `.venv-voice` owns the model and communicates
with the server through a JSON-lines standard-I/O pipe. No extra listener port,
cloud API, API key, or global PATH/CUDA/Rust change is required.

The selected profile is stored under
`%OPENJARVIS_HOME%\voice\voice-config.json`. Synthesized sentence chunks are
cached by text and complete voice settings under
`%OPENJARVIS_HOME%\voice\cache`. Auditions are stored under
`%OPENJARVIS_HOME%\voice\auditions`. These runtime files are not committed.

## Install or repair

From PowerShell in the repository:

```powershell
$runtimeRoot = (Resolve-Path ..\openjarvis-runtime).Path
.\scripts\windows\setup-local-voice.ps1 `
  -RuntimeRoot $runtimeRoot `
  -Warmup
```

The script creates only `.venv-voice`, installs the pinned dependencies, and
downloads `de_DE-thorsten-high` to the supplied runtime root. Its Piper model
card identifies the training dataset as CC0. Chatterbox uses its built-in
conditioning only: arbitrary reference audio is rejected by the config loader,
so this integration does not clone a real person.

## Audition and select

Start JARVIS with the existing final launcher, open the JARVIS menu, and select
**Einstellungen**. The embedded **Stimmenauswahl** can generate all five
samples. Each numbered profile shows its backend, pitch, tempo, emotion
setting, deterministic seed, and an individual WAV player. **Als
JARVIS-Stimme verwenden** persists the selection.

The comparison text is fixed:

> Guten Abend, Deaa. Alle Systeme sind betriebsbereit. Ich habe deine aktuellen
> Aufgaben analysiert und bin bereit, sie auszuführen.

The chat **Read answer** action requests one sentence at a time. While the
current sentence plays, the next is synthesized. Starting push-to-talk calls
`stop()` immediately (barge-in). Playback emits these WebView events for mouth
animation consumers:

- `openjarvis:audio-start`
- `openjarvis:audio-level` with `detail.level` from 0 to 1
- `openjarvis:audio-end`

The start and end events describe the complete utterance, not every sentence.
`audio-start` is emitted by the real `HTMLAudioElement.onplay` callback and
includes `detail.requestToPlaybackMs`. Levels are sampled from the Web Audio
analyser and reset to zero when playback ends or is interrupted.

## Profiles and deterministic output

| Number | ID | Engine | Seed | Character |
| --- | --- | --- | ---: | --- |
| 1 | `jarvis-deep-calm` | Chatterbox | 104729 | deep and calm; default |
| 2 | `jarvis-deep-clear` | Chatterbox | 130363 | deep with clearer articulation |
| 3 | `jarvis-sovereign` | Chatterbox | 155921 | deepest and deliberately measured |
| 4 | `jarvis-balanced` | Chatterbox | 180503 | more natural pitch |
| 5 | `jarvis-piper-fast` | Piper | 0 | fast CPU fallback |

The seed is part of the cache key. A cached fallback never replaces a future
Chatterbox attempt, so a transient CUDA or model failure cannot permanently
poison the primary result. Output is normalized safely with 1 dB peak
headroom; benchmark analysis rejects clipped PCM samples.

## Recovery behavior

Worker health checks are bounded to 20 seconds, Chatterbox synthesis to 120
seconds, and Piper recovery to 60 seconds. On a primary timeout OpenJarvis
terminates only the worker process it started and makes exactly one fresh Piper
attempt. Piper failure is returned to the caller without an unbounded retry
loop. The final runtime can warm both models before reporting `ready`.

## Reproduce the benchmark

```powershell
$runtimeRoot = (Resolve-Path ..\openjarvis-runtime).Path
.\.venv\Scripts\python.exe .\scripts\benchmark_local_voice.py `
  --runtime-root $runtimeRoot
```

The report is written to `%OPENJARVIS_HOME%\voice\benchmark.json`. It records
cold first-sentence latency, full-phrase generation, a warm cache hit, CPU and
peak Torch VRAM measurements, and ten consecutive uncached outputs.

The recorded benchmark on an RTX 3070 produced a 29.923 s cold first sentence,
a 13.790 s full comparison phrase, and a 12.46 ms warm cache hit. All ten
uncached stability outputs used Chatterbox without fallback or clipping; their
wall times ranged from 6.910 s to 10.500 s. Peak Torch allocation was about
3.28 GB. The system-wide GPU-memory field can include unrelated desktop or
inference processes; use the Torch figure for this worker's allocation.

`time_to_first_audio_ready` stops when the first complete sentence WAV is
available. Actual perceived UI latency is separately recorded by the
`openjarvis:audio-start` event as `requestToPlaybackMs`.

## Start and verification

The installed desktop runtime starts through:

```text
C:\Users\<you>\Documents\JARVIS\Start-OpenJarvis.cmd
```

Useful verification commands from the repository are:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\speech tests\server\test_speech_routes.py tests\server\test_final_runtime.py
.\.venv\Scripts\python.exe -m ruff check src\openjarvis\speech tests\speech scripts\benchmark_local_voice.py
Set-Location frontend
npm test -- --run
npm run build
```

## Pinned primary packages

- Python 3.11.9 in `.venv-voice`
- Torch/Torchaudio 2.6.0+cu124
- Chatterbox source commit `5de7a54aa4e5e2baadb0182dde554908b48b85c2`
- Piper TTS 1.6.0
- Resemble PerTh 1.0.1 with `setuptools 80.9.0` compatibility pin

The full reproducible input is `configs/voice/requirements-windows.txt`.

Microphone transcription is a separate local Faster Whisper component. Its
installation and verification are documented in `docs/local-speech.md`.
