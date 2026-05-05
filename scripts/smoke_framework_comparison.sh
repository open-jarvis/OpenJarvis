#!/usr/bin/env bash
# smoke_framework_comparison.sh
#
# One-task-per-cell sanity check for the framework-comparison harness.
# Run before kicking off a benchmark sweep.
#
# Required env vars:
#   HERMES_AGENT_PATH   - path to pinned hermes-agent checkout
#   OPENCLAW_PATH       - path to pinned openclaw checkout
#   JARVIS_MOCK_LLM_URL - OpenAI-compatible endpoint (Ollama or vLLM)
#
# Optional:
#   JARVIS_ALLOW_COMMIT_DRIFT=1  - bypass commit-pin enforcement

set -euo pipefail

: "${HERMES_AGENT_PATH:?must be set}"
: "${OPENCLAW_PATH:?must be set}"
: "${JARVIS_MOCK_LLM_URL:?must be set (e.g. http://localhost:11434/v1)}"

# OpenClaw prerequisites: Node version + dist/ dir
NODE_VERSION=$(node --version 2>&1 || echo "v0")
NODE_MAJOR=$(echo "$NODE_VERSION" | sed -E 's/v([0-9]+)\..*/\1/')
if [ "$NODE_MAJOR" -lt 14 ]; then
  echo "WARNING: Node $NODE_VERSION may be too old for OpenClaw (needs ≥14.8)"
  echo "         OpenClaw runs may fail with 'SyntaxError: Unexpected reserved word'"
fi
if [ ! -f "$OPENCLAW_PATH/dist/entry.js" ]; then
  echo "WARNING: $OPENCLAW_PATH/dist/entry.js not found"
  echo "         OpenClaw needs 'pnpm install && pnpm build' before use"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Verifying commit pins"
uv run python -c "
from openjarvis.evals.comparison.third_party import (
    load_third_party_config, verify_commit_pin,
)
cfg = load_third_party_config()
for name, entry in cfg.entries.items():
    print(f'  {name}: {entry.path}')
    verify_commit_pin(entry)
print('  all pins OK')
"

echo "==> Running one-task smoke per (framework, benchmark)"
mkdir -p results/smoke
SMOKE_BENCHES=(toolcall15 pinchbench gaia)
SMOKE_FRAMEWORKS=(hermes openclaw openjarvis)
SMOKE_MODEL="qwen-9b"

for fwk in "${SMOKE_FRAMEWORKS[@]}"; do
  for bench in "${SMOKE_BENCHES[@]}"; do
    config="src/openjarvis/evals/configs/framework_comparison/${bench}-${fwk}-${SMOKE_MODEL}.toml"
    if [ ! -f "$config" ]; then
      echo "  ! missing config: $config (run make_configs --all-tier1 (or materialize the configs you need))"
      continue
    fi
    echo "  ▸ $fwk × $bench"
    uv run python -m openjarvis.evals run --config "$config" --max-samples 1 \
      --output-dir "results/smoke/${fwk}/${SMOKE_MODEL}/${bench}/" \
      || echo "    FAILED (continuing)"
  done
done

echo "==> Generating T1 from smoke results"
uv run python -m openjarvis.evals.comparison.table_gen \
    --results-glob "results/smoke/**/summary.json" \
    --tables T1 \
    --output-dir results/smoke/tables/

echo "==> Verifying T1.tex non-empty"
test -s results/smoke/tables/T1.tex && echo "  OK: T1.tex emitted"

echo "==> Smoke validation complete"
