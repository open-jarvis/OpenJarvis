# OpenClaw Local LLM Path

For fast OpenJarvis conversation on this Mac, use the lightweight local LLM chat path instead of the heavier `localdev` coding harness.

## Endpoints

- Primary local LLM server: `http://127.0.0.1:11434`
- Active model: `gemma4-agent:e4b`
- Lightweight chat wrapper: `scripts/openclaw-openjarvis-chat.sh`
- Legacy optional MLX server: `http://127.0.0.1:11435`

## Recommended Usage

- Fast chat-only conversation:
  `bash /Users/paulsunny/Documents/OpenJarvis/scripts/openclaw-openjarvis-chat.sh --fresh "OpenJarvis 구조를 짧게 설명해줘"`
- Actual repo work with file access and edits:
  `bash /Users/paulsunny/Documents/openclaw-workspace/scripts/openclaw_localdev_project_chat.sh openjarvis -- "<coding task>"`

The lightweight local LLM path is intentionally chat-only. It does not inspect files or execute tools.
