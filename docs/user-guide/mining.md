# Pearl Mining

OpenJarvis can mine the Pearl Proof-of-Useful-Work chain through local LLM
inference. The primary v1 path supports NVIDIA H100/H200 hosts running vLLM
with Pearl's Docker miner. The consolidated Pearl integration also includes
experimental Apple Silicon and CPU providers through the same `MiningProvider`
registry.

## Prerequisites

| Requirement | v1 expectation |
|---|---|
| GPU | NVIDIA H100 or H200, sm_90a class, at least 70 GB VRAM |
| OS | Linux with `nvidia-container-toolkit` configured |
| Docker | Docker 24+ with GPU runtime access |
| Disk | At least 200 GB free for the 70B model and build cache |
| Pearl node | Reachable `pearld` JSON-RPC endpoint, default `http://localhost:44107` |
| Wallet | Pearl address beginning with `prl1q` or `prl1p` |

The default vLLM config uses `gpu_memory_utilization = 0.96` and
`max_model_len = 8192` for the Pearl 70B mining model on H100/H200 80 GB GPUs.

To generate a wallet address with Pearl's Oyster wallet, run Pearl's wallet
daemon and query it with `prlctl --wallet --skipverify -s localhost:44207
getnewaddress`. Do not reuse a wallet whose mnemonic has been pasted into logs,
chat, or issue trackers.

## Quick Start

```bash
uv sync --extra mining-pearl-vllm
export PEARLD_RPC_PASSWORD=<your-pearld-password>
export HF_TOKEN=<your-huggingface-token>

uv run jarvis mine init
uv run jarvis mine start
uv run jarvis mine status
```

`mine init` writes a `[mining]` config section and resolves the Pearl Docker
image. If Pearl has not published a suitable image for the pinned ref,
OpenJarvis falls back to building from the pinned Pearl source checkout. First
builds can take 30-60 minutes.

On a shared NVIDIA host, restrict the miner to idle GPUs:

```bash
uv run jarvis mine init --cuda-visible-devices 0
```

This writes `[mining.extra].cuda_visible_devices`, which `mine start` passes to
Docker instead of exposing every GPU on the machine.

## Commands

- `jarvis mine models` lists Pearl model support status.
- `jarvis mine inspect-model` checks a Pearl model artifact before GPU launch.
- `jarvis mine doctor` prints hardware, Docker, Pearl node, wallet, provider,
  and session checks.
- `jarvis mine init` writes the local mining config and resolves the image.
- `jarvis mine start` launches the Pearl miner container and writes the runtime
  sidecar.
- `jarvis mine stop` stops the provider and removes the sidecar.
- `jarvis mine status` reads live gateway metrics.
- `jarvis mine attach` writes a sidecar for a miner you launched manually.
- `jarvis mine logs` prints the Docker container log tail.
- `jarvis mine validate-model` probes the active vLLM miner and gateway before
  promoting a planned Pearl model to validated.

## Model Support

Run:

```bash
jarvis mine models
```

OpenJarvis only enables models that have Pearl-compatible quantized artifacts
and real hardware validation. Raw Hugging Face models such as
`Qwen/Qwen3.5-9B` or `google/gemma-4-E4B-it` are not mineable by themselves;
they need corresponding Pearl-compatible variants.

The validated models are:

```text
pearl-ai/Llama-3.3-70B-Instruct-pearl
ScalingIntelligence/Gemma-4-31B-it-pearl
ScalingIntelligence/Qwen3.5-9B-pearl
```

The Gemma 31B and Qwen 3.5 9B artifacts are experimental private staging
artifacts under the `ScalingIntelligence` Hugging Face org. You need Hugging
Face access to those repos before OpenJarvis can inspect or run them. They were
validated on H100 with `jarvis mine validate-model`, but the short validation
runs did not find a reward-bearing block or accepted share.

When validating a newly converted Pearl model on a mining host, run:

```bash
jarvis mine inspect-model \
  --model ScalingIntelligence/Qwen3.5-9B-pearl

jarvis mine validate-model \
  --model ScalingIntelligence/Qwen3.5-9B-pearl \
  --prompt "Say hello in one sentence." \
  --output qwen3.5-9b-pearl-validation.json
```

Attach the JSON artifact to the validation issue when promoting additional
models.

## v1 Scope

v1 is solo mining only. OpenJarvis does not take fees, custody funds, generate
wallet keys, run pools, or operate `pearld`. Users provide their own Pearl node
and payout address.

Unsupported in this PR:

- Pool mining and the future 20% OpenJarvis fee model
- AMD GPU mining and non-Pearl backends
- RTX 4090 or other non-Hopper NVIDIA GPUs
- Wallet generation or transaction signing inside OpenJarvis

## Troubleshooting

Run:

```bash
uv run jarvis mine doctor
```

Read the rows top-down. Fix the first failing dependency before retrying
`mine start`. A Mac or AMD machine should fail honestly at provider capability;
those paths are expected to land as separate providers.

## Production Readiness

The NVIDIA path requires one real H100/H200 validation run before it should be
marketed as a proven earning path. The developer runbook is
[`../development/mining-nvidia-validation.md`](../development/mining-nvidia-validation.md).
