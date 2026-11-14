# Codex workflows

These workflows adapt the repository's Claude-specific GitHub automations to OpenAI Codex.

- Comment `@codex` on a pull request to request a read-only review.
- Comment `@codex` on an issue, or use the `bug` / `autofix` labels, to ask Codex for a proposed fix in a pull request.

## Setup

1. Create an OpenAI API key at https://platform.openai.com/api-keys. ChatGPT Plus/Pro subscription does not include API usage.
2. In this repository, open Settings → Secrets and variables → Actions → New repository secret.
3. Set the secret name to `OPENAI_API_KEY` and paste the key as its value. Never commit or post the key.
4. In Settings → Actions → General, allow GitHub Actions to create pull requests if you want the issue fixer workflow to publish proposed fixes.

The review workflow uses read-only Codex access. The issue fixer may edit its checked-out workspace; changes are proposed as a pull request for your review.
