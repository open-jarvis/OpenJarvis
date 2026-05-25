# OpenJarvis Friday Task Backlog

## Phase 1: Stabilization

### 1. Default model
Goal:
- Set qwen3:0.6b as the default fast local model.
- Handle invalid or missing Ollama models safely.

Success:
- Friday starts with qwen3:0.6b by default.
- Invalid model shows Korean error message.
- User can still choose another installed model.

### 2. STT listen-once stabilization
Goal:
- Make local STT reliable in Friday.app mode.
- Use whisper-cli, rec, Korean language option.

Success:
- Mic button records once.
- Korean text is recognized.
- Missing recorder/model/whisper errors are clear.

### 3. App-mode status
Goal:
- Do not treat frontend 5173 as required in Tauri app mode.

Success:
- Status shows Friday.app app mode.
- 5173 off is marked normal.

### 4. Korean TTS
Goal:
- Improve robotic spoken responses.
- Add macOS say/Yuna voice support.

Success:
- TTS is local.
- User can choose voice/rate.
- TTS failure does not break text chat.

## Phase 2: Wake Listening

Goal:
- Add "프라이데이 호출 대기".
- Continue listening after one command.
- Avoid duplicate loops.

Success:
- Wake phrase detected.
- Command captured.
- Command sent.
- Returns to waiting state.

## Phase 3: Assistant Tools

Features:
- App opening
- Weather
- Notes
- Todos
- Calendar placeholder
- File search with allowlist

## Phase 4: Auto-start

Goal:
- Re-enable only needed services:
  - Ollama
  - Backend
  - Friday.app

Do not auto-start frontend 5173 in app mode.
