# vLLM-Pearl mining integration — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Spec A — the v1 vLLM-Pearl mining integration — as a new `openjarvis.mining` subsystem that lets H100/H200 owners running vLLM solo-mine the Pearl PoUW chain with their normal LLM inference.

**Architecture:** New top-level subsystem `mining/` mirrors OJ's existing primitive pattern (peer to `engine/`, `agents/`). A `MiningProvider` ABC + `MinerRegistry` enables future hardware/engine paths (Apple Silicon, AMD, Ollama) without rewrite. The v1 `vllm-pearl` provider orchestrates Pearl's published Docker container; a runtime sidecar at `~/.openjarvis/runtime/mining.json` decouples mining lifecycle from the existing vLLM engine class. Three deliberate seams (`submit_target` tagged-union, zero-valued `fee_bps`/`fees_owed`, reserved `mining/pools/`) leave room for v2 pool support without retrofit pain.

**Tech Stack:** Python 3.10+, `docker>=7.0` SDK, Click CLI, pytest with `unittest.mock`, ruff, uv. References Pearl repo (`pearl-research-labs/pearl`) at a pinned commit/tag.

**Spec reference:** [`docs/design/2026-05-05-vllm-pearl-mining-integration-design.md`](./2026-05-05-vllm-pearl-mining-integration-design.md). Read it before starting. Section numbers in the plan refer to that spec.

**Critical conventions for any agent picking this up:**

- All new modules begin with `from __future__ import annotations`.
- All dataclasses use `@dataclass(slots=True)`.
- Absolute imports only (`from openjarvis.core.registry import ...`).
- Optional dependencies live behind `try / except ImportError` in the parent `__init__.py`.
- Tests in `tests/conftest.py` autouse-clear all registries — the `ensure_registered()` pattern (idempotent registration guarded by `XRegistry.contains(...)`) is required for components that need to survive the autouse clear.
- File-naming: `_stubs.py` (ABC + dataclasses), `_discovery.py` (auto-detection), `*_cmd.py` (CLI commands).

