# Claude Instructions for OpenJarvis

## Project Goal
We are adapting OpenJarvis into a Korean local-first AI assistant called Friday.

## Primary Strategy
Claude should be used for:
- architecture review
- implementation planning
- debugging strategy
- security review
- reviewing Codex-generated diffs

Codex should be used for:
- code edits
- file creation
- refactoring
- test execution
- implementation work

Ollama/local models should be used for:
- normal assistant runtime responses
- simple Korean conversations
- low-cost local inference

## Cost Control
- Do not inspect the entire repository unless necessary.
- Prefer reviewing specific files or git diffs.
- Avoid rewriting large files.
- Keep answers concise and implementation-focused.

## Review Focus
When reviewing Codex changes, check:
1. whether local-first behavior is preserved
2. whether cloud API calls are gated behind explicit config
3. whether secrets or API keys are exposed
4. whether Mac runtime/startup behavior is affected
5. whether tests or smoke checks are missing
