# Free offline Jarvis voice — Windows

## Easiest Windows setup (separate from your existing Jarvis)

From the **repository root**, double-click **START_OFFLINE_JARVIS_WINDOWS.bat**.
This launches the official Windows source installer with your own GitHub fork
selected, installs local Ollama/Whisper/Piper components, configures a separate
install in `%LOCALAPPDATA%\OpenJarvis-Offline`, and opens a short speech test.
Run **OPEN_OFFLINE_JARVIS_AGAIN.bat** to start the installed version later.

**Windows prerequisite:** Stanford OpenJarvis compiles a Rust extension with
Microsoft's C++ Build Tools. If the setup stops to request the free Microsoft
Visual Studio Build Tools / "Desktop development with C++" workload, approve
that official installer and run START_OFFLINE_JARVIS_WINDOWS.bat again.
This is a large download; the launcher does not silently install it.

This setup does **not** replace your existing Jarvis app or upload audio
recordings to GitHub. It doesn't activate the optional voice clone until
you supply a clean consented WAV sample and install Chatterbox locally.
The initial voice test is the standard free British Piper voice.

The installer requires internet for its first-time downloads but uses local
speech and a local AI engine afterwards. Your system hardware will affect
performance. Windows microphone and voice similarity have not been verified
until you test the installer on that computer.

---


This is an optional, local-only extension of your fork of Stanford OpenJarvis.
It does not modify the original Stanford project or your older Python Jarvis
application. When you select the jarvis_local backend, voice fallback is
restricted to **local Piper or Kokoro**, not paid voice APIs.

## What it does

- **Works first:** a free British Piper speech voice speaks Jarvis responses offline.
- **Optional next:** Chatterbox Nano can use a voice sample you have permission to reproduce.
  It runs locally and produces speech resembling that sample; similarity is not guaranteed.
- **No exported ElevenLabs model:** a Voice ID alone is not a speech model.
- **No sample on GitHub:** keep your private reference WAV on your computer.
- AI reasoning and speech recognition need separate local model configuration.
  This change only provides offline text-to-speech.

## Quick start on Windows

1. Install **Python 3.11** and **uv** from https://docs.astral.sh/uv/
2. Download this feature branch as a separate folder, leaving your older Jarvis
   application untouched.
3. Open PowerShell in the project folder containing pyproject.toml and run:

       uv sync --extra voice

   For the source-based browser GUI, also install Node.js 22+ and run
   "uv run jarvis gui". The local Ollama AI backend may require first-time
   configuration; follow the official Windows guide:
   https://open-jarvis.github.io/OpenJarvis/getting-started/windows-native/

4. Double-click jarvis_voice_setup\01_Setup_Offline_Voice.bat.
   It installs Piper to a separate environment and downloads a British
   voice model to %USERPROFILE%\.openjarvis\voices\.
5. Double-click jarvis_voice_setup\02_Start_Offline_Voice.bat. Leave it open.
   Open http://127.0.0.1:4701/health and check for "ready": true.
6. Double-click jarvis_voice_setup\05_Configure_OpenJarvis.bat.
   This backs up your settings and enables jarvis_local without changing your
   selected AI model or tools.
7. Double-click jarvis_voice_setup\06_Start_OpenJarvis_Voice.bat.
   Type a message or press Enter to use your microphone (a working speech
   recognition backend is needed to hear you).

**Test speech independently** by running this PowerShell command while the
local voice service is open:

    Invoke-WebRequest -Uri http://127.0.0.1:4701/speak -Method Post -ContentType application/json -Body '{"text":"Good morning, sir. Jarvis is ready."}' -OutFile "$env:TEMP\jarvis_test.wav"

Then double-click the resulting WAV in your temp folder.

## Optional reference-matched local voice

Only use a recording you own or have permission to clone.

1. Put a clean WAV recording on your PC at
   %USERPROFILE%\.openjarvis\voices\jarvis_reference.wav.
   Reference audio must **not** be uploaded to this public repository.
2. Stop the ordinary offline voice service.
3. Run jarvis_voice_setup\03_Install_Cloned_Voice.bat.
4. Start jarvis_voice_setup\04_Start_Cloned_Voice.bat instead of step 5.

Chatterbox may require substantial resources and large model downloads.
If cloning errors, the service uses Piper automatically. Chatterbox is
archived research software, so it is optional rather than a reliability
dependency.

## Technical notes

- GET http://127.0.0.1:4701/health
- POST http://127.0.0.1:4701/speak with JSON containing text; returns WAV.
- Service listens only on 127.0.0.1.
- OpenJarvis TTS backend: jarvis_local; voice_id: jarvis-local.
- No ElevenLabs API key is needed for this speech backend.
- The ElevenLabs hosted conversational agent still relies on its service.
- Windows execution and voice similarity must be verified on your PC.