**Branch posture:** This plan is added to the existing branch `docs/pearl-mining-design-specs` as a follow-up commit on the same PR (#310). Implementation work will branch off `main` separately once the spec + plan are merged.

---

## File structure

### Created

| Path | Responsibility |
|---|---|
| `src/openjarvis/mining/__init__.py` | Package init; soft-imports providers via `try/except ImportError` |
| `src/openjarvis/mining/_stubs.py` | `MiningProvider` ABC, `MiningCapabilities`, `MiningConfig`, `MiningStats`, `SoloTarget`/`PoolTarget` tagged union, `Sidecar` dataclass + read/write helpers |
| `src/openjarvis/mining/_discovery.py` | `detect_providers()`, hardware/Docker/disk/pearld checks, wallet-format check |
| `src/openjarvis/mining/_constants.py` | `PEARL_REPO`, `PEARL_PINNED_REF`, `PEARL_IMAGE_TAG`, default ports, default model, sidecar path constants |
| `src/openjarvis/mining/_docker.py` | `PearlDockerLauncher` — `ensure_image()`, `start()`, `stop()`, `is_running()`, `get_logs()` |
| `src/openjarvis/mining/_collector.py` | `MiningTelemetryCollector` — full impl, shipped unwired in v1; v1.x lights it up in the gateway daemon |
| `src/openjarvis/mining/vllm_pearl.py` | `VllmPearlProvider` (`MiningProvider` impl); `_parse_gateway_metrics()`; `ensure_registered()` |
| `src/openjarvis/mining/pools/__init__.py` | Reserved location for v2 `PoolClient` work — empty except for a docstring saying so |
| `src/openjarvis/cli/mine_cmd.py` | `jarvis mine` Click group: `init`, `start`, `stop`, `status`, `doctor`, `attach`, `logs` |
| `tests/mining/__init__.py` | Empty test package init |
| `tests/mining/conftest.py` | Mining-specific fixtures: synthetic `HardwareInfo`, mock Docker client factory, sample sidecar tmp_path |
| `tests/mining/fixtures/gateway_metrics_sample.txt` | Real Prometheus output captured from a Pearl gateway run (one snapshot, committed) |
| `tests/mining/fixtures/config_minimal.toml` | Minimal valid `[mining]` config |
| `tests/mining/fixtures/config_pool_v2.toml` | TOML with `submit_target = "pool:..."` for testing the v2-seam `NotImplementedError` |
| `tests/mining/test_stubs.py` | Tests for ABC contract, dataclass invariants, sidecar IO |
| `tests/mining/test_discovery.py` | Tests for capability detection matrix |
| `tests/mining/test_docker.py` | Tests for `PearlDockerLauncher` with mocked Docker SDK |
| `tests/mining/test_collector.py` | Tests for `MiningTelemetryCollector` |
| `tests/mining/test_vllm_pearl.py` | Tests for `VllmPearlProvider` end-to-end (mocked Docker + filesystem) |
| `tests/mining/test_cli.py` | CLI smoke tests via Click `CliRunner` |
| `docs/user-guide/mining.md` | User-facing docs |
| `docs/development/mining.md` | Contributor guide for adding new providers |

### Modified

| Path | Change |
|---|---|
| `src/openjarvis/core/registry.py` | Add `MinerRegistry` class + entry in `__all__` |
| `src/openjarvis/core/config.py` | Add `MiningConfig` field to `JarvisConfig`; add TOML parser for `[mining]` with `submit_target` tagged-union resolution |
| `src/openjarvis/engine/_discovery.py` | Add sidecar-aware engine resolution: when `~/.openjarvis/runtime/mining.json` exists, register a derived `vllm` engine pointing at `vllm_endpoint` |
| `src/openjarvis/telemetry/store.py` | Add nullable `mining_session_id` column to inference rows; bump `PRAGMA user_version`; helper to tag rows when sidecar is present |
| `src/openjarvis/cli/__init__.py` | Register the `mine` Click group |
| `src/openjarvis/cli/hints.py` | Add hint: "mining configured but not running — start it with `jarvis mine start`" |
| `tests/conftest.py` | Add `MinerRegistry.clear()` to autouse `_clean_registries` fixture |
| `pyproject.toml` | Add `mining-pearl` extra; add `docker` pytest marker |
| `CLAUDE.md` | Add paragraph under Architecture pointing future-Claude at `mining/` as a sibling subsystem |
| `REVIEW.md` | Add bullet under registry compliance calling out `MinerRegistry` |

---

## Task 1 — Add `MinerRegistry`

**Files:**
- Modify: `src/openjarvis/core/registry.py`
- Modify: `tests/conftest.py`
- Test: `tests/core/test_registry.py` (existing file — add a new test)

- [ ] **Step 1: Write the failing test**

Add to `tests/core/test_registry.py`:

```python
def test_miner_registry_register_and_get():
    from openjarvis.core.registry import MinerRegistry

    class _Stub:
        provider_id = "stub-pearl"

    MinerRegistry.register_value("stub-pearl", _Stub)
    assert MinerRegistry.contains("stub-pearl") is True
    assert MinerRegistry.get("stub-pearl") is _Stub
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_registry.py::test_miner_registry_register_and_get -v
```
Expected: `ImportError` or `AttributeError` on `MinerRegistry`.

- [ ] **Step 3: Add `MinerRegistry` to `core/registry.py`**

Insert after `ConnectorRegistry` (around line 153):

```python
class MinerRegistry(RegistryBase[Any]):
    """Registry for Pearl mining provider implementations.

    Each provider implements the ``MiningProvider`` ABC defined in
    ``openjarvis.mining._stubs``. Registry keys are short lowercase strings
    such as ``"vllm-pearl"`` (CUDA + Hopper) and (future) ``"mlx-pearl"``,
    ``"llamacpp-pearl-metal"``, ``"ollama-pearl"``.
    """
```

Add `"MinerRegistry"` to `__all__` (alphabetical position between `MemoryRegistry` and `ModelRegistry`).

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_registry.py::test_miner_registry_register_and_get -v
```
Expected: PASS.

- [ ] **Step 5: Update `tests/conftest.py` autouse fixture**

In `tests/conftest.py`, add `MinerRegistry` to the imports and to the clear-list. The existing `_clean_registries` fixture lists every registry on its own line — insert `MinerRegistry.clear()` alphabetically between `MemoryRegistry.clear()` and `ModelRegistry.clear()`. Likewise add `MinerRegistry,` to the imports block.

- [ ] **Step 6: Verify autouse clear works**

Add a second test below the registration test:

```python
def test_miner_registry_cleared_between_tests():
    from openjarvis.core.registry import MinerRegistry
    # If autouse clear works, no entry from prior tests remains
    assert MinerRegistry.contains("stub-pearl") is False
```

```bash
uv run pytest tests/core/test_registry.py::test_miner_registry_register_and_get tests/core/test_registry.py::test_miner_registry_cleared_between_tests -v
```
Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/core/registry.py tests/conftest.py tests/core/test_registry.py
git commit -m "feat(mining): add MinerRegistry for mining providers"
```

---

## Task 2 — Mining package skeleton: constants, ABC, dataclasses, sidecar IO

**Files:**
- Create: `src/openjarvis/mining/__init__.py`
- Create: `src/openjarvis/mining/_constants.py`
- Create: `src/openjarvis/mining/_stubs.py`
- Create: `src/openjarvis/mining/pools/__init__.py`
- Create: `tests/mining/__init__.py`
- Create: `tests/mining/conftest.py`
- Create: `tests/mining/test_stubs.py`

- [ ] **Step 1: Create `tests/mining/__init__.py`**

Empty file.

- [ ] **Step 2: Create `tests/mining/conftest.py` with shared fixtures**

```python
"""Mining-specific test fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from openjarvis.core.config import GpuInfo, HardwareInfo


@pytest.fixture
def hopper_hw() -> HardwareInfo:
    """Hardware fixture: a typical H100 host."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC 7763",
        cpu_count=64,
        ram_gb=512.0,
        gpu=GpuInfo(
            vendor="nvidia",
            name="NVIDIA H100-SXM5-80GB",
            vram_gb=80.0,
            compute_capability="9.0",
            count=1,
        ),
    )


@pytest.fixture
def ada_hw() -> HardwareInfo:
    """Hardware fixture: RTX 4090 (sm_89, NOT supported by Pearl)."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Core i9-14900K",
        cpu_count=24,
        ram_gb=64.0,
        gpu=GpuInfo(
            vendor="nvidia",
            name="NVIDIA GeForce RTX 4090",
            vram_gb=24.0,
            compute_capability="8.9",
            count=1,
        ),
    )


@pytest.fixture
def apple_hw() -> HardwareInfo:
    """Hardware fixture: Apple Silicon (NOT supported in v1)."""
    return HardwareInfo(
        platform="darwin",
        cpu_brand="Apple M4 Max",
        cpu_count=16,
        ram_gb=128.0,
        gpu=GpuInfo(vendor="apple", name="Apple M4 Max", vram_gb=128.0, count=1),
    )


@pytest.fixture
def mock_docker_client() -> Any:
    """Factory for a mocked docker.DockerClient.

    Returns a MagicMock configured with the most common attribute paths so
    individual tests only need to override what they care about.
    """
    client = MagicMock()
    client.ping.return_value = True
    client.version.return_value = {"Version": "24.0.7"}
    client.images.list.return_value = []
    client.images.get.side_effect = Exception("not found")
    return client


@pytest.fixture
def sample_sidecar_payload() -> dict:
    return {
        "provider": "vllm-pearl",
        "vllm_endpoint": "http://127.0.0.1:8000/v1",
        "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
        "gateway_url": "http://127.0.0.1:8337",
        "gateway_metrics_url": "http://127.0.0.1:8339",
        "container_id": "abc123def456",
        "wallet_address": "prl1qexampleaddress",
        "started_at": 1714867200,
    }


@pytest.fixture
def sidecar_path(tmp_path: Path) -> Path:
    return tmp_path / "mining.json"


@pytest.fixture
def written_sidecar(sidecar_path: Path, sample_sidecar_payload: dict) -> Path:
    sidecar_path.write_text(json.dumps(sample_sidecar_payload))
    return sidecar_path
```

- [ ] **Step 3: Write the failing test for `_stubs.py`**

Create `tests/mining/test_stubs.py`:

```python
"""Tests for mining/_stubs.py — ABC contract, dataclass invariants, sidecar IO."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_mining_capabilities_default_unsupported():
    from openjarvis.mining._stubs import MiningCapabilities
    cap = MiningCapabilities(supported=False, reason="needs sm90")
    assert cap.supported is False
    assert cap.reason == "needs sm90"
    assert cap.estimated_hashrate is None


def test_solo_target_dataclass():
    from openjarvis.mining._stubs import SoloTarget
    t = SoloTarget(pearld_rpc_url="http://localhost:44107")
    assert t.pearld_rpc_url == "http://localhost:44107"


def test_pool_target_dataclass():
    from openjarvis.mining._stubs import PoolTarget
    t = PoolTarget(url="https://pool.example/submit", worker_id="rig01")
    assert t.url == "https://pool.example/submit"
    assert t.worker_id == "rig01"


def test_mining_config_v1_defaults():
    from openjarvis.mining._stubs import MiningConfig, SoloTarget
    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qexample",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
    )
    assert cfg.fee_bps == 0
    assert cfg.fee_payout_address is None
    assert cfg.extra == {}


def test_mining_stats_v1_defaults():
    from openjarvis.mining._stubs import MiningStats
    s = MiningStats(provider_id="vllm-pearl")
    assert s.shares_submitted == 0
    assert s.shares_accepted == 0
    assert s.fees_owed == 0
    assert s.payout_target == "solo"


def test_mining_provider_is_abstract():
    from openjarvis.mining._stubs import MiningProvider
    with pytest.raises(TypeError):
        MiningProvider()  # cannot instantiate ABC


def test_sidecar_write_then_read_roundtrip(sidecar_path: Path, sample_sidecar_payload: dict):
    from openjarvis.mining._stubs import Sidecar
    Sidecar.write(sidecar_path, sample_sidecar_payload)
    payload = Sidecar.read(sidecar_path)
    assert payload == sample_sidecar_payload


def test_sidecar_read_missing_returns_none(sidecar_path: Path):
    from openjarvis.mining._stubs import Sidecar
    assert Sidecar.read(sidecar_path) is None


def test_sidecar_remove_is_idempotent(sidecar_path: Path):
    from openjarvis.mining._stubs import Sidecar
    Sidecar.remove(sidecar_path)  # missing file — should not raise
    sidecar_path.write_text(json.dumps({"x": 1}))
    Sidecar.remove(sidecar_path)
    assert not sidecar_path.exists()
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
uv run pytest tests/mining/test_stubs.py -v
```
Expected: ALL fail with `ImportError` on `openjarvis.mining._stubs`.

- [ ] **Step 5: Create `_constants.py`**

```python
# src/openjarvis/mining/_constants.py
"""Constants for the Pearl mining subsystem.

Pinned Pearl ref OJ has tested against. Bumped per OJ release after
re-testing the integration end-to-end on a real H100/H200 host. See
spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``
section 7.3 for the rev-bump workflow.
"""

from __future__ import annotations

from pathlib import Path

PEARL_REPO = "https://github.com/pearl-research-labs/pearl.git"
# TODO at implementation time: replace with the specific commit/tag verified
# against H100. Document the chosen ref in the OJ release notes.
PEARL_PINNED_REF = "main"
PEARL_IMAGE_TAG = f"openjarvis/pearl-miner:{PEARL_PINNED_REF}"

# Default Pearl-blessed model. Overridable via [mining.extra].model.
DEFAULT_PEARL_MODEL = "pearl-ai/Llama-3.3-70B-Instruct-pearl"

# Default ports as Pearl's container exposes them (network_mode="host").
DEFAULT_VLLM_PORT = 8000
DEFAULT_GATEWAY_RPC_PORT = 8337
DEFAULT_GATEWAY_METRICS_PORT = 8339

# Default pearld RPC endpoint (mainnet).
DEFAULT_PEARLD_RPC_URL = "http://localhost:44107"

# Pre-flight free-disk requirement for the 70B model + headroom.
MIN_FREE_DISK_GB = 200

# Runtime sidecar location (single-session assumption — see spec §8.8).
RUNTIME_DIR = Path.home() / ".openjarvis" / "runtime"
SIDECAR_PATH = RUNTIME_DIR / "mining.json"
SIDECAR_LOCK_PATH = RUNTIME_DIR / "mining.lock"

# Pearl source cache for build-from-pin path (see spec §7.2).
PEARL_CACHE_DIR = Path.home() / ".openjarvis" / "cache" / "pearl"
```

- [ ] **Step 6: Create `_stubs.py`**

```python
# src/openjarvis/mining/_stubs.py
"""ABCs and dataclasses for the mining subsystem.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``
section 4.4 for the design rationale.
"""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from openjarvis.core.config import HardwareInfo


# ---------------------------------------------------------------------------
# Capability descriptor
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MiningCapabilities:
    """Result of a provider's ``detect()`` call.

    ``reason`` is human-readable and surfaced verbatim by ``jarvis mine doctor``
    when ``supported=False``.
    """

    supported: bool
    reason: Optional[str] = None
    estimated_hashrate: Optional[float] = None  # shares/sec, best-effort


# ---------------------------------------------------------------------------
# Submit-target tagged union (v2 seam — see spec §8.5)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SoloTarget:
    """Mine directly to a pearld node. v1 default."""

    pearld_rpc_url: str


@dataclass(slots=True)
class PoolTarget:
    """Mine through an OJ-operated pool. v2 — raises NotImplementedError in v1."""

    url: str
    worker_id: Optional[str] = None


SubmitTarget = Union[SoloTarget, PoolTarget]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MiningConfig:
    """User-supplied mining configuration.

    Loaded from the ``[mining]`` TOML section by ``core/config.py``.
    """

    provider: str
    wallet_address: str
    submit_target: SubmitTarget
    fee_bps: int = 0  # v1: 0; v2: 2000 (=20%)
    fee_payout_address: Optional[str] = None  # v1: ignored; v2: OJ's address
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Live stats (returned by ``MiningProvider.stats()``)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MiningStats:
    provider_id: str
    shares_submitted: int = 0
    shares_accepted: int = 0
    blocks_found: int = 0
    hashrate: float = 0.0
    uptime_seconds: float = 0.0
    last_share_at: Optional[float] = None
    last_error: Optional[str] = None
    payout_target: str = "solo"  # v1: always "solo"; v2: "pool:<url>"
    fees_owed: int = 0  # v2 accounting hook; 0 in v1


# ---------------------------------------------------------------------------
# The ABC
# ---------------------------------------------------------------------------


class MiningProvider(ABC):
    """A mining provider — orchestrates a Pearl mining session for one (hardware, engine, model) combo.

    All future hardware/engine paths (Apple Silicon, AMD, Ollama) implement
    this exact contract. See spec §4.4.
    """

    provider_id: str  # set by subclass

    @classmethod
    @abstractmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        """Return whether this provider can run on the given combo.

        Must be a pure inspection — no subprocess, no network, no Docker. Used
        by ``jarvis mine doctor`` and ``jarvis mine init`` for fast capability
        reporting.
        """

    @abstractmethod
    async def start(self, config: MiningConfig) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def is_running(self) -> bool: ...

    @abstractmethod
    def stats(self) -> MiningStats: ...


# ---------------------------------------------------------------------------
# Sidecar IO (see spec §5.3)
# ---------------------------------------------------------------------------


class Sidecar:
    """Read/write helpers for ``~/.openjarvis/runtime/mining.json``."""

    @staticmethod
    def write(path: Path, payload: dict[str, Any]) -> None:
        """Atomically write the sidecar JSON to ``path``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: tmp file + rename
        fd, tmp = tempfile.mkstemp(prefix=".mining-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def read(path: Path) -> Optional[dict[str, Any]]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def remove(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
```

- [ ] **Step 7: Create `mining/__init__.py`**

```python
# src/openjarvis/mining/__init__.py
"""Pearl mining subsystem.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``.

Provider modules are soft-imported below — each one fails gracefully if the
``mining-pearl`` (or future ``mining-pearl-mlx`` etc.) extra isn't installed.
"""

from __future__ import annotations

# Re-export the public ABCs and dataclasses for ergonomic imports.
from openjarvis.mining._stubs import (
    MiningCapabilities,
    MiningConfig,
    MiningProvider,
    MiningStats,
    PoolTarget,
    Sidecar,
    SoloTarget,
    SubmitTarget,
)

# Soft-import provider implementations to trigger registration. Each provider
# defines an idempotent ``ensure_registered()`` so it survives the autouse
# registry clear in ``tests/conftest.py``.
try:
    from openjarvis.mining import vllm_pearl  # noqa: F401

    vllm_pearl.ensure_registered()
except ImportError:
    pass

__all__ = [
    "MiningCapabilities",
    "MiningConfig",
    "MiningProvider",
    "MiningStats",
    "PoolTarget",
    "Sidecar",
    "SoloTarget",
    "SubmitTarget",
]
```

- [ ] **Step 8: Create `mining/pools/__init__.py`** (reserved for v2)

```python
# src/openjarvis/mining/pools/__init__.py
"""RESERVED for v2 pool support.

Do not add code here in v1. The v2 spec will define a ``PoolClient`` ABC and
``PoolClientRegistry`` peer to ``MinerRegistry``. Squatting on this path now
would create migration debt and pre-decide the v2 API. See spec §8.5.
"""

from __future__ import annotations
```

- [ ] **Step 9: Run tests to verify they pass**

```bash
uv run pytest tests/mining/test_stubs.py -v
```
Expected: 9 PASS.

- [ ] **Step 10: Commit**

```bash
git add src/openjarvis/mining/ tests/mining/__init__.py tests/mining/conftest.py tests/mining/test_stubs.py
git commit -m "feat(mining): add ABC, dataclasses, constants, sidecar IO"
```

---

## Task 3 — `MiningConfig` integration in `JarvisConfig` + TOML parsing

**Files:**
- Modify: `src/openjarvis/core/config.py`
- Test: `tests/core/test_config.py` (existing — add new tests)
- Test: `tests/mining/fixtures/config_minimal.toml`
- Test: `tests/mining/fixtures/config_pool_v2.toml`

- [ ] **Step 1: Create the fixture TOML files**

`tests/mining/fixtures/config_minimal.toml`:

```toml
[mining]
provider           = "vllm-pearl"
wallet_address     = "prl1qexampleaddress"
submit_target      = "solo"
fee_bps            = 0
fee_payout_address = ""

[mining.extra]
model                   = "pearl-ai/Llama-3.3-70B-Instruct-pearl"
pearld_rpc_url          = "http://localhost:44107"
pearld_rpc_user         = "rpcuser"
pearld_rpc_password_env = "PEARLD_RPC_PASSWORD"
```

`tests/mining/fixtures/config_pool_v2.toml`:

```toml
[mining]
provider       = "vllm-pearl"
wallet_address = "prl1qexampleaddress"
submit_target  = "pool:https://pool.openjarvis.ai/submit"

[mining.extra]
model                   = "pearl-ai/Llama-3.3-70B-Instruct-pearl"
pearld_rpc_url          = "http://localhost:44107"
pearld_rpc_user         = "rpcuser"
pearld_rpc_password_env = "PEARLD_RPC_PASSWORD"
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/core/test_config.py`:

```python
def test_mining_config_absent_means_none(tmp_path):
    from openjarvis.core.config import load_config
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("")  # empty config
    cfg = load_config(cfg_path)
    assert cfg.mining is None


def test_mining_config_solo_parsed(tmp_path):
    from pathlib import Path
    from openjarvis.core.config import load_config
    from openjarvis.mining._stubs import SoloTarget
    src = Path(__file__).parent.parent / "mining" / "fixtures" / "config_minimal.toml"
    target = tmp_path / "config.toml"
    target.write_text(src.read_text())
    cfg = load_config(target)
    assert cfg.mining is not None
    assert cfg.mining.provider == "vllm-pearl"
    assert cfg.mining.wallet_address == "prl1qexampleaddress"
    assert isinstance(cfg.mining.submit_target, SoloTarget)
    assert cfg.mining.submit_target.pearld_rpc_url == "http://localhost:44107"
    assert cfg.mining.fee_bps == 0
    assert cfg.mining.extra["model"] == "pearl-ai/Llama-3.3-70B-Instruct-pearl"


def test_mining_config_pool_parsed_as_pool_target(tmp_path):
    from pathlib import Path
    from openjarvis.core.config import load_config
    from openjarvis.mining._stubs import PoolTarget
    src = Path(__file__).parent.parent / "mining" / "fixtures" / "config_pool_v2.toml"
    target = tmp_path / "config.toml"
    target.write_text(src.read_text())
    cfg = load_config(target)
    assert isinstance(cfg.mining.submit_target, PoolTarget)
    assert cfg.mining.submit_target.url == "https://pool.openjarvis.ai/submit"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_config.py -k mining -v
```
Expected: 3 FAIL on `cfg.mining` attribute missing.

- [ ] **Step 4: Add `mining` field to `JarvisConfig`**

In `src/openjarvis/core/config.py`, add an import near the top:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openjarvis.mining._stubs import MiningConfig
```

Add the field to `JarvisConfig` (insert in alphabetical order — after `memory_files`, before `operators`):

```python
    mining: Optional["MiningConfig"] = None
```

- [ ] **Step 5: Implement TOML parsing for `[mining]` section**

In `src/openjarvis/core/config.py`, locate the existing `load_config()` function (around line 1541). Find the section that processes the loaded TOML data into the `JarvisConfig` (look for where it iterates the `data` dict and assigns to dataclass fields). Add a dedicated handler for `mining` because of the tagged-union parsing — it can't go through the generic walker.

Add this helper near the other `_parse_*` helpers in `core/config.py`:

```python
def _parse_mining_section(data: dict) -> Optional["MiningConfig"]:
    """Parse the ``[mining]`` TOML section into a ``MiningConfig``.

    Returns None if the section is absent. Resolves the ``submit_target``
    string into a ``SoloTarget`` or ``PoolTarget`` tagged union.
    """
    if "mining" not in data:
        return None

    # Lazy import to avoid circular: mining/__init__.py imports core/config
    # transitively via _stubs, but only at runtime.
    from openjarvis.mining._stubs import MiningConfig, PoolTarget, SoloTarget

    section = data["mining"]
    extra = section.get("extra", {}) or {}

    target_str = section.get("submit_target", "solo")
    submit_target: Any
    if target_str == "solo":
        submit_target = SoloTarget(
            pearld_rpc_url=extra.get("pearld_rpc_url", "http://localhost:44107")
        )
    elif isinstance(target_str, str) and target_str.startswith("pool:"):
        submit_target = PoolTarget(url=target_str[len("pool:") :])
    else:
        raise ValueError(
            f"[mining].submit_target must be 'solo' or 'pool:<url>', got {target_str!r}"
        )

    return MiningConfig(
        provider=section["provider"],
        wallet_address=section["wallet_address"],
        submit_target=submit_target,
        fee_bps=int(section.get("fee_bps", 0)),
        fee_payout_address=section.get("fee_payout_address") or None,
        extra={k: v for k, v in extra.items()},
    )
```

In `load_config()`, after the other section processing and before returning `cfg`:

```python
    cfg.mining = _parse_mining_section(data)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/core/test_config.py -k mining -v
```
Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/core/config.py tests/core/test_config.py tests/mining/fixtures/
git commit -m "feat(mining): integrate MiningConfig into JarvisConfig with TOML parsing"
```

---

## Task 4 — Capability discovery (`mining/_discovery.py`)

**Files:**
- Create: `src/openjarvis/mining/_discovery.py`
- Test: `tests/mining/test_discovery.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mining/test_discovery.py`:

```python
"""Tests for mining/_discovery.py — capability detection matrix."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_detect_supported_on_h100(hopper_hw):
    from openjarvis.mining._discovery import detect_for_engine_model
    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="vllm",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is True
    assert cap.reason is None


def test_detect_unsupported_on_ada_4090(ada_hw):
    from openjarvis.mining._discovery import detect_for_engine_model
    cap = detect_for_engine_model(
        hw=ada_hw,
        engine_id="vllm",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "sm90" in cap.reason.lower() or "compute_capability" in cap.reason.lower()


def test_detect_unsupported_on_apple(apple_hw):
    from openjarvis.mining._discovery import detect_for_engine_model
    cap = detect_for_engine_model(
        hw=apple_hw,
        engine_id="mlx",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert cap.reason is not None  # specific reason — Apple Silicon route is Spec B


def test_detect_unsupported_for_non_vllm_engine(hopper_hw):
    from openjarvis.mining._discovery import detect_for_engine_model
    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="ollama",
        model="qwen3:8b",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "vllm" in cap.reason.lower() or "engine" in cap.reason.lower()


def test_detect_unsupported_for_non_pearl_model(hopper_hw):
    from openjarvis.mining._discovery import detect_for_engine_model
    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="vllm",
        model="meta-llama/Llama-3.3-70B-Instruct",  # NOT the -pearl variant
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "pearl" in cap.reason.lower()


def test_detect_unsupported_for_low_vram():
    from openjarvis.mining._discovery import detect_for_engine_model
    from openjarvis.core.config import GpuInfo, HardwareInfo
    hw = HardwareInfo(
        platform="linux",
        gpu=GpuInfo(
            vendor="nvidia",
            name="NVIDIA H100 PCIe-40GB",
            vram_gb=40.0,  # below 70 GB threshold
            compute_capability="9.0",
            count=1,
        ),
    )
    cap = detect_for_engine_model(
        hw=hw, engine_id="vllm", model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "vram" in cap.reason.lower() or "memory" in cap.reason.lower()


def test_check_docker_available_true():
    from openjarvis.mining._discovery import check_docker_available
    with patch("openjarvis.mining._discovery._docker_client") as fake:
        fake.return_value.ping.return_value = True
        fake.return_value.version.return_value = {"Version": "24.0.7"}
        ok, info = check_docker_available()
        assert ok is True
        assert "24.0.7" in info


def test_check_docker_available_false_when_daemon_down():
    from openjarvis.mining._discovery import check_docker_available
    with patch("openjarvis.mining._discovery._docker_client") as fake:
        fake.side_effect = Exception("Cannot connect to the Docker daemon")
        ok, info = check_docker_available()
        assert ok is False
        assert "daemon" in info.lower() or "connect" in info.lower()


def test_check_disk_free_passes(tmp_path):
    from openjarvis.mining._discovery import check_disk_free
    with patch("openjarvis.mining._discovery.shutil.disk_usage") as du:
        # 500 GB free
        du.return_value = MagicMock(total=1_000_000_000_000, used=500_000_000_000, free=500_000_000_000)
        ok, info = check_disk_free(tmp_path)
        assert ok is True


def test_check_disk_free_fails_below_threshold(tmp_path):
    from openjarvis.mining._discovery import check_disk_free
    with patch("openjarvis.mining._discovery.shutil.disk_usage") as du:
        du.return_value = MagicMock(total=1_000_000_000_000, used=950_000_000_000, free=50_000_000_000)
        ok, info = check_disk_free(tmp_path)
        assert ok is False


def test_check_pearld_reachable_true():
    from openjarvis.mining._discovery import check_pearld_reachable
    with patch("openjarvis.mining._discovery.httpx.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"result": {"blocks": 442107, "headers": 442107}}
        ok, info = check_pearld_reachable("http://localhost:44107", "user", "pass")
        assert ok is True
        assert "442107" in info


def test_check_pearld_reachable_false_on_connection_error():
    from openjarvis.mining._discovery import check_pearld_reachable
    import httpx
    with patch("openjarvis.mining._discovery.httpx.post") as post:
        post.side_effect = httpx.ConnectError("connection refused")
        ok, info = check_pearld_reachable("http://localhost:44107", "user", "pass")
        assert ok is False


def test_check_wallet_address_format_valid():
    from openjarvis.mining._discovery import check_wallet_address_format
    ok, info = check_wallet_address_format("prl1qexampleaddress0123456789")
    assert ok is True


def test_check_wallet_address_format_invalid():
    from openjarvis.mining._discovery import check_wallet_address_format
    ok, info = check_wallet_address_format("not-a-pearl-address")
    assert ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/mining/test_discovery.py -v
```
Expected: ALL fail with `ImportError`.

- [ ] **Step 3: Create `_discovery.py`**

```python
# src/openjarvis/mining/_discovery.py
"""Capability detection for mining providers.

Each function answers a single yes/no question and returns ``(ok: bool,
info: str)`` where ``info`` is a short human-readable explanation surfaced
verbatim by ``jarvis mine doctor``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional, Tuple

import httpx

from openjarvis.core.config import HardwareInfo
from openjarvis.mining._stubs import MiningCapabilities

# ---------------------------------------------------------------------------
# Constants for the v1 vllm-pearl provider
# ---------------------------------------------------------------------------

REQUIRED_COMPUTE_CAPABILITY = "9.0"  # sm_90a — Hopper
REQUIRED_VRAM_GB = 70.0
SUPPORTED_VLLM_ENGINE_IDS = frozenset({"vllm"})


def detect_for_engine_model(
    *,
    hw: HardwareInfo,
    engine_id: str,
    model: str,
    provider_id: str,
) -> MiningCapabilities:
    """Capability matrix for the ``vllm-pearl`` provider.

    Pure inspection. No subprocess, no Docker, no network. Used by
    ``jarvis mine doctor`` and ``jarvis mine init``.
    """
    if provider_id != "vllm-pearl":
        return MiningCapabilities(
            False, reason=f"unknown provider {provider_id!r}"
        )

    # Engine
    if engine_id not in SUPPORTED_VLLM_ENGINE_IDS:
        return MiningCapabilities(
            False,
            reason=f"engine '{engine_id}' has no Pearl plugin in v1; use vllm",
        )

    # Hardware
    if hw.gpu is None:
        return MiningCapabilities(False, reason="no GPU detected")
    if hw.gpu.vendor != "nvidia":
        return MiningCapabilities(
            False,
            reason=f"vllm-pearl requires NVIDIA Hopper; detected {hw.gpu.vendor!r}. "
            f"Apple Silicon support tracked in Spec B.",
        )
    if not hw.gpu.compute_capability.startswith("9.0"):
        return MiningCapabilities(
            False,
            reason=f"needs compute_capability 9.0 (sm_90a / H100/H200); detected "
            f"{hw.gpu.compute_capability!r} ({hw.gpu.name})",
        )
    if hw.gpu.vram_gb < REQUIRED_VRAM_GB:
        return MiningCapabilities(
            False,
            reason=f"needs ≥{REQUIRED_VRAM_GB:.0f} GB VRAM for the Pearl 70B model; "
            f"detected {hw.gpu.vram_gb:.0f} GB",
        )

    # Model
    if "-pearl" not in model.lower():
        return MiningCapabilities(
            False,
            reason=f"model {model!r} has no Pearl-blessed variant — use a "
            f"'pearl-ai/*-pearl' model",
        )

    return MiningCapabilities(supported=True)


# ---------------------------------------------------------------------------
# Doctor checks (one per row of `jarvis mine doctor` output)
# ---------------------------------------------------------------------------


def _docker_client():  # pragma: no cover - trivial wrapper, mocked in tests
    import docker

    return docker.from_env()


def check_docker_available() -> Tuple[bool, str]:
    try:
        c = _docker_client()
        c.ping()
        ver = c.version().get("Version", "unknown")
        return True, f"running {ver}"
    except Exception as e:  # noqa: BLE001 - intentionally broad
        return False, str(e).splitlines()[0]


def check_disk_free(path: Path) -> Tuple[bool, str]:
    from openjarvis.mining._constants import MIN_FREE_DISK_GB

    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024**3)
    if free_gb < MIN_FREE_DISK_GB:
        return False, f"only {free_gb:.0f} GB free (need ≥{MIN_FREE_DISK_GB} GB)"
    return True, f"{free_gb:.0f} GB free"


def check_pearld_reachable(
    url: str, user: str, password: str
) -> Tuple[bool, str]:
    """Probe pearld via JSON-RPC ``getblockchaininfo``."""
    try:
        resp = httpx.post(
            url,
            json={"jsonrpc": "1.0", "id": "ojprobe", "method": "getblockchaininfo", "params": []},
            auth=(user, password),
            timeout=5.0,
        )
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        data = resp.json()
        result = data.get("result") or {}
        blocks = result.get("blocks", "?")
        headers = result.get("headers", "?")
        synced = blocks == headers
        marker = "synced" if synced else f"syncing ({blocks}/{headers})"
        return True, f"block height {blocks} ({marker})"
    except httpx.ConnectError as e:
        return False, f"connection refused: {e}"
    except Exception as e:  # noqa: BLE001
        return False, str(e).splitlines()[0]


def check_wallet_address_format(address: str) -> Tuple[bool, str]:
    """Pearl Taproot addresses begin with ``prl1q...``.

    We do *not* attempt to validate the bech32 checksum — that's a stronger
    contract that may shift between Pearl revs. Format check only.
    """
    if not address:
        return False, "empty"
    if not address.startswith("prl1q"):
        return False, f"expected 'prl1q...' prefix; got {address[:6]!r}"
    if len(address) < 14:
        return False, f"too short ({len(address)} chars)"
    return True, "format ok"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/mining/test_discovery.py -v
```
Expected: 13 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/mining/_discovery.py tests/mining/test_discovery.py
git commit -m "feat(mining): capability detection + doctor checks"
```

---

## Task 5 — `PearlDockerLauncher` image acquisition

**Files:**
- Create: `src/openjarvis/mining/_docker.py`
- Test: `tests/mining/test_docker.py`

- [ ] **Step 1: Write the failing tests for `ensure_image()`**

Create `tests/mining/test_docker.py`:

```python
"""Tests for mining/_docker.py — Docker SDK orchestration via mocks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_ensure_image_already_local():
    from openjarvis.mining._docker import PearlDockerLauncher
    fake = MagicMock()
    fake.images.get.return_value = MagicMock(id="sha256:abc", tags=["openjarvis/pearl-miner:main"])
    launcher = PearlDockerLauncher(client=fake)
    out = launcher.ensure_image("openjarvis/pearl-miner:main")
    assert out == "openjarvis/pearl-miner:main"
    fake.images.get.assert_called_once_with("openjarvis/pearl-miner:main")
    fake.images.pull.assert_not_called()


def test_ensure_image_pulls_if_published():
    from openjarvis.mining._docker import PearlDockerLauncher
    import docker.errors as derr
    fake = MagicMock()
    fake.images.get.side_effect = derr.ImageNotFound("nope")
    fake.images.pull.return_value = MagicMock(id="sha256:def")
    launcher = PearlDockerLauncher(client=fake)
    out = launcher.ensure_image("registry.example/pearl-miner:1.0")
    assert out == "registry.example/pearl-miner:1.0"
    fake.images.pull.assert_called_once_with("registry.example/pearl-miner:1.0")


def test_ensure_image_falls_back_to_build_for_default_tag():
    from openjarvis.mining._docker import PearlDockerLauncher
    from openjarvis.mining._constants import PEARL_IMAGE_TAG
    import docker.errors as derr
    fake = MagicMock()
    fake.images.get.side_effect = derr.ImageNotFound("nope")
    fake.images.pull.side_effect = derr.NotFound("registry refused")
    launcher = PearlDockerLauncher(client=fake)
    with patch.object(launcher, "_clone_pearl_repo") as clone, patch.object(
        launcher, "_docker_build"
    ) as build:
        clone.return_value = "/tmp/pearl-cache"
        build.return_value = PEARL_IMAGE_TAG
        out = launcher.ensure_image(PEARL_IMAGE_TAG)
        assert out == PEARL_IMAGE_TAG
        clone.assert_called_once()
        build.assert_called_once()


def test_ensure_image_errors_when_non_default_tag_missing():
    from openjarvis.mining._docker import PearlDockerLauncher, ImageAcquisitionError
    import docker.errors as derr
    import pytest
    fake = MagicMock()
    fake.images.get.side_effect = derr.ImageNotFound("nope")
    fake.images.pull.side_effect = derr.NotFound("registry refused")
    launcher = PearlDockerLauncher(client=fake)
    with pytest.raises(ImageAcquisitionError) as ei:
        launcher.ensure_image("user/custom-image:tag")
    assert "user/custom-image:tag" in str(ei.value)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/mining/test_docker.py -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the launcher's image-acquisition path**

Create `src/openjarvis/mining/_docker.py`:

```python
# src/openjarvis/mining/_docker.py
"""Pearl Docker container orchestration.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``
section 7 for the design.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from openjarvis.mining._constants import (
    PEARL_CACHE_DIR,
    PEARL_IMAGE_TAG,
    PEARL_PINNED_REF,
    PEARL_REPO,
)


class ImageAcquisitionError(RuntimeError):
    """Raised when an image can be neither found, pulled, nor built."""


class PearlDockerLauncher:
    """Orchestrates the Pearl miner container.

    Construct with a ``docker.DockerClient`` (real or mocked).
    """

    def __init__(self, client: Any):
        self._client = client
        self._container: Optional[Any] = None

    # -----------------------------------------------------------------
    # Image acquisition
    # -----------------------------------------------------------------

    def ensure_image(self, tag: str) -> str:
        """Resolve ``tag`` to a usable local image, building if necessary.

        Selection order (see spec §7.2):
        1. Image present locally → use it.
        2. Image pullable from a registry → pull and use.
        3. ``tag`` matches OJ's default → clone Pearl + ``docker build``.
        4. Otherwise → ``ImageAcquisitionError``.
        """
        import docker.errors as derr

        try:
            self._client.images.get(tag)
            return tag
        except derr.ImageNotFound:
            pass

        try:
            self._client.images.pull(tag)
            return tag
        except (derr.NotFound, derr.APIError):
            pass

        if tag == PEARL_IMAGE_TAG:
            cache = self._clone_pearl_repo()
            return self._docker_build(cache, tag)

        raise ImageAcquisitionError(
            f"image {tag!r} not present locally, not pullable, and not OJ's "
            f"default tag (no build fallback). Either build it manually with "
            f"`docker buildx build -t {tag} -f miner/vllm-miner/Dockerfile .` "
            f"from the Pearl repo, or set [mining.extra].docker_image_tag to "
            f"the OJ default ({PEARL_IMAGE_TAG}) to enable the build fallback."
        )

    def _clone_pearl_repo(self) -> Path:
        """Clone Pearl at the pinned ref into the OJ cache."""
        PEARL_CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        if PEARL_CACHE_DIR.exists():
            subprocess.run(
                ["git", "fetch", "origin", PEARL_PINNED_REF],
                cwd=str(PEARL_CACHE_DIR),
                check=True,
            )
            subprocess.run(
                ["git", "checkout", PEARL_PINNED_REF],
                cwd=str(PEARL_CACHE_DIR),
                check=True,
            )
        else:
            subprocess.run(
                ["git", "clone", "--branch", PEARL_PINNED_REF, PEARL_REPO, str(PEARL_CACHE_DIR)],
                check=True,
            )
        return PEARL_CACHE_DIR

    def _docker_build(self, repo_path: Path, tag: str) -> str:
        """Run ``docker buildx build`` with Pearl's Dockerfile against the monorepo."""
        # Build context must be the repo root; Dockerfile is at miner/vllm-miner/Dockerfile.
        cmd = [
            "docker",
            "buildx",
            "build",
            "-t",
            tag,
            "-f",
            "miner/vllm-miner/Dockerfile",
            ".",
        ]
        subprocess.run(cmd, cwd=str(repo_path), check=True)
        return tag
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/mining/test_docker.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/mining/_docker.py tests/mining/test_docker.py
git commit -m "feat(mining): PearlDockerLauncher image acquisition (pull-or-build)"
```

---

## Task 6 — `PearlDockerLauncher` container lifecycle

**Files:**
- Modify: `src/openjarvis/mining/_docker.py`
- Modify: `tests/mining/test_docker.py`

- [ ] **Step 1: Write failing tests for `start()` / `stop()` / `is_running()` / `get_logs()`**

Append to `tests/mining/test_docker.py`:

```python
import os
import pytest


@pytest.fixture
def _env_password(monkeypatch):
    monkeypatch.setenv("PEARLD_RPC_PASSWORD", "secret123")


def test_launcher_start_calls_run_with_expected_kwargs(_env_password):
    from openjarvis.mining._docker import PearlDockerLauncher
    from openjarvis.mining._stubs import MiningConfig, SoloTarget
    fake = MagicMock()
    fake.containers.run.return_value = MagicMock(id="cid-1", status="running")
    launcher = PearlDockerLauncher(client=fake)
    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qaaa",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        extra={
            "docker_image_tag": "openjarvis/pearl-miner:main",
            "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
            "vllm_port": 8000,
            "gpu_memory_utilization": 0.9,
            "max_model_len": 8192,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "PEARLD_RPC_PASSWORD",
            "hf_token_env": "HF_TOKEN",
        },
    )
    container = launcher.start(cfg, image="openjarvis/pearl-miner:main")
    assert container.id == "cid-1"
    fake.containers.run.assert_called_once()
    kwargs = fake.containers.run.call_args.kwargs
    # Image
    assert kwargs["image"] == "openjarvis/pearl-miner:main"
    # Command starts with the model name (positional), then args
    assert kwargs["command"][0] == "pearl-ai/Llama-3.3-70B-Instruct-pearl"
    assert "--gpu-memory-utilization" in kwargs["command"]
    # Restart policy
    assert kwargs["restart_policy"]["Name"] == "unless-stopped"
    # Env contains the password (resolved from env var name)
    assert kwargs["environment"]["PEARLD_RPC_PASSWORD"] == "secret123"
    # Mining address pass-through
    assert kwargs["environment"]["PEARLD_MINING_ADDRESS"] == "prl1qaaa"
    # MINER_RPC_TRANSPORT set so OJ can poll port 8337
    assert kwargs["environment"]["MINER_RPC_TRANSPORT"] == "tcp"
    # GPU device request
    assert kwargs["device_requests"]


