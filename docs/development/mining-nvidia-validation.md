# NVIDIA Pearl Mining Validation Runbook

This runbook is the release gate for the v1 `vllm-pearl` provider. Unit tests
prove OpenJarvis wiring; this validates that a real H100/H200 host can mine
through Pearl and serve inference through OpenJarvis.

## Required Host

Run this on a Linux machine with:

- NVIDIA H100 or H200 GPU, compute capability 9.0, at least 70 GB VRAM
- Current NVIDIA driver with CUDA container support
- Docker 24+ and `nvidia-container-toolkit`
- At least 200 GB free disk
- Reachable `pearld` JSON-RPC endpoint
- Pearl payout address beginning with `prl1q` or `prl1p`
- Hugging Face access to `pearl-ai/Llama-3.3-70B-Instruct-pearl`

The validated H100 configuration uses `gpu_memory_utilization = 0.96` with
`max_model_len = 8192`. Lower memory utilization can fail during vLLM startup
because the Pearl 70B mining model leaves too little KV cache at 8k context.

Do not run this on macOS, Apple Silicon, AMD, RTX 4090, or CPU-only hosts.
Those are separate providers.

## Wallet Address Setup

Create the wallet from the Pearl repo root:

```bash
./bin/oyster -u rpcuser -P rpcpass --create
```

If you choose the optional public-data encryption prompt, Oyster will require
that public passphrase on startup via `--walletpass`. Keep private and public
passphrases out of shell history where possible.

Start Oyster:

```bash
./bin/oyster \
  -u rpcuser \
  -P rpcpass \
  --walletpass '<public-wallet-passphrase-if-configured>' \
  &
```

Then generate a mining address through the wallet RPC:

```bash
./bin/prlctl \
  --wallet \
  --skipverify \
  -u rpcuser \
  -P rpcpass \
  -s localhost:44207 \
  getnewaddress
```

Notes:

- `--wallet` is required. Without it, `prlctl` talks to `pearld` instead of
  Oyster and may look for `Pearld/pearld.conf`.
- Use `-s localhost:44207`, not `-s https://localhost:44207`. `prlctl` expects
  host and port, not a URL.
- `--skipverify` is acceptable for this local validation flow unless you have
  configured the Oyster RPC certificate path.
- If a mnemonic has been pasted into logs, chat, or a PR, discard that wallet
  and create a fresh one before mining.

## Environment

```bash
git checkout feat/mining-spec-a-only
uv sync --extra dev --extra mining-pearl-vllm

export PEARLD_RPC_PASSWORD='<pearld-rpc-password>'
export HF_TOKEN='<huggingface-token>'
```

Confirm host prerequisites:

```bash
nvidia-smi
docker info
docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
df -h ~/.cache
```

Expected:

- `nvidia-smi` shows H100 or H200.
- Docker can run a CUDA container with GPU access.
- `~/.cache` or the Hugging Face cache volume has at least 200 GB free.

On shared hosts, select only idle GPUs during `mine init`:

```bash
uv run jarvis mine init --cuda-visible-devices 0
```

This writes `[mining.extra].cuda_visible_devices`. `mine start` passes that
device list to Docker and sets `CUDA_VISIBLE_DEVICES` /
`NVIDIA_VISIBLE_DEVICES` inside the container. Omit the option only on a
dedicated host where the miner may use all GPUs.

## Configure Mining

Run:

```bash
uv run jarvis mine doctor
```

Before config exists, `doctor` should show hardware and Docker as OK, and
Pearl node / wallet as unconfigured.

Then initialize:

```bash
uv run jarvis mine init
```

Use:

- Wallet: the user's Pearl `prl1q...` or `prl1p...` address
- `pearld` URL: usually `http://localhost:44107`
- RPC user: configured `pearld` user, often `rpcuser`
- Password env: `PEARLD_RPC_PASSWORD`
- Model: `pearl-ai/Llama-3.3-70B-Instruct-pearl`
- Image: default unless validating a custom Pearl image
- CUDA devices: an idle GPU ID such as `0` on shared hosts

Expected:

- `[mining]` and `[mining.extra]` are written to config.
- Image resolves locally, pulls, or builds from the pinned Pearl ref.
- First build may take 30-60 minutes.

