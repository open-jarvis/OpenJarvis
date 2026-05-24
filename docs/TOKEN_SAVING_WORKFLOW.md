# Token-Saving Workflow for OpenJarvis

## Goal
Use Claude, Codex, and local Ollama together while minimizing paid cloud token usage.

## Recommended Roles

### Ollama
Use Ollama for normal OpenJarvis / Friday runtime responses.

Examples:
- simple Korean conversation
- weather summaries
- local commands
- short assistant replies

### Codex
Use Codex for code implementation.

Examples:
- modifying files
- adding features
- fixing bugs
- running tests
- creating documentation
- preparing git diffs

### Claude
Use Claude for high-level thinking only.

Examples:
- architecture review
- debugging plan
- reviewing Codex diffs
- identifying risks
- deciding implementation direction

## Recommended Workflow

1. Ask Claude for a short plan.
2. Give the implementation task to Codex.
3. Let Codex modify files locally.
4. Export the diff:
   `git diff > /tmp/openjarvis_changes.diff`
5. Ask Claude to review only the diff.
6. Apply final fixes with Codex.
7. Commit the result.

## Important Rules
- Do not upload the whole repository to Claude repeatedly.
- Do not paste large files unless necessary.
- Prefer git diff reviews.
- Keep cloud model calls optional.
- Default runtime inference should remain local-first.