def test_launcher_stop_calls_container_stop_and_remove():
    from openjarvis.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock()
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    launcher.stop()
    fake_container.stop.assert_called_once()


def test_launcher_is_running_when_container_running():
    from openjarvis.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock(status="running")
    fake_container.reload.return_value = None
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    assert launcher.is_running() is True


def test_launcher_is_running_false_when_container_exited():
    from openjarvis.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock()
    fake_container.reload.return_value = None
    fake_container.status = "exited"
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    assert launcher.is_running() is False


def test_launcher_get_logs_returns_decoded_string():
    from openjarvis.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock()
    fake_container.logs.return_value = b"hello\nworld\n"
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    assert "hello" in launcher.get_logs(tail=100)


def test_launcher_start_errors_when_password_env_missing():
    from openjarvis.mining._docker import PearlDockerLauncher, ConfigurationError
    from openjarvis.mining._stubs import MiningConfig, SoloTarget
    fake = MagicMock()
    launcher = PearlDockerLauncher(client=fake)
    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qaaa",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        extra={
            "docker_image_tag": "openjarvis/pearl-miner:main",
            "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
            "vllm_port": 8000,
            "gpu_memory_utilization": 0.9,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "DOES_NOT_EXIST_IN_ENV",
        },
    )
    with pytest.raises(ConfigurationError) as ei:
        launcher.start(cfg, image="openjarvis/pearl-miner:main")
    assert "DOES_NOT_EXIST_IN_ENV" in str(ei.value)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/mining/test_docker.py -v
