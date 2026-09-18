#!/usr/bin/env bash
set -euo pipefail

# ── OpenJarvis: launch Claude via the cloud engine ────────────────────
# Claude is a proprietary Anthropic model with no public weights, so it
# cannot be served by Ollama. This script routes through OpenJarvis's
# ``cloud`` engine, which speaks the Anthropic API directly.
#
# Usage:
#   export ANTHROPIC_API_KEY=sk-ant-...
#   ./scripts/launch-claude.sh                       # default model
#   ./scripts/launch-claude.sh claude-sonnet-4-6     # pick a model
#   ./scripts/launch-claude.sh -- --voice            # pass-through flags
# ──────────────────────────────────────────────────────────────────────

DEFAULT_MODEL="${OPENJARVIS_CLAUDE_MODEL:-claude-opus-4-6}"

MODEL="$DEFAULT_MODEL"
if [[ $# -gt 0 && "$1" != "--" ]]; then
    MODEL="$1"
    shift
fi
if [[ ${1:-} == "--" ]]; then
    shift
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "error: ANTHROPIC_API_KEY is not set" >&2
    echo "  get a key at https://console.anthropic.com/ and export it first" >&2
    exit 2
fi

if ! command -v jarvis >/dev/null 2>&1; then
    echo "error: 'jarvis' CLI not found on PATH" >&2
    echo "  install with: pip install -e '.[inference-cloud]'" >&2
    exit 3
fi

exec jarvis chat --engine cloud --model "$MODEL" "$@"