Run `doctor` again:

```bash
uv run jarvis mine doctor
```

Expected:

- Hardware OK
- Docker OK
- Disk OK
- Pearl node RPC OK and synced
- Wallet format OK
- `vllm-pearl SUPPORTED`
- Sidecar absent

## Start Mining

```bash
uv run jarvis mine start
```

Expected:

- Docker container `openjarvis-pearl-miner` starts.
- `~/.openjarvis/runtime/mining.json` is written.
- Sidecar contains `vllm_endpoint`, `gateway_url`, `gateway_metrics_url`, and
  `container_id`.

Inspect:

```bash
docker ps --filter name=openjarvis-pearl-miner
cat ~/.openjarvis/runtime/mining.json
uv run jarvis mine logs --tail 200
uv run jarvis mine status
```

Expected:

- Container is running.
- vLLM is listening on the configured port, default `8000`.
- Pearl gateway metrics are available on the configured metrics port, default
  `8339`.
- `mine status` exits 0 and prints `provider: vllm-pearl`.

## Verify OpenJarvis Inference Uses Mining Endpoint

Run:

```bash
uv run jarvis mine doctor
uv run jarvis ask "Say hello in one sentence."
```

Expected:

- `doctor` shows sidecar present.
- Engine discovery registers `vllm-pearl-mining`.
- The prompt completes through the Pearl/vLLM endpoint.
- Container logs show vLLM activity during the prompt.

If inference succeeds but mining stats stay zero, continue to the Pearl
network checks below; vLLM serving alone is not enough to prove mining.

## Verify Pearl Network Submission

Check gateway metrics directly:

```bash
curl -fsS http://127.0.0.1:8339/metrics | tee /tmp/pearl-gateway-metrics.txt
uv run jarvis mine status
```

Expected:

- Metrics endpoint returns Prometheus text.
- If Pearl exposes share counters, `mine status` maps them correctly.
- If metric names differ, attach `/tmp/pearl-gateway-metrics.txt` to the PR and
  update `src/openjarvis/mining/_metrics.py`.

Check `pearld` connectivity using the same RPC configuration used by mining:

```bash
curl --user "rpcuser:${PEARLD_RPC_PASSWORD}" \
  --data-binary '{"jsonrpc":"1.0","id":"oj","method":"getblockchaininfo","params":[]}' \
  -H 'content-type: text/plain;' \
  http://127.0.0.1:44107
```

Expected:

- `blocks` and `headers` are present.
- Node is synced or close enough for mining validation.

Proof of actual earning requires a successful accepted share/block and wallet
credit. Depending on Pearl network difficulty, this may take longer than the
smoke test window. Record:

- Runtime duration
- `mine status` before and after
- Gateway metrics snapshot
- Relevant container log tail
- Wallet balance / transaction evidence if a reward lands

## Stop And Cleanup

```bash
uv run jarvis mine stop
docker ps --filter name=openjarvis-pearl-miner
test ! -e ~/.openjarvis/runtime/mining.json
```

Expected:

- Container stops.
- Sidecar is removed.
- `jarvis ask` no longer routes through `vllm-pearl-mining` unless another
  mining sidecar is attached.

## Pass Criteria

The NVIDIA provider is considered proven when all are true:

- `mine doctor` reports supported on H100/H200.
- `mine init` resolves/builds the Pearl image.
- `mine start` launches the container and writes the sidecar.
- OpenJarvis inference succeeds through `vllm-pearl-mining`.
- Pearl gateway metrics are reachable and `mine status` parses them.
- `pearld` accepts the miner's network path.
- At least one accepted share/block is observed, or a documented Pearl
  maintainer confirmation says the observed gateway state is sufficient proof
  of live mining.

## Failure Artifacts

For any failure, collect:

```bash
uv run jarvis mine doctor
uv run jarvis mine status || true
uv run jarvis mine logs --tail 300 || true
docker inspect openjarvis-pearl-miner || true
curl -fsS http://127.0.0.1:8339/metrics || true
nvidia-smi
docker info
```

Attach outputs to the implementation PR or follow-up issue. Do not paste
`PEARLD_RPC_PASSWORD`, wallet seed material, or Hugging Face tokens.