```
Expected: 6 new FAIL.

- [ ] **Step 3: Implement `start()`, `stop()`, `is_running()`, `get_logs()`**

Append to `src/openjarvis/mining/_docker.py`:

```python
class ConfigurationError(RuntimeError):
    """Raised when required env vars or config fields are missing."""


    # ----- in PearlDockerLauncher class, append these methods -----

    def start(self, config: "MiningConfig", image: str) -> Any:
        """Launch the Pearl miner container.

        ``image`` must already be resolved by ``ensure_image()``.
        Returns the docker.models.containers.Container object.
        """
        from openjarvis.mining._stubs import MiningConfig  # noqa: F401  (typing only)

        extra = config.extra
        # Resolve secret env vars (we hold the *name*, not the value).
        password_env = extra.get("pearld_rpc_password_env", "PEARLD_RPC_PASSWORD")
        password = os.environ.get(password_env)
        if password is None:
            raise ConfigurationError(
                f"environment variable {password_env!r} is not set; "
                f"set it before running `jarvis mine start`"
            )

        hf_token_env = extra.get("hf_token_env", "HF_TOKEN")
        hf_token = os.environ.get(hf_token_env, "")

        model = extra.get("model", "pearl-ai/Llama-3.3-70B-Instruct-pearl")
        vllm_port = int(extra.get("vllm_port", 8000))
        gpu_mem = float(extra.get("gpu_memory_utilization", 0.9))
        max_len = int(extra.get("max_model_len", 8192))

        command = [
            model,
            "--host", "0.0.0.0",
            "--port", str(vllm_port),
            "--gpu-memory-utilization", str(gpu_mem),
            "--enforce-eager",
            "--max-model-len", str(max_len),
        ]

        environment = {
            "PEARLD_RPC_URL": extra.get("pearld_rpc_url", "http://localhost:44107"),
            "PEARLD_RPC_USER": extra.get("pearld_rpc_user", "rpcuser"),
            "PEARLD_RPC_PASSWORD": password,
            "PEARLD_MINING_ADDRESS": config.wallet_address,
            "HF_TOKEN": hf_token,
            "MINER_RPC_TRANSPORT": "tcp",
        }

        # Dynamic import so tests don't need the real `docker` package shape.
        try:
            from docker.types import DeviceRequest
            device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]
        except ImportError:  # pragma: no cover
            device_requests = None

        hf_cache = Path.home() / ".cache" / "huggingface"
        volumes = {
            str(hf_cache): {"bind": "/root/.cache/huggingface", "mode": "rw"},
        }

        self._container = self._client.containers.run(
            image=image,
            command=command,
            name="openjarvis-pearl-miner",
            detach=True,
            auto_remove=False,
            restart_policy={"Name": "unless-stopped"},
            device_requests=device_requests,
            shm_size="8g",
            network_mode="host",
            volumes=volumes,
            environment=environment,
        )
        return self._container

    def stop(self, timeout: int = 30) -> None:
        if self._container is None:
            return
        try:
            self._container.stop(timeout=timeout)
        except Exception:  # noqa: BLE001 - best-effort
            pass
        self._container = None

    def is_running(self) -> bool:
        if self._container is None:
            return False
        try:
            self._container.reload()
        except Exception:  # noqa: BLE001
            return False
        return getattr(self._container, "status", "") == "running"

    def get_logs(self, tail: int = 200) -> str:
        if self._container is None:
            return ""
        raw = self._container.logs(tail=tail)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/mining/test_docker.py -v
```
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/mining/_docker.py tests/mining/test_docker.py
git commit -m "feat(mining): PearlDockerLauncher container lifecycle (start/stop/is_running/logs)"
```

---

## Task 7 — Gateway metrics adapter

**Files:**
- Modify: `src/openjarvis/mining/vllm_pearl.py` (creating in next task — for now create the parser as a helper)
- Create: `src/openjarvis/mining/_metrics.py`
- Create: `tests/mining/fixtures/gateway_metrics_sample.txt`
- Create: `tests/mining/test_metrics.py`

> **Note for the implementer:** The fixture file in this task is a *placeholder* with the metric names the spec assumes (see spec §8.2 table). At implementation time, replace it with real Prometheus output captured from a Pearl gateway run against the pinned Pearl ref. Document the capture procedure in `tests/mining/fixtures/README.md`.

- [ ] **Step 1: Create the (placeholder) Prometheus fixture**

`tests/mining/fixtures/gateway_metrics_sample.txt`:

```
# HELP pearl_gateway_shares_submitted_total Total mining shares submitted.
# TYPE pearl_gateway_shares_submitted_total counter
pearl_gateway_shares_submitted_total 12345
# HELP pearl_gateway_shares_accepted_total Total mining shares accepted by pearld.
# TYPE pearl_gateway_shares_accepted_total counter
pearl_gateway_shares_accepted_total 12300
# HELP pearl_gateway_blocks_found_total Total blocks found.
# TYPE pearl_gateway_blocks_found_total counter
pearl_gateway_blocks_found_total 7
# HELP pearl_gateway_last_share_timestamp Unix timestamp of last share submission.
# TYPE pearl_gateway_last_share_timestamp gauge
pearl_gateway_last_share_timestamp 1714867500
# HELP pearl_gateway_errors_total Total errors observed by the gateway.
# TYPE pearl_gateway_errors_total counter
pearl_gateway_errors_total 0
# HELP process_start_time_seconds Process start time (Unix seconds).
# TYPE process_start_time_seconds gauge
process_start_time_seconds 1714865000
```

Also create `tests/mining/fixtures/README.md`:

```markdown
# Mining test fixtures

`gateway_metrics_sample.txt` is captured Prometheus output from a real
Pearl gateway run against the pinned Pearl ref. Re-capture by:

1. Run the Pearl Docker image on an H100 host per the spec §7.4 launch shape.
2. `curl http://127.0.0.1:8339/metrics > gateway_metrics_sample.txt` once
   the gateway is healthy and at least 10 shares have been submitted.
3. Strip any cardinality bombs (per-prompt or per-block-time histograms)
   that bloat the file.
4. Commit, citing the Pearl commit/tag the capture was taken against.

If Pearl renames metrics, update `mining/_metrics.py::PROM_*` constants and
re-capture.
```

- [ ] **Step 2: Write the failing test**

Create `tests/mining/test_metrics.py`:

```python
"""Tests for mining/_metrics.py — Prometheus → MiningStats adapter."""

from __future__ import annotations

from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "gateway_metrics_sample.txt"


def test_parse_gateway_metrics_full():
    from openjarvis.mining._metrics import parse_gateway_metrics
    text = FIXTURE.read_text()
    stats = parse_gateway_metrics(text, provider_id="vllm-pearl")
    assert stats.provider_id == "vllm-pearl"
    assert stats.shares_submitted == 12345
    assert stats.shares_accepted == 12300
    assert stats.blocks_found == 7
    assert stats.last_share_at == 1714867500.0
    # Uptime computed as now - process_start_time, but not asserted exactly.
    assert stats.uptime_seconds >= 0


def test_parse_gateway_metrics_missing_metrics_zero_fills():
    from openjarvis.mining._metrics import parse_gateway_metrics
    stats = parse_gateway_metrics("# empty exposition\n", provider_id="vllm-pearl")
    assert stats.shares_submitted == 0
    assert stats.shares_accepted == 0
    assert stats.blocks_found == 0
    assert stats.last_share_at is None


