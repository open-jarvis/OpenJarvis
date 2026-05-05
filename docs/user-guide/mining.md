# Pearl Mining

OpenJarvis can mine the Pearl Proof-of-Useful-Work chain through local LLM
inference. v1 supports NVIDIA H100/H200 hosts running vLLM with Pearl's
Docker miner. Apple Silicon GPU support is a separate parallel effort; the
integration point is the `MiningProvider` registry.

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

## Commands

- `jarvis mine doctor` prints hardware, Docker, Pearl node, wallet, provider,
  and session checks.
- `jarvis mine init` writes the local mining config and resolves the image.
- `jarvis mine start` launches the Pearl miner container and writes the runtime
  sidecar.
- `jarvis mine stop` stops the provider and removes the sidecar.
- `jarvis mine status` reads live gateway metrics.
- `jarvis mine attach` writes a sidecar for a miner you launched manually.
- `jarvis mine logs` prints the Docker container log tail.

## v1 Scope

v1 is solo mining only. OpenJarvis does not take fees, custody funds, generate
wallet keys, run pools, or operate `pearld`. Users provide their own Pearl node
and payout address.

Unsupported in this PR:

- Pool mining and the future 20% OpenJarvis fee model
- Apple Silicon, AMD, and non-vLLM backends
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
