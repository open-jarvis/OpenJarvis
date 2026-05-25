# Codex Implementation Rules for OpenJarvis Friday

Codex is the implementer for this project.

## Project Context

OpenJarvis Friday is a local-first Korean assistant running on macOS.

Runtime:
- Tauri app: OpenJarvis Friday.app
- Backend: 127.0.0.1:8000
- Ollama: 127.0.0.1:11434
- Local STT: whisper-cli
- Recorder: sox/rec
- Main config: ~/.openjarvis/config.toml

## Hard Rules

- Preserve local-first behavior.
- Do not add cloud APIs.
- Do not add API keys.
- Do not remove browser Web Speech support.
- Do not break Tauri app mode.
- Do not break local STT.
- Do not make broad refactors unless explicitly asked.
- Do not execute arbitrary shell commands from user input.
- Use allowlists for app launching and website opening.
- Never use shell=True for subprocess calls.
- Before editing, list exact files you plan to modify.
- After editing, show changed files and test results.

## Preferred Workflow

For every task:

1. Restate the goal briefly.
2. List files to modify.
3. Make the smallest safe change.
4. Run focused tests.
5. Run build if frontend/Tauri changed.
6. Show:
   - changed files
   - test results
   - build results
   - remaining issues

## Commands

Backend run:
cd /Users/guru/OpenJarvis
uv run jarvis serve --port 8000

Frontend/Tauri build:
cd /Users/guru/OpenJarvis/frontend
npm run tauri -- build

Install app:
rm -rf "/Applications/OpenJarvis Friday.app"
ditto "src-tauri/target/release/bundle/macos/OpenJarvis Friday.app" "/Applications/OpenJarvis Friday.app"
xattr -dr com.apple.quarantine "/Applications/OpenJarvis Friday.app" 2>/dev/null || true

## Current Local STT Config

Expected config in ~/.openjarvis/config.toml:

[voice]
stt_enabled = true
stt_engine = "whisper_cpp"
recording_seconds = 2
sample_rate = 16000
whisper_cpp_path = "/opt/homebrew/bin/whisper-cli"
stt_model = "/Users/guru/.openjarvis/models/ggml-base.bin"
recorder_command = "/opt/homebrew/bin/rec"
stt_language = "ko"
language = "ko"

## Current Priority Tasks

1. Set qwen3:0.6b as default fast model.
2. Stabilize STT listen-once.
3. Fix app-mode status reporting.
4. Improve Korean TTS.
5. Fix wake listening loop so it continues after one command.
6. Expand assistant tools.
7. Restore safe auto-start.
