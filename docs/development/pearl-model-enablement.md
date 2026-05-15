# Pearl Model Enablement

This page tracks the work required to make a new Hugging Face model mineable
through Pearl's vLLM miner and OpenJarvis.

OpenJarvis can point `vllm-pearl` at a model id, but a raw Hugging Face model is
not enough. The Pearl vLLM plugin expects a Pearl-compatible quantized model
whose metadata marks mining layers for 7-bit NoisyGEMM and non-mining layers
for the vanilla Pearl GEMM path.

## Supported Models

OpenJarvis only supports Pearl models published by the `pearl-ai` Hugging Face
organization. Private staging artifacts and OpenJarvis-specific conversion
repos are not user-facing supported mining models.

The current public support set is:

| Raw model | Pearl model | Status |
|---|---|---|
| `meta-llama/Llama-3.3-70B-Instruct` | `pearl-ai/Llama-3.3-70B-Instruct-pearl` | Validated default |
| `google/gemma-4-31B-it` | `pearl-ai/Gemma-4-31B-it-pearl` | Planned until H100/H200 validation passes |
| `meta-llama/Llama-3.1-8B-Instruct` | `pearl-ai/Llama-3.1-8B-Instruct-pearl` | Planned until H100/H200 validation passes |

## Current Validation Findings

The H100 smoke run validated the default Llama Pearl model end to end through
`jarvis mine start`, vLLM `/v1/models`, OpenJarvis inference routing, Pearl
gateway template refresh, and `jarvis mine validate-model`.

`pearl-ai/Gemma-4-31B-it-pearl` and
`pearl-ai/Llama-3.1-8B-Instruct-pearl` are listed because they are public Pearl
org artifacts. They remain `planned` in OpenJarvis until we have clean
H100/H200 validation artifacts for the published repos.

## Enablement Checklist

1. Reproduce the current Llama Pearl model recipe.
   - Record the compressed-tensors config.
   - Record which linear layers are 7-bit mining layers.
   - Record which layers are 8-bit non-mining layers.
   - Record calibration data and SmoothQuant settings, if used.

2. Convert the target model.
   - Start with a model Pearl intends to publish under the `pearl-ai` org.
   - Generate Pearl-compatible quantized weights and metadata.
   - For Gemma4 artifacts, include the base model's processor metadata required
     by vLLM's Gemma4 multimodal profiler.
   - Publish under the planned `pearl-ai/*-pearl` id before enabling it in
     OpenJarvis.

   OpenJarvis includes an experimental local converter for this work:

   ```bash
   python scripts/pearl/model_converter.py \
     meta-llama/Llama-3.1-8B-Instruct \
     /tmp/pearl-ai-Llama-3.1-8B-Instruct-pearl \
     --device cuda
   ```

   The converter copies Hugging Face metadata, emits
   `quantization_config.quant_method = "pearl"`, writes a safetensors index,
   converts attention q/k/v and MLP down projections to int8 non-mining layers,
   and converts the remaining text linear weights to int7 mining layers. Treat
   its output as a staging artifact until `jarvis mine inspect-model` and
   `jarvis mine validate-model` pass on H100/H200 hardware.

   Local staging artifacts can be inspected before upload:

   ```bash
   jarvis mine inspect-model \
     --model /tmp/pearl-ai-Llama-3.1-8B-Instruct-pearl
   ```

   To run a local staging artifact through the Docker miner, keep `--model` as
   the intended served model name and point `--local-model-path` at the
   converted checkpoint directory:

   ```bash
   jarvis mine init \
     --provider vllm-pearl \
     --wallet-address <prl1...> \
     --model pearl-ai/Llama-3.1-8B-Instruct-pearl \
     --local-model-path /tmp/pearl-ai-Llama-3.1-8B-Instruct-pearl \
     --cuda-visible-devices 1 \
     --vllm-arg=--language-model-only \
     --vllm-arg=--skip-mm-profiling
   jarvis mine start
   ```

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