def test_parse_gateway_metrics_ignores_comment_lines():
    from openjarvis.mining._metrics import parse_gateway_metrics
    stats = parse_gateway_metrics(
        "# HELP something\n# TYPE something counter\nsomething 99\n",
        provider_id="vllm-pearl",
    )
    assert stats.shares_submitted == 0  # 'something' isn't a Pearl metric
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/mining/test_metrics.py -v
```
Expected: 3 FAIL.

- [ ] **Step 4: Implement the adapter**

Create `src/openjarvis/mining/_metrics.py`:

```python
# src/openjarvis/mining/_metrics.py
"""Pearl gateway Prometheus → MiningStats adapter.

The gateway exposes ``:8339/metrics`` in plain Prometheus exposition format.
This is the most stable contract Pearl publishes; deeper RPC introspection
on ``:8337`` is deferred to v2 (where it's needed for pool share accounting).

If Pearl renames metrics, change the ``PROM_*`` constants here — that's the
only place the metric names live.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from openjarvis.mining._stubs import MiningStats

log = logging.getLogger(__name__)

# Pearl metric names. See spec §8.2 — verify against the fixture committed
# in tests/mining/fixtures/gateway_metrics_sample.txt.
PROM_SHARES_SUBMITTED = "pearl_gateway_shares_submitted_total"
PROM_SHARES_ACCEPTED = "pearl_gateway_shares_accepted_total"
PROM_BLOCKS_FOUND = "pearl_gateway_blocks_found_total"
PROM_LAST_SHARE_TS = "pearl_gateway_last_share_timestamp"
PROM_ERRORS_TOTAL = "pearl_gateway_errors_total"
PROM_PROCESS_START = "process_start_time_seconds"


def _parse_simple_metric(text: str, name: str) -> Optional[float]:
    """Find the first occurrence of a simple, label-less metric.

    Lines look like ``metric_name 12345`` or ``metric_name{label="x"} 12345``.
    For the v1 adapter we ignore labels and take the first non-comment match.
    """
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        # Split on the first whitespace; the metric name is everything up to
        # an optional `{...}` label block.
        head, _, value = line.partition(" ")
        head = head.split("{", 1)[0]
        if head == name:
            try:
                return float(value.strip())
            except ValueError:
                return None
    return None


def parse_gateway_metrics(text: str, *, provider_id: str) -> MiningStats:
    """Convert a Prometheus exposition payload into a ``MiningStats``."""
    submitted = _parse_simple_metric(text, PROM_SHARES_SUBMITTED) or 0.0
    accepted = _parse_simple_metric(text, PROM_SHARES_ACCEPTED) or 0.0
    blocks = _parse_simple_metric(text, PROM_BLOCKS_FOUND) or 0.0
    last_share_ts = _parse_simple_metric(text, PROM_LAST_SHARE_TS)
    errors = _parse_simple_metric(text, PROM_ERRORS_TOTAL) or 0.0
    proc_start = _parse_simple_metric(text, PROM_PROCESS_START)

    uptime = 0.0
    if proc_start is not None:
        uptime = max(0.0, time.time() - proc_start)

    last_error: Optional[str] = None
    if errors > 0:
        last_error = f"{int(errors)} gateway errors observed"

    return MiningStats(
        provider_id=provider_id,
        shares_submitted=int(submitted),
        shares_accepted=int(accepted),
        blocks_found=int(blocks),
        # Hashrate as a derived rate is not meaningful from a single snapshot;
        # the v1.x persistent collector will compute it. v1 leaves it 0.
        hashrate=0.0,
        uptime_seconds=uptime,
        last_share_at=last_share_ts,
        last_error=last_error,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/mining/test_metrics.py -v
```
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/mining/_metrics.py tests/mining/test_metrics.py tests/mining/fixtures/
git commit -m "feat(mining): Prometheus gateway metrics adapter"
```

---

## Task 8 — `VllmPearlProvider` (the only v1 provider)

**Files:**
- Create: `src/openjarvis/mining/vllm_pearl.py`
- Create: `tests/mining/test_vllm_pearl.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mining/test_vllm_pearl.py`:

```python
"""End-to-end tests for VllmPearlProvider with mocked Docker + filesystem."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def test_vllm_pearl_detect_supported_on_h100(hopper_hw):
    from openjarvis.mining.vllm_pearl import VllmPearlProvider
    cap = VllmPearlProvider.detect(
        hopper_hw, engine_id="vllm",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
    )
    assert cap.supported is True


def test_vllm_pearl_detect_unsupported_on_apple(apple_hw):
    from openjarvis.mining.vllm_pearl import VllmPearlProvider
    cap = VllmPearlProvider.detect(
        apple_hw, engine_id="mlx",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
    )
    assert cap.supported is False


@pytest.mark.asyncio
async def test_vllm_pearl_start_writes_sidecar(tmp_path, monkeypatch):
    from openjarvis.mining.vllm_pearl import VllmPearlProvider
    from openjarvis.mining._stubs import MiningConfig, SoloTarget, Sidecar

    sidecar_path = tmp_path / "mining.json"
    monkeypatch.setattr(
        "openjarvis.mining.vllm_pearl.SIDECAR_PATH", sidecar_path
    )
    monkeypatch.setenv("PEARLD_RPC_PASSWORD", "x")

    fake_client = MagicMock()
    fake_container = MagicMock(id="cid-xyz")
    fake_container.status = "running"
    fake_client.containers.run.return_value = fake_container
    # ensure_image: image already present
    fake_client.images.get.return_value = MagicMock(id="sha256:abc")

    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qaaa",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        extra={
            "docker_image_tag": "openjarvis/pearl-miner:main",
            "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
            "vllm_port": 8000,
            "gateway_port": 8337,
            "gateway_metrics_port": 8339,
            "gpu_memory_utilization": 0.9,
            "max_model_len": 8192,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "PEARLD_RPC_PASSWORD",
        },
    )

    provider = VllmPearlProvider(docker_client=fake_client)
    await provider.start(cfg)

    assert sidecar_path.exists()
    payload = json.loads(sidecar_path.read_text())
    assert payload["provider"] == "vllm-pearl"
    assert payload["vllm_endpoint"].endswith(":8000/v1")
    assert payload["gateway_url"].endswith(":8337")
    assert payload["gateway_metrics_url"].endswith(":8339")
    assert payload["wallet_address"] == "prl1qaaa"
    assert payload["container_id"] == "cid-xyz"
    assert "started_at" in payload
    # Sidecar omits secrets
    assert "PEARLD_RPC_PASSWORD" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_vllm_pearl_start_pool_target_raises_not_implemented(monkeypatch, tmp_path):
    from openjarvis.mining.vllm_pearl import VllmPearlProvider
    from openjarvis.mining._stubs import MiningConfig, PoolTarget

    sidecar_path = tmp_path / "mining.json"
    monkeypatch.setattr(
        "openjarvis.mining.vllm_pearl.SIDECAR_PATH", sidecar_path
    )

    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qaaa",
        submit_target=PoolTarget(url="https://pool.openjarvis.ai/submit"),
        extra={"docker_image_tag": "openjarvis/pearl-miner:main"},
    )
    provider = VllmPearlProvider(docker_client=MagicMock())
    with pytest.raises(NotImplementedError) as ei:
        await provider.start(cfg)
    assert "v2" in str(ei.value).lower() or "pool" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_vllm_pearl_stop_removes_sidecar(tmp_path, monkeypatch, written_sidecar):
    from openjarvis.mining.vllm_pearl import VllmPearlProvider
    monkeypatch.setattr(
        "openjarvis.mining.vllm_pearl.SIDECAR_PATH", written_sidecar
    )
    fake_client = MagicMock()
    provider = VllmPearlProvider(docker_client=fake_client)
    provider._launcher._container = MagicMock()  # simulate running
    await provider.stop()
    assert not written_sidecar.exists()


def test_vllm_pearl_stats_reads_gateway(monkeypatch, written_sidecar):
    from openjarvis.mining.vllm_pearl import VllmPearlProvider
    monkeypatch.setattr(
        "openjarvis.mining.vllm_pearl.SIDECAR_PATH", written_sidecar
    )
    sample = (
        "pearl_gateway_shares_submitted_total 100\n"
        "pearl_gateway_shares_accepted_total 99\n"
        "pearl_gateway_blocks_found_total 1\n"
    )
    with patch("openjarvis.mining.vllm_pearl.httpx.get") as get:
        get.return_value.status_code = 200
        get.return_value.text = sample
        provider = VllmPearlProvider(docker_client=MagicMock())
        stats = provider.stats()
        assert stats.shares_submitted == 100
        assert stats.shares_accepted == 99
        assert stats.blocks_found == 1


def test_ensure_registered_is_idempotent():
    from openjarvis.core.registry import MinerRegistry
    from openjarvis.mining.vllm_pearl import (
        VllmPearlProvider,
        ensure_registered,
    )
    ensure_registered()
    ensure_registered()  # second call should not raise
    assert MinerRegistry.contains("vllm-pearl")
    assert MinerRegistry.get("vllm-pearl") is VllmPearlProvider
```

> **Note:** the test `test_vllm_pearl_start_writes_sidecar` uses `pytest.mark.asyncio`. Confirm `pytest-asyncio` is in the dev extras (it is per `pyproject.toml`'s `[project.optional-dependencies].dev`). If async tests fail to collect, add `asyncio_mode = "auto"` under `[tool.pytest.ini_options]` in `pyproject.toml`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/mining/test_vllm_pearl.py -v
```
Expected: 7 FAIL.

- [ ] **Step 3: Implement `VllmPearlProvider`**

Create `src/openjarvis/mining/vllm_pearl.py`:

```python
# src/openjarvis/mining/vllm_pearl.py
"""The v1 vllm-pearl mining provider.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import httpx

from openjarvis.core.config import HardwareInfo
from openjarvis.core.registry import MinerRegistry
from openjarvis.mining._constants import (
    DEFAULT_GATEWAY_METRICS_PORT,
    DEFAULT_GATEWAY_RPC_PORT,
    DEFAULT_PEARL_MODEL,
    DEFAULT_VLLM_PORT,
    PEARL_IMAGE_TAG,
    SIDECAR_PATH,
)
from openjarvis.mining._discovery import detect_for_engine_model
from openjarvis.mining._docker import PearlDockerLauncher
from openjarvis.mining._metrics import parse_gateway_metrics
from openjarvis.mining._stubs import (
    MiningCapabilities,
    MiningConfig,
    MiningProvider,
    MiningStats,
    PoolTarget,
    Sidecar,
    SoloTarget,
)


class VllmPearlProvider(MiningProvider):
    """vLLM + Pearl Docker container, solo-mining only in v1."""

    provider_id = "vllm-pearl"

    def __init__(self, docker_client: Optional[Any] = None):
        if docker_client is None:
            import docker
            docker_client = docker.from_env()
        self._client = docker_client
        self._launcher = PearlDockerLauncher(client=docker_client)

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        return detect_for_engine_model(
            hw=hw, engine_id=engine_id, model=model, provider_id=cls.provider_id,
        )

    async def start(self, config: MiningConfig) -> None:
        if isinstance(config.submit_target, PoolTarget):
            raise NotImplementedError(
                "pool support is v2 — see openjarvis#XYZ. v1 only accepts "
                "submit_target='solo'."
            )
        assert isinstance(config.submit_target, SoloTarget)

        image = config.extra.get("docker_image_tag", PEARL_IMAGE_TAG)
        image = self._launcher.ensure_image(image)
        container = self._launcher.start(config, image=image)

        # Pull port assignments from extra (with sensible defaults).
        vllm_port = int(config.extra.get("vllm_port", DEFAULT_VLLM_PORT))
        gw_port = int(config.extra.get("gateway_port", DEFAULT_GATEWAY_RPC_PORT))
        gw_metrics = int(
            config.extra.get("gateway_metrics_port", DEFAULT_GATEWAY_METRICS_PORT)
        )
        model_name = config.extra.get("model", DEFAULT_PEARL_MODEL)

        Sidecar.write(SIDECAR_PATH, {
            "provider": self.provider_id,
            "vllm_endpoint": f"http://127.0.0.1:{vllm_port}/v1",
            "model": model_name,
            "gateway_url": f"http://127.0.0.1:{gw_port}",
            "gateway_metrics_url": f"http://127.0.0.1:{gw_metrics}",
            "container_id": getattr(container, "id", ""),
            "wallet_address": config.wallet_address,
            "started_at": int(time.time()),
        })

    async def stop(self) -> None:
        self._launcher.stop()
        Sidecar.remove(SIDECAR_PATH)

    def is_running(self) -> bool:
        return self._launcher.is_running()

    def stats(self) -> MiningStats:
        sidecar = Sidecar.read(SIDECAR_PATH)
        if sidecar is None:
            return MiningStats(provider_id=self.provider_id)
        url = sidecar.get("gateway_metrics_url")
        if not url:
            return MiningStats(provider_id=self.provider_id)
        try:
            resp = httpx.get(f"{url}/metrics", timeout=5.0)
            if resp.status_code != 200:
                return MiningStats(
                    provider_id=self.provider_id,
                    last_error=f"gateway HTTP {resp.status_code}",
                )
            return parse_gateway_metrics(resp.text, provider_id=self.provider_id)
        except Exception as e:  # noqa: BLE001
            return MiningStats(
                provider_id=self.provider_id,
                last_error=str(e).splitlines()[0],
            )


def ensure_registered() -> None:
    """Idempotent registration. Required because tests/conftest.py clears
    every registry before each test (see Spec A §4.2).
    """
    if not MinerRegistry.contains("vllm-pearl"):
        MinerRegistry.register_value("vllm-pearl", VllmPearlProvider)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/mining/test_vllm_pearl.py -v
```
Expected: 7 PASS.

- [ ] **Step 5: Run the full mining test suite to confirm no regressions**

```bash
uv run pytest tests/mining/ -v
```
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/mining/vllm_pearl.py tests/mining/test_vllm_pearl.py
git commit -m "feat(mining): VllmPearlProvider — the v1 vllm-pearl provider"
```

---

## Task 9 — Engine sidecar handoff

**Files:**
- Modify: `src/openjarvis/engine/_discovery.py`
- Test: `tests/engine/test_discovery.py` (existing — add new tests)

- [ ] **Step 1: Read existing `engine/_discovery.py`**

Run:
```bash
sed -n '1,80p' src/openjarvis/engine/_discovery.py
```

Identify the function that resolves engines (likely `discover_engines()` or `get_engine()`).

- [ ] **Step 2: Write the failing test**

Add to `tests/engine/test_discovery.py`:

```python
def test_engine_discovery_picks_up_mining_sidecar(tmp_path, monkeypatch, written_sidecar):
    """When a mining sidecar exists, engine resolution should expose a
    'vllm-pearl-mining' engine pointing at the sidecar's vllm_endpoint.
    """
    from openjarvis.engine._discovery import discover_engines
    from openjarvis.mining import _constants as mining_const

    monkeypatch.setattr(mining_const, "SIDECAR_PATH", written_sidecar)

    engines = discover_engines(force=True)
    keys = {e.engine_id if hasattr(e, "engine_id") else e for e in engines}
    assert any("vllm-pearl-mining" in str(k) for k in keys)


def test_engine_discovery_no_mining_engine_when_sidecar_absent(tmp_path, monkeypatch):
    from openjarvis.engine._discovery import discover_engines
    from openjarvis.mining import _constants as mining_const

    missing = tmp_path / "no-such-mining.json"
    monkeypatch.setattr(mining_const, "SIDECAR_PATH", missing)

    engines = discover_engines(force=True)
    keys = {e.engine_id if hasattr(e, "engine_id") else e for e in engines}
    assert not any("vllm-pearl-mining" in str(k) for k in keys)
