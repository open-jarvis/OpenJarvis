#!/usr/bin/env bash
# Scaffold a new hybrid paradigm experiment cell.
#
# Appends a [cells.<name>] block to
# src/openjarvis/agents/hybrid/registry/<method>.toml
# (registry is split by method — minions.toml, conductor.toml, etc.).
#
# Usage:
#   src/openjarvis/agents/hybrid/scripts/new_experiment.sh \
#       --method minions --bench gaia \
#       --local qwen3.5-27b --cloud claude-opus-4-7 --n 50 \
#       [--mode minion|minions] [--max-rounds 3]
#
# Then run:
#   python -m openjarvis.agents.hybrid.runner --cell <printed name>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/registry"

method=""; bench=""; local_model=""; cloud_model=""; n=""
mode="minion"; max_rounds=3

while [[ $# -gt 0 ]]; do
    case "$1" in
        --method)      method="$2";       shift 2;;
        --bench)       bench="$2";        shift 2;;
        --local)       local_model="$2";  shift 2;;
        --cloud)       cloud_model="$2";  shift 2;;
        --n)           n="$2";            shift 2;;
        --mode)        mode="$2";         shift 2;;
        --max-rounds)  max_rounds="$2";   shift 2;;
        *) echo "unknown arg: $1" >&2; exit 2;;
    esac
done

for v in method bench local_model cloud_model n; do
    if [[ -z "${!v}" ]]; then
        echo "missing required --${v//_/-}" >&2
        exit 2
    fi
done

# Map shortnames → full HF id + endpoint
case "$local_model" in
    qwen3.5-27b|qwen-27b|qwen27b)   local_full="Qwen/Qwen3.5-27B-FP8";       local_ep="http://localhost:8001/v1";;
    qwen3.5-9b|qwen-9b|qwen9b)      local_full="Qwen/Qwen3.5-9B";            local_ep="http://localhost:8001/v1";;
    gemma-4-31b|gemma-31b|gemma31b) local_full="google/gemma-4-31B-it";      local_ep="http://localhost:8004/v1";;
    gemma-4-26b|gemma-26b|gemma26b) local_full="google/gemma-4-26B-A4B-it";  local_ep="http://localhost:8004/v1";;
    *)                              local_full="$local_model";               local_ep="${LOCAL_ENDPOINT:-http://localhost:8001/v1}";;
esac

case "$cloud_model" in
    gpt-5|gpt-5-mini|gpt-4o)               cloud_ep="openai";;
    claude-opus-4-7|claude-sonnet-4-6)     cloud_ep="anthropic";;
    *)                                     cloud_ep="${CLOUD_ENDPOINT:-anthropic}";;
esac

local_short="$(echo "$local_model" | tr '/' '_')"
cloud_short="$cloud_model"
name="${method}-${bench}-${local_short}-${cloud_short}-${n}"

registry_file="$REGISTRY_DIR/${method}.toml"
if [[ ! -f "$registry_file" ]]; then
    echo "no registry file for method '${method}' — expected $registry_file" >&2
    echo "known: $(ls "$REGISTRY_DIR" | tr '\n' ' ')" >&2
    exit 2
fi

# Method-specific method_cfg defaults — keep simple, override later in TOML.
case "$method" in
    minions)
        cfg_block="method_cfg = { mode = \"${mode}\", max_rounds = ${max_rounds}, worker_max_tokens = 4096 }"
        ;;
    conductor)
        cfg_block="method_cfg = { conductor_max_tokens = 2048, worker_max_tokens = 4096 }"
        ;;
    advisors)
        cfg_block="method_cfg = { executor_max_tokens = 4096, advisor_max_tokens = 1024 }"
        ;;
    archon)
        cfg_block="method_cfg = { architecture = \"ensemble_rank_fuse\", n_samples = 5, max_tokens = 2048 }"
        ;;
    skillorchestra)
        cfg_block="method_cfg = { router_max_tokens = 1024, local_max_tokens = 4096, cloud_max_tokens = 4096 }"
        ;;
    toolorchestra)
        cfg_block="method_cfg = { max_turns = 6, orchestrator_max_tokens = 1024, worker_max_tokens = 4096 }"
        ;;
    *)
        cfg_block="method_cfg = {}"
        ;;
esac

cat >> "$registry_file" <<EOF

[cells.${name}]
method = "${method}"
bench  = "${bench}"
n      = ${n}
local  = { model = "${local_full}", endpoint = "${local_ep}" }
cloud  = { model = "${cloud_model}", endpoint = "${cloud_ep}" }
${cfg_block}
EOF

echo "Added cell: ${name}  →  $(realpath --relative-to="$(pwd)" "$registry_file")"
echo "Run with: python -m openjarvis.agents.hybrid.runner --cell ${name}"
