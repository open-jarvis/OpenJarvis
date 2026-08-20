# Spec A — vLLM-Pearl mining integration (v1)

| | |
|---|---|
| **Date** | 2026-05-05 |
| **Status** | Design — pending implementation plan |
| **Owner** | OpenJarvis team |
| **Companion spec** | [Spec B — Apple Silicon enablement](2026-05-05-apple-silicon-pearl-mining-design.md) (separate effort, runs in parallel) |
| **Repos referenced** | `OpenJarvis` (this repo), `pearl-research-labs/pearl` |

## 1. Summary

Add a new sibling subsystem `openjarvis.mining` that lets users run [Pearl](https://github.com/pearl-research-labs/pearl) Proof-of-Useful-Work mining as a property of their local LLM inference. v1 ships solo mining for users who already have an H100/H200 and run vLLM — the only configuration Pearl's reference miner currently supports. The architecture leaves three deliberate seams for v2 (pool support + a 20% OJ fee) and is engine-agnostic by construction so Apple Silicon, AMD, Ollama, llama.cpp, and MLX paths plug in via the registry without a rewrite when Pearl ships the matching plugins.

The narrative thesis: Pearl's `vllm-miner` is a vLLM plugin that swaps quantized linear ops with `NoisyGEMM`, a CUDA kernel that produces both the correct matmul output *and* a PoW commitment. Mining IS inference. For an OJ user already serving prompts on a powerful local GPU, this is a way to capture economic value from compute they were going to do anyway — directly aligned with OJ's Intelligence-Per-Watt thesis rather than against it.

## 2. Scope

### In scope (v1)
- New `openjarvis.mining` subsystem with `MiningProvider` ABC, `MinerRegistry`, `MiningCapabilities` / `MiningConfig` / `MiningStats` dataclasses
- `vllm-pearl` provider implementation: orchestrate Pearl's published `vllm-miner` Docker container
- `[mining]` TOML section in OJ config; `MiningConfig` field in `JarvisConfig`
- New CLI namespace: `jarvis mine init|start|stop|status|doctor|attach|logs`
- Runtime sidecar at `~/.openjarvis/runtime/mining.json` for engine ↔ mining handoff
- Hybrid Docker image acquisition: pull-if-published, otherwise build from a pinned Pearl ref
- On-demand telemetry via Pearl gateway `:8339/metrics`; `mining_session_id` nullable column on telemetry inference rows
- v2 seams: `submit_target` tagged-union parsing, zero-valued `fee_bps` / `fees_owed` plumbing, reserved `mining/pools/` location
- Test strategy that doesn't require an H100 in CI
- Documentation: `docs/user-guide/mining.md`, `docs/development/mining.md`, `CLAUDE.md` paragraph, `REVIEW.md` bullet

### Out of scope (v1) — deferred or owned elsewhere
- Pool support and the 20% OJ fee mechanism (own spec, v2)
- Custody, signing, or routing Pearl funds (anti-goal — must remain zero in v1)
- Apple Silicon, AMD ROCm, sm89 (RTX 4090) NVIDIA, CPU, MLX, Ollama, llama.cpp, SGLang mining paths (Spec B for Apple; remaining hardware/engine paths blocked on Pearl)
- Wallet generation, Oyster integration, key custody (paste-only address)
- pearld lifecycle management (BYO node)
- Background telemetry collection in OJ's gateway daemon (v1.x; the hook point is reserved)
- Inference-quality drift detection (v1.x at earliest)
- `mine doctor --fix` automatic remediation (v1.x stub)
- Multi-GPU / multi-worker / multi-session per host (v2+)

## 3. Load-bearing decisions from brainstorming

These were the forks where the design could have gone several ways. Recorded so future-readers can audit reasoning rather than re-derive it.

| Decision | What we picked | Why |
|---|---|---|
| Target audience for v1 | H100/H200 owners running vLLM (Pearl's only working config today) | Anything broader is blocked on Pearl shipping non-CUDA / non-vLLM plugins. Power-user MVP ships in weeks; pool/fee/Apple are separate specs. |
| Mining model | Co-located: every inference through the Pearl-flavored vLLM is mining work | Matches Pearl's `vllm-miner` plugin design and OJ's Intelligence-Per-Watt thesis. Side-car deferred until Pearl ships plugins for engines users care about for non-mining inference. |
| Coupling to Pearl miner process | Wrap-and-launch via Docker | Pearl's Docker image (or Dockerfile) is the most stable contract they expose. (1) "BYO miner" is too thin to be a feature; (3) running Pearl's `uv` workspace natively couples us to their build system. |
| Module placement | Sibling top-level subsystem `mining/` (peer to `engine/`, `agents/`) | Matches OJ's existing module pattern. `MinerRegistry` is a peer registry. Future non-vLLM providers slot in identically. |
| Engine attachment | Runtime sidecar JSON at `~/.openjarvis/runtime/mining.json` | Existing vLLM engine class stays untouched. Sidecar is the single source of truth tying mining lifecycle to engine resolution. Inspectable via `cat`. |
| Config shape | Flat top-level `[mining]` TOML section | Only one provider in v1; nested per-engine config can grow later if multi-provider becomes real. |
| Wallet handling | Paste-only Pearl Taproot address | Keys are sensitive; Pearl's wallet RPC is unstable surface. v1.x can add Oyster integration once the contract stabilizes. |
| pearld | BYO; user points OJ at their own node | OJ doesn't orchestrate L1 nodes. Doctor surfaces unreachable cleanly. |
| Telemetry collection | On-demand reads in v1; persistent collector class shipped unwired (`MiningTelemetryCollector`) | Most users won't enable mining; daemon shouldn't grow surface for them. v1.x lights up the hook with zero API churn. |
| v1 fee/pool seams | Three seams: `submit_target` parsed (one variant works), `fee_bps`/`fees_owed` plumbed at zero, `mining/pools/` reserved | Cheap to leave; painful to retrofit. Does not pre-decide the v2 API. |
| Custody | **Anti-goal**: zero. v1 must not accept, sign, or route Pearl funds. | Avoids prematurely binding a legal/regulatory posture. v2 revisits as part of pool design. |
| Apple Silicon support | Not in v1. Designed-for via the `MiningProvider` ABC + `MiningCapabilities.detect()`. Spec B documents the enablement work. | The Pearl `pearl-gemm` kernel is heavily Hopper-bound (`sm_90a`, WGMMA, TMA, cluster mode, CUTLASS 3.x). A Metal port is real GPU-kernel engineering, not a config flag. |

## 4. Architecture & module layout

### 4.1 New module tree

```
src/openjarvis/mining/
    __init__.py          # soft-imports providers (try/except ImportError)
    _stubs.py            # MiningProvider ABC + dataclasses (MiningCapabilities, MiningConfig, MiningStats, SoloTarget, PoolTarget)
    _discovery.py        # detect_providers(hardware, engine, model) -> list[MiningCapabilities]
    _docker.py           # PearlDockerLauncher — shared Docker orchestration (image acquisition + container lifecycle)
    _collector.py        # MiningTelemetryCollector class — defined but UNWIRED in v1; lit up in v1.x
    _constants.py        # PEARL_REPO, PEARL_PINNED_REF, PEARL_IMAGE_TAG, OJ default tag
    vllm_pearl.py        # @MinerRegistry.register("vllm-pearl") — only impl in v1
    pools/               # RESERVED for v2. Empty in v1 except for an __init__.py with a docstring saying so.

src/openjarvis/cli/
    mine_cmd.py          # jarvis mine init|start|stop|status|doctor|attach|logs

tests/mining/
    __init__.py
    conftest.py          # mining-specific fixtures (synthetic HardwareInfo, sample Prometheus output)
    fixtures/
        gateway_metrics_sample.txt   # captured Prometheus output from a real Pearl run
        config_*.toml                # golden TOML files
    test_stubs.py
    test_discovery.py
    test_docker.py
    test_collector.py
    test_vllm_pearl.py
    test_cli.py
```

### 4.2 Registry additions

`MinerRegistry` added to `src/openjarvis/core/registry.py` as a peer to `EngineRegistry`, `AgentRegistry`, etc. `tests/conftest.py`'s autouse `_clean_registries` fixture is updated to include `MinerRegistry.clear()`.

`mining/vllm_pearl.py` exposes idempotent `ensure_registered()`:

```python
def ensure_registered() -> None:
    if not MinerRegistry.contains("vllm-pearl"):
        MinerRegistry.register_value("vllm-pearl", VllmPearlProvider)
```

`mining/__init__.py` soft-imports `vllm_pearl` inside `try / except ImportError` and calls `ensure_registered()`. Standard OJ pattern.

### 4.3 Optional-deps extras

```toml
mining-pearl       = ["docker>=7.0"]   # v1 requires only the Docker SDK
# mining-pearl-mlx   = [...]            # future, owned by Spec B
# mining-pearl-rocm  = [...]            # future
```

### 4.4 The central ABC

```python
# src/openjarvis/mining/_stubs.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from openjarvis.core.config import HardwareInfo

@dataclass(slots=True)
class MiningCapabilities:
    supported: bool
    reason: str | None = None              # human-readable: "needs sm90", "no Pearl plugin for engine ollama"
    estimated_hashrate: float | None = None

@dataclass(slots=True)
class SoloTarget:
    pearld_rpc_url: str

@dataclass(slots=True)
class PoolTarget:
    url: str
    worker_id: str | None = None

SubmitTarget = SoloTarget | PoolTarget

@dataclass(slots=True)
class MiningConfig:
    provider: str                          # MinerRegistry key
    wallet_address: str
    submit_target: SubmitTarget            # parsed from TOML "solo" / "pool:<url>"; v1 accepts only SoloTarget at runtime
    fee_bps: int = 0                       # v1: 0; v2: 2000 (=20%)
    fee_payout_address: str | None = None  # v1: ignored; v2: OJ's address
    extra: dict = field(default_factory=dict)

@dataclass(slots=True)
class MiningStats:
    provider_id: str
    shares_submitted: int = 0
    shares_accepted: int = 0
    blocks_found: int = 0
    hashrate: float = 0.0
    uptime_seconds: float = 0.0
    last_share_at: float | None = None
    last_error: str | None = None
    payout_target: str = "solo"            # v2 reporting; "solo" in v1
    fees_owed: int = 0                     # v2 accounting hook; 0 in v1

class MiningProvider(ABC):
    provider_id: str

    @classmethod
    @abstractmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities: ...

    @abstractmethod
    async def start(self, config: MiningConfig) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    def is_running(self) -> bool: ...
    @abstractmethod
    def stats(self) -> MiningStats: ...
```

## 5. Config schema & engine attachment

### 5.1 TOML schema

```toml
[mining]
provider                = "vllm-pearl"               # MinerRegistry key
wallet_address          = "prl1q..."                 # user's Pearl Taproot address (paste-only)
submit_target           = "solo"                     # v1: "solo" only; "pool:<url>" raises NotImplementedError at start()
fee_bps                 = 0                          # v1: 0; v2: 2000
fee_payout_address      = ""                         # v1: ignored; v2: OJ's address

[mining.extra]
docker_image_tag         = "openjarvis/pearl-miner:<pinned-ref>"
model                    = "pearl-ai/Llama-3.3-70B-Instruct-pearl"
gateway_port             = 8337
gateway_metrics_port     = 8339
vllm_port                = 8000
gpu_memory_utilization   = 0.9
max_model_len            = 8192
pearld_rpc_url           = "http://localhost:44107"
pearld_rpc_user          = "rpcuser"
pearld_rpc_password_env  = "PEARLD_RPC_PASSWORD"     # name of env var, not the secret
hf_token_env             = "HF_TOKEN"                # name of env var
```

Secrets: env-var *names*, never literal values. Matches OJ's existing convention for cloud API keys.

### 5.2 JarvisConfig field

`core/config.py` adds:

```python
@dataclass(slots=True)
class JarvisConfig:
    ...
    mining: MiningConfig | None = None
```

The TOML loader reads `[mining]`, parses `submit_target` into `SoloTarget | PoolTarget`, validates against the dataclass, surfaces unknown `extra` keys as warnings. Absent section → `mining = None` → zero behavior change.

### 5.3 Runtime sidecar

`~/.openjarvis/runtime/mining.json` (created on `mine start`, removed on `mine stop`):

```json
{
  "provider": "vllm-pearl",
  "vllm_endpoint": "http://127.0.0.1:8000/v1",
  "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
  "gateway_url": "http://127.0.0.1:8337",
  "gateway_metrics_url": "http://127.0.0.1:8339",
  "container_id": "abc123...",
  "wallet_address": "prl1q...",
  "started_at": 1714867200
}
```

Sidecar deliberately omits all secrets and process IDs. `container_id` is the authoritative handle (Docker is the source of truth for liveness); `wallet_address` is captured for drift-detection (config-vs-runtime).

### 5.4 Engine handoff flow

1. `jarvis mine start` → `MinerRegistry.get("vllm-pearl").start(config)`.
2. `VllmPearlProvider.start()` calls `_docker.PearlDockerLauncher.start(config)` and writes the sidecar.
3. `engine/_discovery.py` checks for `mining.json` on every engine lookup. When present, it auto-registers a `vllm` engine instance pointing at `vllm_endpoint`, named `vllm-pearl-mining`, marked default for mining-aware operations.
4. `jarvis ask` and the SDK route to that endpoint transparently. The user's normal inference is the mining work.

The vLLM engine class itself (`engine/openai_compat_engines.py`) is **not modified**. The change to `engine/_discovery.py` is small and additive: it inspects for `mining.json` and registers a derived `vllm` instance pointing at the mining endpoint when the sidecar is present. Absent sidecar → unchanged discovery behavior.

### 5.5 Manual mode

Power users running their own Pearl container skip `jarvis mine start` and write the sidecar themselves via `jarvis mine attach --vllm-endpoint=... --gateway-url=...`. Decouples lifecycle from wiring.

## 6. CLI surface, lifecycle & daemon integration

### 6.1 Subcommands

| Command | Purpose |
|---|---|
| `jarvis mine init` | Interactive: hardware/Docker checks, prompt for wallet + pearld credentials, write `[mining]`, pull/build image. Does NOT start mining. Pre-checks `>=200 GB` free disk. |
| `jarvis mine start` | Launch container via the registered provider, write sidecar, print endpoint info. Idempotent if running. |
| `jarvis mine stop` | Stop container, remove sidecar. Idempotent if not running. |
| `jarvis mine status` | Read sidecar + query gateway `:8339/metrics`. Print `MiningStats`. |
| `jarvis mine doctor` | Capability matrix; every check ✓/✗ with reason. Works in any state. |
| `jarvis mine attach` | Manual mode: write sidecar without launching. |
| `jarvis mine logs [-f]` | Tail container logs through Docker SDK. |

### 6.2 Doctor output (canonical example)

```
$ jarvis mine doctor
Hardware
  GPU vendor          nvidia                           ✓
  Compute capability  sm_90a                           ✓
  VRAM                80 GB                            ✓  (need ≥ 70 GB for Pearl 70B)
Docker
  Daemon              running 24.0.7                   ✓
  GPU runtime         nvidia-container-toolkit         ✓
Disk
  Free in HF cache    312 GB                           ✓  (need ≥ 200 GB)
Image
  openjarvis/pearl-miner:<ref>   present (built 2026-04-30)   ✓
Pearl node
  RPC                 http://localhost:44107           ✓
  Auth                ok                               ✓
  Block height        442107 (synced)                  ✓
Wallet
  Address format      prl1q...                         ✓
Provider capability
  vllm-pearl          SUPPORTED
Session
  Sidecar             absent (not running)
  Container           —
```

Each row maps to one check function in `mining/_discovery.py`. Failures print actionable reasons (e.g. `✗  reason: needs sm90, you have sm89 (RTX 4090)`).

### 6.3 Lifecycle states

```
NOT_CONFIGURED  →  CONFIGURED  →  STARTING  →  RUNNING  ⇄  STOPPING  →  STOPPED
                                       ↘
                                       FAILED
```

State derivation rules (no separate state file — derived from config + sidecar + container introspection):

- `NOT_CONFIGURED` — no `[mining]` in config
- `CONFIGURED` — config present, no sidecar
- `STARTING` — sidecar with `started_at` < ~30 s ago, container exists but gateway not yet healthy
- `RUNNING` — sidecar present, container running, gateway responding
- `FAILED` — sidecar present, but container exited or gateway failing > threshold
- `STOPPING` — `mine stop` invoked, Docker stop in progress
- `STOPPED` — `mine stop` complete, sidecar removed

### 6.4 Daemon integration: deliberately minimal in v1

- Docker handles container restart via `--restart=unless-stopped`. OJ does not babysit.
- Existing `com.openjarvis.gateway` daemon is unchanged.
- v1.x hook: `MiningTelemetryCollector` (already shipped in v1, unwired) can be added to the gateway as a 30-second-tick async task.
- launchd/systemd installation surface (`jarvis daemon install`) untouched.

### 6.5 Concurrency

POSIX `flock` on `~/.openjarvis/runtime/mining.lock` prevents racing `mine start` invocations.

### 6.6 `jarvis ask` UX hint

When `[mining]` is configured but no sidecar exists, `cli/hints.py` emits one line: `"mining configured but not running — start it with \`jarvis mine start\`"`. One-line UX nudge, no new infrastructure.

## 7. Pearl Docker integration

### 7.1 Realities from inspecting Pearl's repo

- **Build context = entire Pearl monorepo.** Dockerfile copies root `pyproject.toml`/`uv.lock`, `miner/`, `pearl-blake3/`, `py-pearl-mining/`, `zk-pow/`, `plonky2/`. Building requires the full repo.
- **Pearl publishes no registry image as of writing.** README documents only `docker buildx build -t vllm_miner . -f miner/vllm-miner/Dockerfile`.
- **Single container, three ports.** `entrypoint.sh` launches `pearl-gateway` in the background, waits on `:8339/metrics`, then `exec`s `vllm serve`. Ports: `8000` (vLLM), `8337` (miner RPC), `8339` (gateway metrics).
- **Pinned stack inside the image.** CUDA 12.9.1, vLLM 0.20.0+cu129, Python 3.12, `compute_90a/sm_90a`. Set by Pearl, not by us.
- **First-launch cost.** vLLM pulls the 70 B model from HF on first serve (~140 GB). Build itself is 30–60 min on first init.

### 7.2 Hybrid image acquisition

| Mode | Behavior | When |
|---|---|---|
| **Pre-built pull** | OJ `docker pull`s the configured tag if it resolves in a registry | Default once Pearl publishes; users with private registry; CI |
| **Build-from-pin** | OJ git-clones Pearl at a pinned ref into `~/.openjarvis/cache/pearl/`, then `docker buildx build` | v1 default (Pearl publishes nothing today) |
| **BYO image** | User sets `mining.extra.docker_image_tag` to an image they built/pulled themselves | Power users, air-gapped envs |

Selection logic in `_docker.PearlDockerLauncher.ensure_image()`:
1. If `docker_image_tag` resolves locally → use it.
2. Else `docker pull <tag>` → on success, use it.
3. Else if `tag == OJ_DEFAULT_TAG`, fall back to clone-and-build from `PEARL_PINNED_REF`.
4. Else fail with a clear error pointing at `mine doctor`.

### 7.3 Pearl version pinning

`mining/_constants.py`:

```python
PEARL_REPO       = "https://github.com/pearl-research-labs/pearl.git"
PEARL_PINNED_REF = "<sha-or-tag>"            # bumped per OJ release after rev-testing
PEARL_IMAGE_TAG  = f"openjarvis/pearl-miner:{PEARL_PINNED_REF}"
```

OJ release notes call out the Pearl ref shipped. Bumping the ref is its own PR with a documented Pearl-rev workflow.

### 7.4 Container launch shape

Via `docker>=7.0` SDK in `_docker.PearlDockerLauncher.start()`:

```python
container = client.containers.run(
    image=PEARL_IMAGE_TAG,
    command=[
        config.extra["model"],
        "--host", "0.0.0.0",
        "--port", str(config.extra["vllm_port"]),
        "--gpu-memory-utilization", str(config.extra["gpu_memory_utilization"]),
        "--enforce-eager",
        "--max-model-len", str(config.extra.get("max_model_len", 8192)),
    ],
    name="openjarvis-pearl-miner",
    detach=True,
    auto_remove=False,
    restart_policy={"Name": "unless-stopped"},
    device_requests=[ DeviceRequest(count=-1, capabilities=[["gpu"]]) ],
    shm_size="8g",
    network_mode="host",
    volumes={
        str(Path.home() / ".cache/huggingface"): {
            "bind": "/root/.cache/huggingface",
            "mode": "rw",
        },
    },
    environment={
        "PEARLD_RPC_URL":         config.extra["pearld_rpc_url"],
        "PEARLD_RPC_USER":        config.extra["pearld_rpc_user"],
        "PEARLD_RPC_PASSWORD":    os.environ[config.extra["pearld_rpc_password_env"]],
        "PEARLD_MINING_ADDRESS":  config.wallet_address,
        "HF_TOKEN":               os.environ.get(config.extra.get("hf_token_env", "HF_TOKEN"), ""),
        "MINER_RPC_TRANSPORT":    "tcp",
    },
)
```

### 7.5 Trade-offs called out

- **`network_mode="host"`** because pearld's RPC at `http://localhost:44107` lives on the host. A user-defined Docker network adds setup steps with no real isolation benefit on a single-tenant miner box. Pragmatism > purity. Note: host networking has Linux semantics; macOS/Windows Docker handle it differently. Acceptable for v1 since H100/H200 + nvidia-container-toolkit constrains the deployment to Linux anyway.
- **`auto_remove=False`** so a crashed container stays around for `jarvis mine logs` post-mortem.
- **HF cache mounted from host.** 140 GB weight download is one-time, survives container restarts, visible to other tools.
- **Secrets via env-var names**, never persisted in the container image, the sidecar, or Docker labels.

### 7.6 Wallet handling boundary

OJ never sees Pearl mnemonic seeds, never imports Oyster keys, never signs Pearl transactions. Only Pearl-secret OJ touches is the pearld RPC password (passed through container env, sourced by name from host env). Mining address is public — fine in plaintext config.

### 7.7 Image lifecycle UX

- `jarvis mine init` triggers `ensure_image()`, streams build/pull output through the CLI with a clear time estimate (`"Building Pearl miner image — first run takes ~45 min on a fast machine"`).
- `jarvis mine doctor` reports `image: present (tag, age, sha)` or `image: missing (run mine init)`.
- `jarvis mine prune` (v1.x) cleans old `openjarvis/pearl-miner:*` tags. Manual `docker image rm` works in v1.

## 8. Telemetry hooks & v2 fee/pool seams

### 8.1 Telemetry — read surface

Pearl's container exposes `:8339/metrics` (Prometheus exposition format). v1 reads only this endpoint. Deeper RPC introspection via `:8337` deferred to v2.

### 8.2 Adapter and metric mapping

`mining/vllm_pearl.py::_parse_gateway_metrics()` translates Prometheus lines to `MiningStats`. Metric names are TBD on implementation — verified against captured fixture `tests/mining/fixtures/gateway_metrics_sample.txt`. Expected mapping (fallback: zero-fill any missing field, log a one-shot warning):

| `MiningStats` field | Likely Pearl metric (verify on implementation) |
|---|---|
| `shares_submitted` | `pearl_gateway_shares_submitted_total` |
| `shares_accepted` | `pearl_gateway_shares_accepted_total` |
| `blocks_found` | `pearl_gateway_blocks_found_total` |
| `hashrate` | derived rate of `shares_submitted_total` |
| `uptime_seconds` | `process_start_time_seconds` |
| `last_share_at` | `pearl_gateway_last_share_timestamp` |
| `last_error` | derived from `pearl_gateway_errors_total` deltas |

### 8.3 Collection cadence

- **v1: on-demand only.** `jarvis mine status` makes one HTTP GET per call (~10 ms). No background polling.
- **v1.x: `MiningTelemetryCollector` lit up in the gateway daemon.** The class is shipped in v1 but unwired. v1.x adds a periodic asyncio task; same `MiningStats` schema, same gateway endpoint. Zero API churn.

### 8.4 Intelligence-Per-Watt extension

The `telemetry/store.py` schema gains a nullable `mining_session_id` column on inference rows:

- Tagged when an inference goes through the Pearl-mining endpoint; null otherwise.
- Untagged rows behave exactly as today — zero impact on the non-mining path.
- `jarvis telemetry stats --mining` (v1.x) joins to the latest `MiningStats` snapshot and reports `tokens / share`, `joules / share`, `est. PRL / kWh`.

v1 ships the column and the no-op join path. v1.x lights up the reporting. This is the metric the IPW thesis genuinely cares about.

### 8.5 v2 fee/pool seams (three concrete, no more)

**1. `submit_target` parsed into a tagged union; only one variant works.** `SoloTarget` accepted at runtime in v1; `PoolTarget` raises `NotImplementedError("pool support is v2 — track openjarvis#XYZ")`. Reachable only by users who edit their config to opt in.

**2. `fee_bps` / `fee_payout_address` plumbed; zero-valued in v1.** `MiningStats.fees_owed = 0` and `MiningStats.payout_target = "solo"` always in v1. Schema is real; values are zero. No migration in v2.

**3. `mining/pools/` module location reserved.** Empty in v1 except for an `__init__.py` whose docstring says the location is reserved for v2 `PoolClient` work. The v1 spec **does not** define a `PoolClient` ABC — predicting the v2 API precisely creates migration debt. The v2 spec writes against an empty slot.

### 8.6 What v1 deliberately does not lock in

- Pool protocol (PPLNS / PPS / SOLO+ / custom)
- Custody model (escrow / trustless split-coinbase / settlement contract)
- OJ pool URL, share format, share difficulty
- KYC / TOS / payout thresholds

### 8.7 Custody anti-goal

v1 must not introduce any code path where OJ accepts custody of, signs, or routes Pearl funds. Closest v1 comes is reading `wallet_address` (public) and passing it through to the container. v2 revisits.

### 8.8 Single-session assumption (called out, not seamed)

v1 assumes one mining session per host (one sidecar). Multi-GPU / multi-worker fanout is v2+. Sidecar would become a list or directory.

## 9. Failure handling & test strategy

### 9.1 Principles

1. **Fail loud, don't auto-heal.** Docker handles container restarts; `mine doctor` surfaces what's wrong. OJ does not retry mining work, restart pearld, or paper over crashes.
2. **`mine doctor` is the canonical failure surface.** Every failure mode below maps to one or more rows in doctor output.
3. **Sidecar is authoritative; config is intent.** Drift surfaces as a warning, not a crash.

### 9.2 Failure mode matrix

| Failure | v1 behavior | Surface |
|---|---|---|
| Image missing | `mine start` errors with "run `mine init` to build/pull" | `mine doctor: image: missing` |
| GPU not reachable in container | Docker error with `nvidia-container-toolkit` hint | `mine doctor: docker.gpu_runtime: ✗` |
| Disk too low | `mine init` pre-checks `shutil.disk_usage`; errors if < 200 GB free | `mine doctor: disk_free: ✗` |
| vLLM model load fails (HF auth, OOM, model not found) | Container exits; `mine status` reports `FAILED` with `last_error` from `docker logs` tail | `mine status` + `mine logs` |
| pearl-gateway can't reach pearld | `:8339/metrics` exposes the error; adapter populates `MiningStats.last_error` | `mine status: last_error` |
| Container crashes mid-run | Docker `--restart=unless-stopped` restarts; `mine status` shows brief `STARTING` → `RUNNING` | self-healing, logged |
| Stale sidecar (container died, sidecar not cleaned) | `mine start` validates `container_id`; if Docker says it's gone, removes sidecar and proceeds | one-line warning |
| Concurrent `mine start` | POSIX `flock` on `~/.openjarvis/runtime/mining.lock`; second invocation errors clearly | clear message |
| Already-running `mine start` | Idempotent: detect via sidecar + container introspection, print status, exit 0 | informational |
| Wallet/config drift | Sidecar carries wallet from start time; `mine status` cross-checks and warns on mismatch | warning, not auto-restart |
| User edits `submit_target = "pool:..."` in v1 | `start()` raises `NotImplementedError` with tracking issue link | clear error |
| Pearl protocol upgrade (block format / metric names change) | Adapter zero-fills with one-shot warning. `mine doctor` does a best-effort check: it reads the `image: openjarvis/pearl-miner:<ref>` Docker label and compares against `PEARL_PINNED_REF` baked into the OJ release; mismatch surfaces a warning. **OJ does not poll Pearl's GitHub at runtime.** | warning + spec'd Pearl-rev workflow |
| Inference quality regression from NoisyGEMM | **Out of v1 scope to detect.** Documented risk; v1.x may add automated drift detection. | docs only |

### 9.3 Test strategy

Hard constraint: **OJ's CI has no H100, no GPU, no Pearl image, no pearld.** Almost everything must be testable without those.

| Layer | Pattern | Marker | Runs in CI? |
|---|---|---|---|
| `MiningCapabilities.detect()` matrix | Pure unit, parametrized over synthetic `HardwareInfo` | unmarked | yes |
| `MiningConfig` parsing (TOML → dataclass, including `submit_target` tagged-union) | Unit, golden TOML fixtures | unmarked | yes |
| Docker launch shape | `unittest.mock.patch("docker.from_env")`; assert `containers.run(...)` kwargs | unmarked | yes |
| Gateway metrics adapter | `tests/mining/fixtures/gateway_metrics_sample.txt`, parse + assert `MiningStats` | unmarked | yes |
| Sidecar lifecycle (write/read/stale-cleanup, `flock` acquisition) | `tmp_path`, real filesystem, real `flock` | unmarked | yes |
| CLI smoke | Click `CliRunner`, mocked `MiningProvider` | unmarked | yes |
| Container start/stop with real Docker daemon | Real Docker, swap Pearl image for tiny stub `alpine`-based image opening the right ports | new `docker` marker | optional in CI |
| End-to-end mining (real container, real pearld, real shares) | Real H100 + pearld testnet + pinned Pearl image | `live and nvidia and slow` | **no** — manual pre-release smoke |

**New pytest marker.** `docker` registered alongside `live`, `cloud`, `nvidia`, etc. in `pyproject.toml`. CI matrix optionally runs `-m "docker and not live"` on a Docker-enabled runner.

**Conftest hygiene.** `tests/conftest.py`'s autouse fixture clears `MinerRegistry`. `mining/__init__.py`'s `ensure_registered()` survives the autouse clear via `MinerRegistry.contains(...)`.

**Captured Prometheus fixture.** Real metrics output from a Pearl gateway run, committed to the repo. Pins the metric-name assumptions and is the canary if Pearl renames metrics.

### 9.4 What v1 deliberately does not test

- Mining throughput/economics on a real H100 (Pearl's CI tests their kernels)
- Inference quality drift from NoisyGEMM (out of v1 scope)
- Pool share submission paths (v2 spec)
- Apple Silicon paths (Spec B)

## 10. Documentation deliverables (part of this spec)

- `docs/user-guide/mining.md` — user-facing: prerequisites, init flow, doctor output reading guide, `mine status` interpretation, deliberately-unsupported list (Mac, AMD, sm89, non-vLLM engines)
- `docs/development/mining.md` — for contributors: `MiningProvider` ABC, registry pattern, how to add a new provider (Spec B is the canonical worked example)
- One paragraph in `CLAUDE.md` under "Architecture" pointing future-Claude at `mining/` as a sibling subsystem with its own optional-deps discipline
- `REVIEW.md` gets a new bullet under registry compliance specifically calling out `MinerRegistry`

## 11. Open items to resolve at implementation time

1. **Pearl gateway metric names.** Verify the actual exposition labels by capturing `:8339/metrics` from a running Pearl gateway. Update the adapter mapping and commit the fixture.
2. **`PEARL_PINNED_REF`.** Pick a specific commit/tag at the start of implementation. Document the rev-bump workflow.
3. **The `pearl-ai/Llama-3.3-70B-Instruct-pearl` HF model.** Confirm it exists and is gated/ungated; document HF auth requirements.
4. **Pearl Taproot address regex.** Confirm the prefix and length for `mine doctor`'s address-format check.
5. **Pearl `:8337` miner RPC TCP port behavior.** Confirm `MINER_RPC_TRANSPORT=tcp` works as documented and binds to `0.0.0.0` not just `127.0.0.1` inside the host network namespace.
6. **OJ default Docker image tag.** Decide whether to publish to GHCR/Docker Hub once we have a build, or leave users on build-from-pin. Likely v1.x.
7. **Wallet generation hand-off (v1.x).** Decide whether `mine init` shells out to Pearl's `oyster` for users who want guidance, or stays paste-only.
8. **Telemetry schema migration approach.** Adding the nullable `mining_session_id` column to `telemetry/store.py` is a SQLite schema change. Decide between (a) `ALTER TABLE` on first start with a guarded `PRAGMA user_version` bump, (b) per-query `try/except` on the column, or (c) creating a sidecar table joined on inference id. Confirm what convention OJ already uses for `telemetry/` schema evolution before picking; default lean is (a).

## 12. Cross-references

- **[Spec B — Apple Silicon enablement](2026-05-05-apple-silicon-pearl-mining-design.md)** — separate effort tracking the Pearl-side and OJ-side work to make Apple Silicon a registered `MiningProvider`. Spec A is engine-agnostic by design; Spec B drops in via `MinerRegistry` without modifying anything in this spec.
- **Pearl repo:** [`pearl-research-labs/pearl`](https://github.com/pearl-research-labs/pearl) — referenced sub-paths: `miner/vllm-miner/`, `miner/pearl-gemm/`, `miner/pearl-gateway/`, `miner/vllm-miner/Dockerfile`, `miner/vllm-miner/entrypoint.sh`.
- **Pearl paper:** [Proof-of-Useful-Work via matrix multiplication (arXiv:2504.09971)](https://arxiv.org/abs/2504.09971).
- **OJ contributing guide:** `docs/development/contributing.md` — registry pattern, `_stubs.py` / `_discovery.py` conventions, `ensure_registered()` discipline, optional-deps soft-import pattern. All followed in this spec.

## 13. Implementation plan

The implementation plan for Spec A is a separate document, written via the `superpowers:writing-plans` skill after this design is approved by the user. It will decompose section 4–9 above into ordered, independently-reviewable steps and call out which steps can be parallelized.