```

The `written_sidecar` fixture lives in `tests/mining/conftest.py`; you'll need to either move it to a shared conftest or duplicate it in `tests/engine/conftest.py`. Prefer moving relevant ones to `tests/conftest.py`.

- [ ] **Step 3: Move sidecar fixtures to root conftest**

Move `sample_sidecar_payload`, `sidecar_path`, and `written_sidecar` from `tests/mining/conftest.py` to `tests/conftest.py`. Also move `hopper_hw`, `ada_hw`, `apple_hw`, and `mock_docker_client` to `tests/conftest.py` so all test packages can use them.

- [ ] **Step 4: Run tests to verify they fail**

```bash
uv run pytest tests/engine/test_discovery.py -k mining_sidecar -v
```
Expected: FAIL — sidecar engine isn't registered.

- [ ] **Step 5: Modify `engine/_discovery.py`**

Locate the engine-resolution path. Add a helper:

```python
def _maybe_register_mining_sidecar_engine() -> None:
    """If a mining sidecar exists, register a derived vLLM engine pointing
    at the mining endpoint.

    See Spec A §5.4. Idempotent — safe to call from any discovery path.
    """
    try:
        from openjarvis.mining import Sidecar
        from openjarvis.mining._constants import SIDECAR_PATH
    except ImportError:
        return
    payload = Sidecar.read(SIDECAR_PATH)
    if payload is None:
        return
    endpoint = payload.get("vllm_endpoint")
    model = payload.get("model")
    if not endpoint or not model:
        return

    from openjarvis.core.registry import EngineRegistry
    from openjarvis.engine.openai_compat_engines import OpenAICompatEngine  # adjust to actual class name

    if EngineRegistry.contains("vllm-pearl-mining"):
        return

    # Construct an instance bound to the mining endpoint and register it.
    instance = OpenAICompatEngine(
        engine_id="vllm-pearl-mining",
        base_url=endpoint,
        default_model=model,
    )
    EngineRegistry.register_value("vllm-pearl-mining", instance)
```

Call `_maybe_register_mining_sidecar_engine()` from `discover_engines()` after the existing engine-detection logic and before returning.

> **Note for the implementer:** Verify the actual class name of the OpenAI-compatible engine wrapper in `engine/openai_compat_engines.py` and adjust the import + constructor accordingly. The registry key must be `"vllm-pearl-mining"` exactly.

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/engine/test_discovery.py -k mining_sidecar -v
```
Expected: 2 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/engine/_discovery.py tests/conftest.py tests/mining/conftest.py tests/engine/test_discovery.py
git commit -m "feat(mining): engine discovery picks up runtime sidecar"
```

---

## Task 10 — `MiningTelemetryCollector` (shipped unwired)

**Files:**
- Create: `src/openjarvis/mining/_collector.py`
- Create: `tests/mining/test_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mining/test_collector.py`:

```python
"""Tests for MiningTelemetryCollector — shipped in v1 but unwired."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_collector_collect_once_returns_stats(written_sidecar):
    from openjarvis.mining._collector import MiningTelemetryCollector

    sample = (
        "pearl_gateway_shares_submitted_total 50\n"
        "pearl_gateway_shares_accepted_total 49\n"
    )
    with patch("openjarvis.mining._collector.httpx.get") as get:
        get.return_value.status_code = 200
        get.return_value.text = sample
        store = MagicMock()
        c = MiningTelemetryCollector(
            sidecar_path=written_sidecar, telemetry_store=store, interval_s=0.05
        )
        stats = await c.collect_once()
        assert stats.shares_submitted == 50
        assert stats.shares_accepted == 49


@pytest.mark.asyncio
async def test_collector_run_loop_writes_to_store_then_stops(written_sidecar):
    from openjarvis.mining._collector import MiningTelemetryCollector

    sample = "pearl_gateway_shares_submitted_total 1\n"
    with patch("openjarvis.mining._collector.httpx.get") as get:
        get.return_value.status_code = 200
        get.return_value.text = sample
        store = MagicMock()
        c = MiningTelemetryCollector(
            sidecar_path=written_sidecar, telemetry_store=store, interval_s=0.01
        )
        # Run the loop briefly and stop.
        task = asyncio.create_task(c.run())
        await asyncio.sleep(0.05)
        c.stop()
        await asyncio.wait_for(task, timeout=1.0)
        assert store.record_mining_stats.call_count >= 1


@pytest.mark.asyncio
async def test_collector_handles_gateway_errors_gracefully(written_sidecar):
    from openjarvis.mining._collector import MiningTelemetryCollector

    with patch("openjarvis.mining._collector.httpx.get") as get:
        get.side_effect = ConnectionError("nope")
        store = MagicMock()
        c = MiningTelemetryCollector(
            sidecar_path=written_sidecar, telemetry_store=store
        )
        stats = await c.collect_once()
        assert stats.last_error is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/mining/test_collector.py -v
```
Expected: 3 FAIL.

- [ ] **Step 3: Implement the collector**

Create `src/openjarvis/mining/_collector.py`:

```python
# src/openjarvis/mining/_collector.py
"""Background poller for mining telemetry.

Shipped in v1 but **not wired into the gateway daemon**. v1.x will register
this as a periodic asyncio task in ``openjarvis.daemon.gateway``. v1's
status command reads on-demand instead — see ``vllm_pearl.VllmPearlProvider.stats``.

Why ship now? Lighting up the collector in v1.x is a one-line change in the
daemon. The contract (init signature, ``run()`` loop, ``collect_once()``,
``stop()``) is fixed by this v1 ship to prevent API churn.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from openjarvis.mining._metrics import parse_gateway_metrics
from openjarvis.mining._stubs import MiningStats, Sidecar

log = logging.getLogger(__name__)


class MiningTelemetryCollector:
    """Periodically polls the Pearl gateway and writes ``MiningStats`` to a
    telemetry store.

    ``telemetry_store`` is duck-typed: must implement
    ``record_mining_stats(stats: MiningStats) -> None``.
    """

    def __init__(
        self,
        sidecar_path: Path,
        telemetry_store: Any,
        interval_s: float = 30.0,
    ):
        self._sidecar_path = sidecar_path
        self._store = telemetry_store
        self._interval_s = interval_s
        self._stop = False

    async def collect_once(self) -> MiningStats:
        sidecar = Sidecar.read(self._sidecar_path)
        if sidecar is None:
            return MiningStats(provider_id="unknown")
        url = sidecar.get("gateway_metrics_url")
        provider_id = sidecar.get("provider", "unknown")
        if not url:
            return MiningStats(provider_id=provider_id)
        try:
            resp = httpx.get(f"{url}/metrics", timeout=5.0)
            if resp.status_code != 200:
                return MiningStats(
                    provider_id=provider_id,
                    last_error=f"gateway HTTP {resp.status_code}",
                )
            return parse_gateway_metrics(resp.text, provider_id=provider_id)
        except Exception as e:  # noqa: BLE001
            return MiningStats(provider_id=provider_id, last_error=str(e).splitlines()[0])

    async def run(self) -> None:
        while not self._stop:
            try:
                stats = await self.collect_once()
                self._store.record_mining_stats(stats)
            except Exception as e:  # noqa: BLE001
                log.warning("MiningTelemetryCollector tick error: %s", e)
            try:
                await asyncio.sleep(self._interval_s)
            except asyncio.CancelledError:
                break

    def stop(self) -> None:
        self._stop = True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/mining/test_collector.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/mining/_collector.py tests/mining/test_collector.py
git commit -m "feat(mining): MiningTelemetryCollector — shipped unwired for v1.x"
```

---

## Task 11 — Telemetry schema migration (`mining_session_id`)

**Files:**
- Modify: `src/openjarvis/telemetry/store.py`
- Test: `tests/telemetry/test_store.py` (existing — add new tests)

- [ ] **Step 1: Inspect existing `telemetry/store.py` migration approach**

Run:
```bash
grep -n "PRAGMA user_version\|CREATE TABLE\|ALTER TABLE\|migrate" src/openjarvis/telemetry/store.py | head -20
```

If `PRAGMA user_version` is already used, follow that convention. If migrations are inline `CREATE TABLE IF NOT EXISTS` only, switch to a versioned approach for this change. Document the chosen pattern in the commit message.

- [ ] **Step 2: Write failing tests**

Add to `tests/telemetry/test_store.py`:

```python
def test_inference_row_has_mining_session_id_column(tmp_path):
    from openjarvis.telemetry.store import TelemetryStore
    db = tmp_path / "tel.db"
    store = TelemetryStore(db_path=db)
    store.record_inference(
        model="test-model",
        engine_id="test-engine",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=100.0,
    )
    # Default — null
    rows = store.list_recent(limit=1)
    assert "mining_session_id" in rows[0]
    assert rows[0]["mining_session_id"] is None


def test_inference_row_can_be_tagged_with_mining_session_id(tmp_path):
    from openjarvis.telemetry.store import TelemetryStore
    db = tmp_path / "tel.db"
    store = TelemetryStore(db_path=db)
    store.record_inference(
        model="test-model",
        engine_id="vllm-pearl-mining",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=100.0,
        mining_session_id="abc123",
    )
    rows = store.list_recent(limit=1)
    assert rows[0]["mining_session_id"] == "abc123"


def test_record_mining_stats_persists(tmp_path):
    from openjarvis.telemetry.store import TelemetryStore
    from openjarvis.mining._stubs import MiningStats
    db = tmp_path / "tel.db"
    store = TelemetryStore(db_path=db)
    store.record_mining_stats(
        MiningStats(provider_id="vllm-pearl", shares_submitted=42, shares_accepted=40)
    )
    snapshots = store.list_recent_mining_stats(limit=1)
    assert snapshots[0]["shares_submitted"] == 42
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/telemetry/test_store.py -k mining -v
```
Expected: FAIL.

- [ ] **Step 4: Implement the migration**

In `src/openjarvis/telemetry/store.py`:

1. Bump the schema version constant by 1 (or introduce one if absent).
2. Add a migration step: `ALTER TABLE inference ADD COLUMN mining_session_id TEXT NULL;` guarded by the version bump.
3. Add a `mining_stats` table with appropriate columns: `provider_id`, `shares_submitted`, `shares_accepted`, `blocks_found`, `hashrate`, `uptime_seconds`, `last_share_at`, `last_error`, `payout_target`, `fees_owed`, `recorded_at`.
4. Add `record_inference(..., mining_session_id: Optional[str] = None)` parameter — keep it kwargs-only and defaulted so callers don't change.
5. Add `record_mining_stats(stats: MiningStats) -> None`.
6. Add `list_recent_mining_stats(limit: int = 50) -> list[dict]`.
7. Update `list_recent()` to include `mining_session_id` in returned rows.

Exact SQL:

```sql
-- migrate_v<N>_to_v<N+1>:
ALTER TABLE inference ADD COLUMN mining_session_id TEXT;

CREATE TABLE IF NOT EXISTS mining_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at REAL NOT NULL,
    provider_id TEXT NOT NULL,
    shares_submitted INTEGER NOT NULL DEFAULT 0,
    shares_accepted INTEGER NOT NULL DEFAULT 0,
    blocks_found INTEGER NOT NULL DEFAULT 0,
    hashrate REAL NOT NULL DEFAULT 0,
    uptime_seconds REAL NOT NULL DEFAULT 0,
    last_share_at REAL,
    last_error TEXT,
    payout_target TEXT NOT NULL DEFAULT 'solo',
    fees_owed INTEGER NOT NULL DEFAULT 0
);
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/telemetry/test_store.py -v
```
Expected: ALL PASS (existing tests + 3 new).

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/telemetry/store.py tests/telemetry/test_store.py
git commit -m "feat(telemetry): add mining_session_id + mining_stats table"
```

---

## Task 12 — `jarvis mine doctor` (highest user-facing value, build first)

**Files:**
- Create: `src/openjarvis/cli/mine_cmd.py`
- Create: `tests/mining/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/mining/test_cli.py`:

