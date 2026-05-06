# Pearl Model Enablement

This page tracks the work required to make a new Hugging Face model mineable
through Pearl's vLLM miner and OpenJarvis.

OpenJarvis can point `vllm-pearl` at a model id, but a raw Hugging Face model is
not enough. The Pearl vLLM plugin expects a Pearl-compatible quantized model
whose metadata marks mining layers for 7-bit NoisyGEMM and non-mining layers
for the vanilla Pearl GEMM path.

## Target Models

| Raw model | Planned Pearl model | Status | Tracking |
|---|---|---|---|
| `Qwen/Qwen3.5-9B` | `pearl-ai/Qwen3.5-9B-pearl` | Planned | [#316](https://github.com/open-jarvis/OpenJarvis/issues/316) |
| `Qwen/Qwen3.6-27B` | `pearl-ai/Qwen3.6-27B-pearl` | Planned | [#317](https://github.com/open-jarvis/OpenJarvis/issues/317) |
| `google/gemma-4-E4B-it` | `pearl-ai/Gemma-4-E4B-it-pearl` | Planned | [#318](https://github.com/open-jarvis/OpenJarvis/issues/318) |
| `google/gemma-4-31B-it` | `pearl-ai/Gemma-4-31B-it-pearl` | Planned | [#319](https://github.com/open-jarvis/OpenJarvis/issues/319) |

The current validated model remains:

```text
pearl-ai/Llama-3.3-70B-Instruct-pearl
```

## Current Validation Findings

The H100 smoke run validated the default Llama Pearl model end to end through
`jarvis mine start`, vLLM `/v1/models`, OpenJarvis inference routing, Pearl
gateway template refresh, and `jarvis mine validate-model`.

The Qwen and Gemma targets remain planned:

- `pearl-ai/Qwen3.5-9B-pearl`, `pearl-ai/Qwen3.6-27B-pearl`, and
  `pearl-ai/Gemma-4-E4B-it-pearl` are not publicly available artifacts yet.
- `pearl-ai/Gemma-4-31B-it-pearl` exists and selects Pearl mining kernels on
  H100, but vLLM fails during Gemma4 multimodal profiling because the published
  artifact is missing processor/preprocessor metadata required by Transformers.
  A local cache experiment proved the processor can be loaded only after
  injecting metadata from `google/gemma-4-31B-it`; that is not sufficient for
  OpenJarvis promotion because a clean user install would still fail.

## Enablement Checklist

1. Reproduce the current Llama Pearl model recipe.
   - Record the compressed-tensors config.
   - Record which linear layers are 7-bit mining layers.
   - Record which layers are 8-bit non-mining layers.
   - Record calibration data and SmoothQuant settings, if used.

2. Convert the target model.
   - Start with `Qwen/Qwen3.5-9B`; it is the smallest target.
   - Generate Pearl-compatible quantized weights and metadata.
   - For Gemma4 artifacts, include the base model's processor metadata required
     by vLLM's Gemma4 multimodal profiler.
   - Publish under the planned `pearl-ai/*-pearl` id or a staging namespace.

3. Validate the Pearl vLLM plugin path.
   - Run `jarvis mine inspect-model --model <pearl-model-id>
     --allow-planned` before starting the miner.
   - Model loads in Pearl's `vllm-miner` container.
   - vLLM registers Pearl's quantization plugin.
   - Mining layers use int7 NoisyGEMM.
   - Non-mining layers use int8 vanilla Pearl GEMM.
   - Text generation works with mining enabled and disabled.

4. Validate chain integration.
   - `pearld` is reachable.
   - `pearl-gateway` receives work.
   - NoisyGEMM submits candidate proofs.
   - Gateway reports metrics.
   - `jarvis mine status` parses those metrics.

5. Promote the model in OpenJarvis.
   - Change its registry status from `planned` to `validated`.
   - Set measured VRAM and context defaults.
   - Add the model to user docs.
   - Attach validation logs to the PR.

## OpenJarvis Registry

Model support metadata lives in:

```text
src/openjarvis/mining/_models.py
```

`jarvis mine models` renders that registry. Planned models are visible to users
but blocked by capability detection until the Pearl model artifact and H100/H200
validation exist.

## Acceptance Criteria

A model is `validated` only when all of these pass on real hardware:

- `jarvis mine inspect-model --model <pearl-model-id> --allow-planned`
- `jarvis mine init --model <pearl-model-id>`
- `jarvis mine start`
- `curl http://127.0.0.1:8000/v1/models`
- `jarvis ask "Say hello in one sentence."`
- `jarvis mine status`
- `jarvis mine validate-model --model <pearl-model-id> --allow-planned --prompt
  "Say hello in one sentence." --output <artifact>.json`
- Pearl gateway metrics show the mining path is active.
- No block/share submission errors appear in gateway or miner logs.

Do not mark a model validated based only on vLLM load success. It must exercise
Pearl's NoisyGEMM and submission path.

## Tracking

Use the `Pearl Model Validation` GitHub issue template for each candidate model.
The issue should hold the quantization recipe, hardware details, command output,
metrics excerpts, and the PR that changes the model status to `validated`.
Attach the JSON artifact from `jarvis mine validate-model --output` to the issue.
