# Skill Stack Notes

Date: 2026-04-12

## Installed Codex Skills

### System Skills Already Present

- `imagegen`
- `openai-docs`
- `skill-creator`
- `skill-installer`

### Curated Installs from `openai/skills`

- `frontend-skill`
- `playwright`
- `security-best-practices`
- `speech`
- `transcribe`
- `screenshot`
- `doc`
- `gh-fix-ci`

Trust tier: high

Reason: official curated OpenAI skill packages with real `SKILL.md` layouts.

### Community Install

- `project-skill-audit` from `TerminalSkills/skills`

Trust tier: medium

Reason: verified real `SKILL.md` package from a public GitHub repo and useful for targeted project skill audits.

### Local Custom Skill

- `real-build-guard`

Trust tier: project-local and mandatory

Reason: enforces repo-first inspection, hard verification, no simulated success, and no secret leakage.

## Deferred Or Rejected Sources

- `heilcheng/awesome-agent-skills`
  Discovery or index repo only; not a first-pass install source.
- `coleam00/excalidraw-diagram-skill`
  Deferred until a proper Codex or OpenAI-style `SKILL.md` package path is verified.
- random GitHub skills repos
  Rejected unless they expose real skill folders with `SKILL.md` and have a credible maintenance story.

## Source Verification

- Verified `openai/skills` exists on GitHub and was used as the curated source.
- Verified `TerminalSkills/skills` exists on GitHub and was used for the community audit skill.
- Verified each selected installed skill exists locally as a real folder with `SKILL.md`.

## Post-Install Audit

### Existing Project-Local Skills

None found in:

- `.agents/skills`
- `.codex/skills`
- `skills`

### Evidence Used

- repository README for current project surface and built-in OpenJarvis capabilities
- local project tree for project-specific skill folders
- Codex memory index search for `OpenJarvis`, `Co-bob`, `jarvis_server`, `start_telegram_bot`, and `jarvis_voice`

The memory index search returned no matching entries, so the audit stayed grounded in the current repo surface.

### Suggested Updates

- None yet.

The repo currently relies on global Codex skills plus custom local launcher and surface files such as `jarvis_server.py`, `jarvis_voice.html`, `web_interface.html`, and `start_telegram_bot.py`.

### Suggested Future Project-Local Skills

- `jarvis-voice-e2e`
  Trigger: browser voice, wake-word, STT or TTS, and Telegram voice regressions.
  Workflow: run end-to-end validation for microphone, transcription, streaming response, audio output, and Telegram voice handling.
- `jarvis-secret-migration`
  Trigger: Brave, ElevenLabs, Telegram, and related secret cleanup work.
  Workflow: find exposed secrets, migrate to vault, env, or config references, preserve behavior, and verify startup paths.
- `jarvis-surface-rebuild`
  Trigger: migration from root custom web and server files to the official React and FastAPI surface.
  Workflow: preserve user-visible features while consolidating architecture and reducing duplicated logic.

### Priority Order

1. Keep the current global skill stack active during the rebuild.
2. Use `real-build-guard` as the mandatory verification layer for all implementation work.
3. Revisit project-local skills after the first stable Jarvis rebuild pass lands.