```python
"""CLI smoke tests via Click CliRunner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner


def test_mine_doctor_prints_capability_matrix(monkeypatch):
    from openjarvis.cli.mine_cmd import mine
    runner = CliRunner()

    # Force the H100 hardware fixture so detect() returns supported.
    from openjarvis.core.config import GpuInfo, HardwareInfo
    fake_hw = HardwareInfo(
        platform="linux",
        gpu=GpuInfo(
            vendor="nvidia", name="H100", vram_gb=80.0,
            compute_capability="9.0", count=1,
        ),
    )
    with patch("openjarvis.cli.mine_cmd._detect_hardware", return_value=fake_hw), \
         patch("openjarvis.cli.mine_cmd.check_docker_available", return_value=(True, "running 24.0.7")), \
         patch("openjarvis.cli.mine_cmd.check_disk_free", return_value=(True, "300 GB free")), \
         patch("openjarvis.cli.mine_cmd.check_pearld_reachable", return_value=(True, "block height 442107 (synced)")):
        result = runner.invoke(mine, ["doctor"])
    assert result.exit_code == 0, result.output
    out = result.output.lower()
    assert "hardware" in out
    assert "docker" in out
    assert "pearl" in out
    assert "vllm-pearl" in out


def test_mine_doctor_flags_unsupported_hardware():
    from openjarvis.cli.mine_cmd import mine
    runner = CliRunner()

    from openjarvis.core.config import GpuInfo, HardwareInfo
    fake_hw = HardwareInfo(
        platform="linux",
        gpu=GpuInfo(
            vendor="nvidia", name="RTX 4090", vram_gb=24.0,
            compute_capability="8.9", count=1,
        ),
    )
    with patch("openjarvis.cli.mine_cmd._detect_hardware", return_value=fake_hw), \
         patch("openjarvis.cli.mine_cmd.check_docker_available", return_value=(True, "ok")), \
         patch("openjarvis.cli.mine_cmd.check_disk_free", return_value=(True, "300 GB free")), \
         patch("openjarvis.cli.mine_cmd.check_pearld_reachable", return_value=(False, "connection refused")):
        result = runner.invoke(mine, ["doctor"])
    assert result.exit_code == 0
    assert "✗" in result.output or "FAIL" in result.output.upper()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/mining/test_cli.py::test_mine_doctor_prints_capability_matrix -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `mine_cmd.py` with the `doctor` subcommand**

```python
# src/openjarvis/cli/mine_cmd.py
"""``jarvis mine`` command group.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``
section 6 for the full CLI surface.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click

from openjarvis.core.config import HardwareInfo, load_config
from openjarvis.mining._constants import (
    DEFAULT_PEARL_MODEL,
    DEFAULT_PEARLD_RPC_URL,
    PEARL_IMAGE_TAG,
    SIDECAR_PATH,
)
from openjarvis.mining._discovery import (
    check_disk_free,
    check_docker_available,
    check_pearld_reachable,
    check_wallet_address_format,
    detect_for_engine_model,
)
from openjarvis.mining._stubs import Sidecar


def _detect_hardware() -> HardwareInfo:
    """Wrapper to make hardware detection mockable in CLI tests."""
    return load_config().hardware


@click.group()
def mine() -> None:
    """Pearl PoUW mining commands.

    See https://open-jarvis.github.io/OpenJarvis/user-guide/mining/ for the
    full guide.
    """


@mine.command()
def doctor() -> None:
    """Diagnose mining capability with one row per check."""
    hw = _detect_hardware()
    cfg = load_config()
    mining_cfg = cfg.mining

    def row(group: str, name: str, ok: bool, info: str) -> None:
        marker = "✓" if ok else "✗"
        click.echo(f"  {name:<22} {info:<35} {marker}")

    click.echo("Hardware")
    row("hw", "GPU vendor", hw.gpu.vendor == "nvidia" if hw.gpu else False,
        hw.gpu.vendor if hw.gpu else "(no GPU)")
    cc_ok = bool(hw.gpu and hw.gpu.compute_capability.startswith("9.0"))
    row("hw", "Compute capability", cc_ok,
        hw.gpu.compute_capability if hw.gpu else "n/a")
    vram = hw.gpu.vram_gb if hw.gpu else 0
    row("hw", "VRAM", vram >= 70, f"{vram:.0f} GB")

    click.echo("Docker")
    ok, info = check_docker_available()
    row("docker", "Daemon", ok, info)

    click.echo("Disk")
    ok, info = check_disk_free(Path.home())
    row("disk", "Free in HF cache", ok, info)

    click.echo("Pearl node")
    if mining_cfg is not None:
        url = mining_cfg.extra.get("pearld_rpc_url", DEFAULT_PEARLD_RPC_URL)
        user = mining_cfg.extra.get("pearld_rpc_user", "rpcuser")
        password_env = mining_cfg.extra.get(
            "pearld_rpc_password_env", "PEARLD_RPC_PASSWORD"
        )
        password = os.environ.get(password_env, "")
        ok, info = check_pearld_reachable(url, user, password)
        row("pearld", "RPC", ok, info)
    else:
        row("pearld", "RPC", False, "no [mining] config — run `jarvis mine init`")

    click.echo("Wallet")
    if mining_cfg is not None:
        ok, info = check_wallet_address_format(mining_cfg.wallet_address)
        row("wallet", "Address format", ok, info)

    click.echo("Provider capability")
    if mining_cfg is not None:
        cap = detect_for_engine_model(
            hw=hw, engine_id="vllm",
            model=mining_cfg.extra.get("model", DEFAULT_PEARL_MODEL),
            provider_id=mining_cfg.provider,
        )
        marker = "SUPPORTED" if cap.supported else f"UNSUPPORTED — {cap.reason}"
        click.echo(f"  vllm-pearl              {marker}")

    click.echo("Session")
    sidecar = Sidecar.read(SIDECAR_PATH)
    if sidecar is None:
        click.echo("  Sidecar                absent (not running)")
    else:
        click.echo(f"  Sidecar                present ({SIDECAR_PATH})")
        click.echo(f"  Container              {sidecar.get('container_id', '?')}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/mining/test_cli.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/cli/mine_cmd.py tests/mining/test_cli.py
git commit -m "feat(mining-cli): jarvis mine doctor"
```

---

## Task 13 — `jarvis mine init / start / stop`

**Files:**
- Modify: `src/openjarvis/cli/mine_cmd.py`
- Modify: `tests/mining/test_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/mining/test_cli.py`:

```python
def test_mine_start_runs_provider_start(monkeypatch):
    from openjarvis.cli.mine_cmd import mine
    runner = CliRunner()
    fake_provider_class = MagicMock()
    fake_provider_class.return_value.start = MagicMock(return_value=None)
    with patch("openjarvis.cli.mine_cmd.MinerRegistry") as reg, \
         patch("openjarvis.cli.mine_cmd.load_config") as load, \
         patch("openjarvis.cli.mine_cmd.asyncio.run") as arun:
        from openjarvis.mining._stubs import MiningConfig, SoloTarget
        load.return_value = MagicMock(mining=MiningConfig(
            provider="vllm-pearl",
            wallet_address="prl1qaaa",
            submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        ))
        reg.get.return_value = fake_provider_class
        result = runner.invoke(mine, ["start"])
    assert result.exit_code == 0
    arun.assert_called_once()


def test_mine_stop_calls_provider_stop():
    from openjarvis.cli.mine_cmd import mine
    runner = CliRunner()
    fake_provider_class = MagicMock()
    with patch("openjarvis.cli.mine_cmd.MinerRegistry") as reg, \
         patch("openjarvis.cli.mine_cmd.load_config") as load, \
         patch("openjarvis.cli.mine_cmd.asyncio.run") as arun:
        from openjarvis.mining._stubs import MiningConfig, SoloTarget
        load.return_value = MagicMock(mining=MiningConfig(
            provider="vllm-pearl",
            wallet_address="prl1qaaa",
            submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        ))
        reg.get.return_value = fake_provider_class
        result = runner.invoke(mine, ["stop"])
    assert result.exit_code == 0


def test_mine_start_errors_when_no_mining_config():
    from openjarvis.cli.mine_cmd import mine
    runner = CliRunner()
    with patch("openjarvis.cli.mine_cmd.load_config") as load:
        load.return_value = MagicMock(mining=None)
        result = runner.invoke(mine, ["start"])
    assert result.exit_code != 0
    assert "init" in result.output.lower() or "no [mining]" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/mining/test_cli.py -v
```
Expected: 3 new FAIL.

- [ ] **Step 3: Implement `init`, `start`, `stop`**

Append to `mine_cmd.py`:

```python
import asyncio
from openjarvis.core.registry import MinerRegistry


@mine.command()
@click.option("--wallet", prompt="Pearl Taproot wallet address (prl1q...)")
@click.option("--pearld-url", default=DEFAULT_PEARLD_RPC_URL,
              prompt="pearld RPC URL")
@click.option("--pearld-user", default="rpcuser", prompt="pearld RPC user")
@click.option("--pearld-password-env", default="PEARLD_RPC_PASSWORD",
              prompt="env var holding pearld password")
@click.option("--model", default=DEFAULT_PEARL_MODEL)
@click.option("--image", default=PEARL_IMAGE_TAG)
def init(
    wallet: str,
    pearld_url: str,
    pearld_user: str,
    pearld_password_env: str,
    model: str,
    image: str,
) -> None:
    """Interactive setup. Validates capability, writes [mining] config, pulls/builds image."""
    # Pre-checks
    hw = _detect_hardware()
    cap = detect_for_engine_model(
        hw=hw, engine_id="vllm", model=model, provider_id="vllm-pearl",
    )
    if not cap.supported:
        raise click.ClickException(
            f"vllm-pearl not supported on this host: {cap.reason}\n"
            f"See `jarvis mine doctor` for details."
        )

    ok, info = check_docker_available()
    if not ok:
        raise click.ClickException(f"Docker unavailable: {info}")

    ok, info = check_disk_free(Path.home())
    if not ok:
        raise click.ClickException(f"Insufficient disk: {info}")

    if pearld_password_env not in os.environ:
        click.echo(
            f"Warning: ${pearld_password_env} is not set in your environment. "
            f"Set it before `jarvis mine start`.",
            err=True,
        )

    ok, info = check_wallet_address_format(wallet)
    if not ok:
        raise click.ClickException(f"Invalid wallet address: {info}")

    # Write config (preserves any existing config sections; appends [mining])
    config_path = Path.home() / ".openjarvis" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    new_section = f"""
[mining]
provider           = "vllm-pearl"
wallet_address     = "{wallet}"
submit_target      = "solo"
fee_bps            = 0
fee_payout_address = ""

