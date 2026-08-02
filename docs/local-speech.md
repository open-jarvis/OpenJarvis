# Local JARVIS speech input

The final Windows runtime transcribes microphone recordings locally with
Faster Whisper. The `base` model runs on CPU with `int8` compute, leaving the
GPU available for the Chatterbox text-to-speech voice. Audio is not sent to a
cloud transcription provider.

Models are kept under `%OPENJARVIS_HOME%\speech\models`. The final launcher
passes that path to Faster Whisper and warms the model before the server reports
itself as ready, so an installation problem cannot silently leave an enabled
but non-working microphone button.

## Install or repair

From PowerShell in the repository:

```powershell
$runtimeRoot = (Resolve-Path ..\openjarvis-runtime).Path
.\scripts\windows\setup-local-speech.ps1 `
  -RuntimeRoot $runtimeRoot `
  -Warmup
```

The script uses only the repository `.venv`, installs the pinned local STT
dependencies, checks the environment, and optionally downloads and loads the
model. It does not change global Python, PATH, CUDA, or system settings.

## Runtime behavior

Pressing the microphone button requests microphone permission from the Windows
WebView, records locally, and posts the recording to the local OpenJarvis server
on `127.0.0.1`. The server returns the transcript to the chat composer. In
**Talk** mode JARVIS also reads answers aloud; in **Text** mode transcription
still works, but responses are deliberately silent.

The health endpoint reports STT and TTS separately:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/v1/speech/health
```

Both `stt_available` and `tts_available` should be `true`. If the WebView asks
for microphone access, allow it for the native OpenJarvis app.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\speech `
  tests\server\test_speech_routes.py `
  tests\server\test_final_runtime.py
```

The reproducible dependency input is
`configs/speech/requirements-windows.txt`.