[mining.extra]
docker_image_tag         = "{image}"
model                    = "{model}"
gateway_port             = 8337
gateway_metrics_port     = 8339
vllm_port                = 8000
gpu_memory_utilization   = 0.9
max_model_len            = 8192
pearld_rpc_url           = "{pearld_url}"
pearld_rpc_user          = "{pearld_user}"
pearld_rpc_password_env  = "{pearld_password_env}"
hf_token_env             = "HF_TOKEN"
"""
    if config_path.exists():
        existing = config_path.read_text()
        if "[mining]" in existing:
            click.echo("[mining] section already present; not overwriting. Edit manually if needed.")
            return
        config_path.write_text(existing + new_section)
    else:
        config_path.write_text(new_section)

    # Pull/build image
    click.echo(f"Resolving image {image}... (build may take 30-60 min on first run)")
    import docker
    from openjarvis.mining._docker import PearlDockerLauncher
    launcher = PearlDockerLauncher(client=docker.from_env())
    launcher.ensure_image(image)
    click.echo(f"Done. Run `jarvis mine start` to begin mining.")


@mine.command()
def start() -> None:
    """Launch the Pearl mining container and write the runtime sidecar."""
    cfg = load_config().mining
    if cfg is None:
        raise click.ClickException("no [mining] section in config — run `jarvis mine init`")
    provider_cls = MinerRegistry.get(cfg.provider)
    provider = provider_cls()

    async def _run():
        await provider.start(cfg)
    asyncio.run(_run())
    click.echo(f"Mining started. Run `jarvis mine status` for live stats.")


@mine.command()
def stop() -> None:
    """Stop the Pearl mining container and remove the sidecar."""
    cfg = load_config().mining
    if cfg is None:
        click.echo("no [mining] section — nothing to stop")
        return
    provider_cls = MinerRegistry.get(cfg.provider)
    provider = provider_cls()

    async def _run():
        await provider.stop()
    asyncio.run(_run())
    click.echo("Mining stopped.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/mining/test_cli.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/cli/mine_cmd.py tests/mining/test_cli.py
git commit -m "feat(mining-cli): jarvis mine init/start/stop"
```

---

## Task 14 — `jarvis mine status / attach / logs`

**Files:**
- Modify: `src/openjarvis/cli/mine_cmd.py`
- Modify: `tests/mining/test_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/mining/test_cli.py`:

```python
def test_mine_status_renders_stats(written_sidecar, monkeypatch):
    from openjarvis.cli.mine_cmd import mine
    runner = CliRunner()
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", written_sidecar)
    sample = (
        "pearl_gateway_shares_submitted_total 100\n"
        "pearl_gateway_shares_accepted_total 99\n"
        "pearl_gateway_blocks_found_total 2\n"
    )
    with patch("openjarvis.mining.vllm_pearl.httpx.get") as get, \
         patch("openjarvis.cli.mine_cmd.MinerRegistry") as reg:
        get.return_value.status_code = 200
        get.return_value.text = sample
        from openjarvis.mining.vllm_pearl import VllmPearlProvider
        reg.get.return_value = lambda: VllmPearlProvider(docker_client=MagicMock())
        result = runner.invoke(mine, ["status"])
    assert result.exit_code == 0
    assert "100" in result.output


def test_mine_attach_writes_sidecar(tmp_path, monkeypatch):
    from openjarvis.cli.mine_cmd import mine
    runner = CliRunner()
    sidecar = tmp_path / "mining.json"
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar)
    result = runner.invoke(mine, [
        "attach",
        "--vllm-endpoint", "http://127.0.0.1:8000/v1",
        "--gateway-url", "http://127.0.0.1:8337",
        "--gateway-metrics-url", "http://127.0.0.1:8339",
        "--model", "pearl-ai/Llama-3.3-70B-Instruct-pearl",
    ])
    assert result.exit_code == 0
    assert sidecar.exists()


def test_mine_logs_streams_container_output(monkeypatch):
    from openjarvis.cli.mine_cmd import mine
    runner = CliRunner()
    fake_launcher = MagicMock()
    fake_launcher.get_logs.return_value = "log line 1\nlog line 2\n"
    with patch("openjarvis.cli.mine_cmd.PearlDockerLauncher",
               return_value=fake_launcher):
        result = runner.invoke(mine, ["logs", "--tail", "100"])
    assert result.exit_code == 0
    assert "log line 1" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/mining/test_cli.py -v
```
Expected: 3 new FAIL.

- [ ] **Step 3: Implement `status`, `attach`, `logs`**

Append to `mine_cmd.py`:

```python
import time
from openjarvis.mining._docker import PearlDockerLauncher


@mine.command()
def status() -> None:
    """Print live mining stats from the gateway."""
    cfg = load_config().mining
    if cfg is None:
        raise click.ClickException("no [mining] section — run `jarvis mine init`")
    provider_cls = MinerRegistry.get(cfg.provider)
    provider = provider_cls()
    s = provider.stats()
    click.echo(f"provider:           {s.provider_id}")
    click.echo(f"shares submitted:   {s.shares_submitted}")
    click.echo(f"shares accepted:    {s.shares_accepted}")
    click.echo(f"blocks found:       {s.blocks_found}")
    click.echo(f"hashrate:           {s.hashrate:.2f}")
    click.echo(f"uptime (s):         {s.uptime_seconds:.0f}")
    click.echo(f"last share at:      {s.last_share_at or '—'}")
    click.echo(f"last error:         {s.last_error or '—'}")
    click.echo(f"payout target:      {s.payout_target}")
    click.echo(f"fees owed:          {s.fees_owed}")


@mine.command()
@click.option("--vllm-endpoint", required=True)
@click.option("--gateway-url", required=True)
@click.option("--gateway-metrics-url", required=True)
@click.option("--model", default=DEFAULT_PEARL_MODEL)
@click.option("--container-id", default="external")
@click.option("--wallet", default="")
def attach(
    vllm_endpoint: str,
    gateway_url: str,
    gateway_metrics_url: str,
    model: str,
    container_id: str,
    wallet: str,
) -> None:
    """Manual mode — write a sidecar pointing at a Pearl container you started yourself."""
    Sidecar.write(SIDECAR_PATH, {
        "provider": "vllm-pearl",
        "vllm_endpoint": vllm_endpoint,
        "model": model,
        "gateway_url": gateway_url,
        "gateway_metrics_url": gateway_metrics_url,
        "container_id": container_id,
        "wallet_address": wallet,
        "started_at": int(time.time()),
    })
    click.echo(f"Sidecar written to {SIDECAR_PATH}")


@mine.command()
@click.option("-n", "--tail", "tail_n", default=200, type=int)
@click.option("-f", "--follow", is_flag=True, default=False,
              help="Follow logs (not supported in v1 — equivalent to --tail).")
def logs(tail_n: int, follow: bool) -> None:
    """Tail the Pearl mining container logs."""
    if follow:
        click.echo("note: -f follow not implemented in v1; printing tail and exiting", err=True)
    import docker
    launcher = PearlDockerLauncher(client=docker.from_env())
    # Re-attach to the running container by name.
    try:
        container = docker.from_env().containers.get("openjarvis-pearl-miner")
        launcher._container = container
    except Exception as e:  # noqa: BLE001
        raise click.ClickException(f"no running mining container: {e}")
    click.echo(launcher.get_logs(tail=tail_n))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/mining/test_cli.py -v
```
Expected: 8 PASS (cumulative).

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/cli/mine_cmd.py tests/mining/test_cli.py
git commit -m "feat(mining-cli): jarvis mine status/attach/logs"
```

---

## Task 15 — Register `mine` group; add hint

**Files:**
- Modify: `src/openjarvis/cli/__init__.py`
- Modify: `src/openjarvis/cli/hints.py`
- Test: `tests/cli/test_main.py` (or wherever CLI registration is tested)
- Test: `tests/cli/test_hints.py` (existing)

- [ ] **Step 1: Inspect current `cli/__init__.py`**

```bash
sed -n '1,50p' src/openjarvis/cli/__init__.py
grep -n "add_command\|@main.command\|main.add_command" src/openjarvis/cli/__init__.py | head -20
```

Identify how other commands are registered.

- [ ] **Step 2: Write failing test**

Add to `tests/cli/test_main.py` (create if absent):

```python
def test_mine_subcommand_registered():
    from click.testing import CliRunner
    from openjarvis.cli import main
    runner = CliRunner()
    result = runner.invoke(main, ["mine", "--help"])
    assert result.exit_code == 0
    assert "doctor" in result.output
    assert "start" in result.output
    assert "stop" in result.output
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/cli/test_main.py::test_mine_subcommand_registered -v
```

- [ ] **Step 4: Register the group**

Add to `cli/__init__.py` near other `add_command` calls:

```python
from openjarvis.cli.mine_cmd import mine
main.add_command(mine)
```

- [ ] **Step 5: Add the hint**

In `cli/hints.py`, add a function (or extend existing hint logic) that emits one line when `[mining]` is configured but no sidecar exists:

```python
def mining_not_running_hint(cfg, sidecar_present: bool) -> Optional[str]:
    if cfg is None or sidecar_present:
        return None
    return "mining configured but not running — start it with `jarvis mine start`"
```

Wire it into wherever hints are surfaced (read existing hint integration points first; mirror the pattern).

- [ ] **Step 6: Add tests for the hint**

Add to `tests/cli/test_hints.py`:

```python
def test_mining_not_running_hint_when_configured_no_sidecar():
    from openjarvis.cli.hints import mining_not_running_hint
    cfg = object()  # any truthy stand-in for MiningConfig
    msg = mining_not_running_hint(cfg, sidecar_present=False)
    assert msg is not None
    assert "jarvis mine start" in msg


def test_mining_not_running_hint_silent_when_running():
    from openjarvis.cli.hints import mining_not_running_hint
    msg = mining_not_running_hint(object(), sidecar_present=True)
    assert msg is None


def test_mining_not_running_hint_silent_when_unconfigured():
    from openjarvis.cli.hints import mining_not_running_hint
    msg = mining_not_running_hint(None, sidecar_present=False)
    assert msg is None
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
uv run pytest tests/cli/test_main.py tests/cli/test_hints.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/openjarvis/cli/__init__.py src/openjarvis/cli/hints.py tests/cli/test_main.py tests/cli/test_hints.py
git commit -m "feat(mining-cli): register `mine` group + add not-running hint"
```

---

## Task 16 — `pyproject.toml` updates

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `mining-pearl` extra**

In `pyproject.toml` `[project.optional-dependencies]`, alphabetical position (after `media`, before `openhands`):

```toml
mining-pearl = ["docker>=7.0", "httpx>=0.27"]
```

- [ ] **Step 2: Add `docker` pytest marker**

In `pyproject.toml` under `[tool.pytest.ini_options].markers`, add (alphabetical):

```toml
"docker: requires a working Docker daemon (no GPU required)",
```

- [ ] **Step 3: Verify uv lock is updated**

```bash
uv lock
```

Diff `uv.lock` for any unintended changes (only `docker` and `httpx` entries should be new).

- [ ] **Step 4: Verify CI command still passes**

```bash
uv sync --extra dev
uv run pytest tests/ -m "not live and not cloud and not docker" -v
```

Expected: pass (or fail only on tests unrelated to this work).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add mining-pearl extra and docker pytest marker"
```

---

## Task 17 — Documentation

**Files:**
- Create: `docs/user-guide/mining.md`
- Create: `docs/development/mining.md`
- Modify: `CLAUDE.md` (note: gitignored locally — write only if your local copy expects it)
- Modify: `REVIEW.md`

- [ ] **Step 1: Write `docs/user-guide/mining.md`**

```markdown
# Pearl mining

OpenJarvis can mine the [Pearl](https://github.com/pearl-research-labs/pearl)
Proof-of-Useful-Work blockchain through your local LLM inference. v1
supports H100/H200 hosts running vLLM. Apple Silicon, AMD, and other
inference backends are tracked separately — see [Spec B](../design/2026-05-05-apple-silicon-pearl-mining-design.md).

## Prerequisites

| | |
|---|---|
| GPU | NVIDIA H100 or H200 (sm_90a) with ≥ 70 GB VRAM |
| OS | Linux with `nvidia-container-toolkit` installed |
| Docker | 24+, GPU runtime configured |
| Disk | ≥ 200 GB free for the 70B model + headroom |
| Network | Reachable pearld node (default `http://localhost:44107`) |
| Wallet | A Pearl Taproot address (`prl1q...`) generated via Pearl's `oyster` CLI |

## Quick start

```bash
uv sync --extra mining-pearl
export PEARLD_RPC_PASSWORD=<your-pearld-password>
export HF_TOKEN=<your-hf-token>
uv run jarvis mine init    # writes [mining] config + builds Docker image (30-60 min first time)
uv run jarvis mine start
uv run jarvis mine status
```

## Diagnosing problems

`jarvis mine doctor` prints one row per check with a clear ✓ or ✗ and reason.
Read top-down — fix what's failing before retrying `mine start`.

## What v1 does NOT support

- Pool mining or any OJ fee — solo only, you keep 100%
- Apple Silicon, AMD, sm_89 NVIDIA (RTX 4090), CPU-only — protocol-blocked
  on Pearl shipping non-CUDA / non-Hopper kernels
- Wallet generation inside OJ — bring your own address

## What's coming

- v2: pool support and a 20% OJ fee for joining a shared variance-reduction pool
- Apple Silicon path tracked in [Spec B](../design/2026-05-05-apple-silicon-pearl-mining-design.md)
```

- [ ] **Step 2: Write `docs/development/mining.md`**

```markdown
# Adding a new mining provider

The `openjarvis.mining` subsystem uses a registry pattern identical to
`engine/`, `agents/`, etc. To add a new provider (e.g., for Apple Silicon,
AMD, or a future engine), implement the `MiningProvider` ABC and register
via `@MinerRegistry.register("<key>")`.

## Steps

1. Create `src/openjarvis/mining/<provider>.py`.
2. Subclass `openjarvis.mining.MiningProvider`.
3. Implement `detect()`, `start()`, `stop()`, `is_running()`, `stats()`.
4. Define an idempotent `ensure_registered()` (required for test isolation —
   see `tests/conftest.py` autouse clear).
5. Add a soft-import in `mining/__init__.py`:
   ```python
   try:
       from openjarvis.mining import <provider>  # noqa: F401
       <provider>.ensure_registered()
   except ImportError:
       pass
   ```
6. Add an optional dep extra in `pyproject.toml` (`mining-pearl-<key>`).
7. Add tests in `tests/mining/test_<provider>.py` mirroring
   `test_vllm_pearl.py`.

## Working example

The Apple Silicon path is the canonical worked example —
see [Spec B](../design/2026-05-05-apple-silicon-pearl-mining-design.md)
section 7 for the full provider template.
```

- [ ] **Step 3: Add `CLAUDE.md` paragraph (if your local copy is intended to be edited)**

If your local `CLAUDE.md` exists and is intended for editing, add this paragraph under the Architecture section listing the primitives:

```markdown
- `mining/` — `MiningProvider` ABC + `MinerRegistry`. v1's only impl is `vllm_pearl.py` (Pearl Docker container orchestrator). Soft-imported via `mining/__init__.py`'s `try/except ImportError` per OJ's optional-deps pattern. Future providers (Apple Silicon, AMD, Ollama) drop in via the registry without rewrite. See `docs/design/2026-05-05-vllm-pearl-mining-integration-design.md`.
```

> CLAUDE.md may be in `.gitignore` in this repo. Check before adding to a commit.

- [ ] **Step 4: Add `REVIEW.md` bullet**

In `REVIEW.md` under "Registry pattern compliance" (or the closest equivalent bullet about new components needing registry registration), add:

```markdown
- New mining providers must register via `MinerRegistry` in `src/openjarvis/core/registry.py` and expose an idempotent `ensure_registered()` per the autouse-clear test convention.
```

- [ ] **Step 5: Run mkdocs locally to verify rendering**

```bash
uv sync --extra docs
uv run mkdocs build
```

Expected: build succeeds. Inspect output for missing assets / broken links to the new pages.

- [ ] **Step 6: Commit**

```bash
git add docs/user-guide/mining.md docs/development/mining.md REVIEW.md
# only add CLAUDE.md if it isn't ignored:
git check-ignore -q CLAUDE.md || git add CLAUDE.md
git commit -m "docs: user + dev guides for mining; REVIEW bullet"
```

---

## Final verification

- [ ] **Step 1: Full test suite**

```bash
uv run pytest tests/ -v --tb=short -m "not live and not cloud and not docker"
```
Expected: PASS — every test, no regressions in other packages.

- [ ] **Step 2: Lint + format**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```
Expected: clean.

- [ ] **Step 3: Coverage**

```bash
uv run pytest tests/mining/ --cov=openjarvis.mining --cov-report=term-missing
```
Expected: ≥ 80% coverage on the new `mining/` package.

- [ ] **Step 4: Smoke `jarvis mine doctor` on a non-mining dev box**

```bash
uv run jarvis mine doctor
```
Expected: doctor runs, hardware/Docker/Pearl rows print honest ✗ where applicable, exit code 0.

- [ ] **Step 5: Open the implementation PR**

```bash
gh pr create --title "feat(mining): vllm-pearl integration (v1, Spec A)" --body "$(cat <<'EOF'
Implements [Spec A](docs/design/2026-05-05-vllm-pearl-mining-integration-design.md). Solo mining only, no pool, no fee. v2 seams in place per spec §8.5.

## Summary
- New `openjarvis.mining` subsystem with `MiningProvider` ABC + `MinerRegistry`
- `vllm-pearl` provider wrapping Pearl's Docker container
- Runtime sidecar (`~/.openjarvis/runtime/mining.json`) for engine ↔ mining handoff
- Telemetry: on-demand reads in v1; `MiningTelemetryCollector` shipped unwired for v1.x
- New CLI: `jarvis mine init|start|stop|status|doctor|attach|logs`
- New optional extra: `mining-pearl`
- New pytest marker: `docker`
- Docs: user guide, contributor guide, REVIEW.md update

## Test plan
- [x] `uv run pytest tests/ -m "not live and not cloud and not docker"`
- [x] `uv run ruff check src/ tests/`
- [x] `uv run ruff format --check src/ tests/`
- [x] `uv run mkdocs build`
- [ ] Manual smoke: `uv run jarvis mine doctor` on a non-mining dev box prints honest output
- [ ] Manual smoke (release-gate): full mine init → start → status → stop on a real H100 host
EOF
)"
```

---

## Self-review summary

**Spec coverage:** Every Spec A section maps to at least one task above:

| Spec section | Tasks |
|---|---|
| §4 Architecture & module layout | 1, 2 |
| §5 Config schema & engine attachment | 3, 9 |
| §6 CLI surface, lifecycle | 12, 13, 14, 15 |
| §7 Pearl Docker integration | 5, 6 |
| §8 Telemetry hooks & v2 seams | 7, 10, 11 |
| §9 Failure handling & test strategy | All tasks (TDD); 16 (markers) |
| §10 Documentation deliverables | 17 |
| §11 Open items | Surfaced inline at the implementation moment they affect (e.g., the implementer notes in Tasks 7, 9, 11) |

**Type consistency:** `MiningCapabilities`, `MiningConfig`, `MiningStats`, `SoloTarget`, `PoolTarget`, `Sidecar`, `MiningProvider`, `MinerRegistry`, `VllmPearlProvider` — names and signatures consistent across all tasks.

**Placeholder scan:** No `TBD`, `TODO`, `add appropriate error handling`, or undefined-but-referenced types. The single intentional TODO is the `PEARL_PINNED_REF = "main"` constant in Task 2 — that's an explicit implementer-time decision, called out in `_constants.py`'s docstring and Spec A §11 Open Item #2. The Prometheus-fixture file is a placeholder by spec design (Task 7 step 1's note explains the capture procedure).
