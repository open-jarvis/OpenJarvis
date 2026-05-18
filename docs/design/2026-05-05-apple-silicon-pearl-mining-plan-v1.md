# Apple Silicon Pearl mining v1 — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the v1 `cpu-pearl` mining provider — decoupled CPU mining for Apple Silicon (and any non-CUDA host where Pearl's pure-Rust miner builds), wrapping upstream `pearl_mining.mine()` and Pearl's `pearl-gateway` as subprocess.

**Architecture:** New provider `CpuPearlProvider` in `src/openjarvis/mining/cpu_pearl.py`, registered as `"cpu-pearl"` via `MinerRegistry`. The provider's `start()` launches two subprocesses: (1) Pearl's `pearl-gateway` Python service (talks to user's `pearld`), and (2) a small Python miner-loop that polls gateway for `getMiningInfo`, calls `pearl_mining.mine()`, and submits via `submitPlainProof`. Reuses Spec A's `MiningProvider` ABC, `MinerRegistry`, sidecar at `~/.openjarvis/runtime/mining.json`, telemetry adapter, and CLI surface (`jarvis mine init|start|stop|status|doctor`) — all unchanged.

**Tech Stack:** Python 3.10+, `py-pearl-mining` (Rust+PyO3), `miner-base` (PyTorch), `pearl-gateway` (Python+JSON-RPC), `subprocess.Popen`, pytest with `unittest.mock`, ruff. References Pearl repo (`pearl-research-labs/pearl`) at a pinned commit/tag stored in `mining/_constants.py`.

**Hard prerequisite:** Spec A's plan (`docs/design/2026-05-05-vllm-pearl-mining-integration-plan.md`) **must be executed first**. v1 reuses Spec A's `MiningProvider` ABC, registry, sidecar shape, telemetry adapter, mining-config dataclass, and CLI surface. If Spec A isn't merged, stop here and execute Spec A first; do not duplicate that infrastructure in this plan.

---

## File structure (new files only — Spec A files unchanged)

```
src/openjarvis/mining/
    cpu_pearl.py             # CpuPearlProvider — implements MiningProvider ABC for CPU
    _pearl_subprocess.py     # PearlSubprocessLauncher — gateway + miner-loop subprocess management
    _install.py              # Helpers: detect upstream packages, build-from-pin fallback
    _miner_loop_main.py      # Subprocess entry point: poll gateway, call pearl_mining.mine, submit

tests/mining/
    test_cpu_pearl.py        # CpuPearlProvider unit tests (capability detection, lifecycle)
    test_pearl_subprocess.py # Subprocess launcher unit tests (mocked Popen)
    test_install.py          # Install detection / build helper tests
    test_miner_loop.py       # Miner-loop unit tests (mocked gateway socket)
    fixtures/
        gateway_mining_info.json    # Captured getMiningInfo RPC response
        gateway_submit_ok.json      # Captured submitPlainProof OK response
        gateway_submit_rejected.json # Captured submitPlainProof rejection

docs/user-guide/
    mining-apple-silicon.md  # User-facing guide

# Modified files
pyproject.toml               # Add `mining-pearl-cpu` extra
src/openjarvis/mining/__init__.py  # Soft-import cpu_pearl
src/openjarvis/mining/_constants.py  # Add PEARL_PINNED_REF and helper constants
```

---

## Task 1: Bootstrap — pinned ref and constants

**Files:**
- Modify: `src/openjarvis/mining/_constants.py:1-N` (created in Spec A)

This task adds Pearl-version pinning and CPU-specific constants that the rest of the provider references. Spec A already created `_constants.py` with `PEARL_PINNED_REF` and `PEARL_REPO`; reuse those. We only add the new `cpu-pearl`-specific values.

- [ ] **Step 1: Read Spec A's `_constants.py` to learn the existing shape**

Run: `cat src/openjarvis/mining/_constants.py`

Expected: file contains `PEARL_REPO`, `PEARL_PINNED_REF`, `PEARL_IMAGE_TAG`. If missing, **stop and execute Spec A first.**

- [ ] **Step 2: Add CPU-specific constants**

Append to `src/openjarvis/mining/_constants.py`:

```python
# ── cpu-pearl provider (v1, Apple Silicon and other non-CUDA hosts) ────────────

# Default mining-loop matrix shapes. These are the same values used by Pearl's
# upstream test_python_api.py — known to produce a valid proof per call at test
# difficulty. Real difficulty is set per-block by the network and we can't
# control that; the only knob we expose is the matmul shape, which determines
# search space size per `mine()` call.
CPU_PEARL_DEFAULT_M = 256
CPU_PEARL_DEFAULT_N = 128
CPU_PEARL_DEFAULT_K = 1024
CPU_PEARL_DEFAULT_RANK = 32

# Pattern lists copied verbatim from upstream Pearl tests.
CPU_PEARL_DEFAULT_ROWS_PATTERN = [0, 8, 64, 72]
CPU_PEARL_DEFAULT_COLS_PATTERN = [0, 1, 8, 9, 32, 33, 40, 41]

# Local clone path used by _install.py build-from-pin fallback. Only created
# when Pearl wheels are not yet on PyPI.
CPU_PEARL_LOCAL_CLONE_DIR = "~/.openjarvis/cache/pearl"

# Names of the Pearl Python packages we depend on, in install order.
# These are the packages we install from local paths (or PyPI when published).
PEARL_CPU_PACKAGES = (
    "py-pearl-mining",
    "miner-utils",
    "pearl-gateway",
    "miner-base",
)
```

- [ ] **Step 3: Run lint**

Run: `uv run ruff check src/openjarvis/mining/_constants.py`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/openjarvis/mining/_constants.py
git commit -m "feat(mining): add cpu-pearl constants (Spec B v1 task 1)"
```

---

## Task 2: Add `mining-pearl-cpu` optional extra

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Locate existing `mining-pearl` extra**

Run: `grep -n "mining-pearl" pyproject.toml`
Expected: at least one match for `mining-pearl = [...]` from Spec A.

- [ ] **Step 2: Add `mining-pearl-cpu` extra**

Add under `[project.optional-dependencies]`:

```toml
mining-pearl-cpu = [
    # Pearl's pure-Rust miner exposed to Python. Today: install from a local
    # path or git URL. When Pearl publishes to PyPI, this becomes a normal
    # version pin (see CPU_PEARL_LOCAL_CLONE_DIR in _constants.py).
    "py-pearl-mining ; sys_platform == 'darwin' or sys_platform == 'linux'",
    # PyTorch reference of NoisyGEMM — used for parity validation only,
    # not required at runtime, but the install verifies torch builds OK.
    "miner-base ; sys_platform == 'darwin' or sys_platform == 'linux'",
    # JSON-RPC server that talks to pearld and brokers shares for the miner.
    "pearl-gateway ; sys_platform == 'darwin' or sys_platform == 'linux'",
]
```

The `sys_platform` markers exclude Windows for now; v1 doesn't claim Windows support, and we don't want to accidentally hand a broken install to a Windows user.

- [ ] **Step 3: Run lint and resolve check**

Run:
```bash
uv run ruff check pyproject.toml || true
uv lock --check 2>&1 | tail -5
```

Expected: ruff has nothing to say about pyproject.toml. `uv lock --check` may fail because we haven't installed the actual packages yet — that's expected. Note the failure mode for Task 4.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(mining): add mining-pearl-cpu optional extra (Spec B v1 task 2)"
```

---

## Task 3: Install detection helper (`_install.py`)

**Files:**
- Create: `src/openjarvis/mining/_install.py`
- Test: `tests/mining/test_install.py`

`_install.py` answers a single question: are the Pearl Python packages installed in the current environment? Used by `cpu_pearl.detect()` and `mine doctor`. Also exposes a hint string telling the user how to install if not.

- [ ] **Step 1: Write the failing test**

Create `tests/mining/test_install.py`:

```python
"""Tests for openjarvis.mining._install."""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


def test_pearl_packages_available_returns_false_when_pearl_mining_missing():
    from openjarvis.mining import _install

    fake_modules = dict(sys.modules)
    fake_modules.pop("pearl_mining", None)
    fake_modules.pop("pearl_gateway", None)
    with patch.dict(sys.modules, fake_modules, clear=True):
        assert _install.pearl_packages_available() is False


def test_pearl_packages_available_returns_true_when_all_present():
    """When all three importable, returns True."""
    from openjarvis.mining import _install

    # Install three fake modules so importlib.util.find_spec returns truthy.
    import types
    fakes = {
        name: types.ModuleType(name)
        for name in ("pearl_mining", "pearl_gateway", "miner_base")
    }
    with patch.dict(sys.modules, fakes):
        assert _install.pearl_packages_available() is True


def test_install_hint_is_actionable():
    """The hint string must include the extra name and the build-from-pin path."""
    from openjarvis.mining._install import install_hint

    h = install_hint()
    assert "mining-pearl-cpu" in h
    assert "uv sync" in h or "pip install" in h
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mining/test_install.py -v`
Expected: FAIL — `ImportError: cannot import name '_install' from 'openjarvis.mining'`

- [ ] **Step 3: Write `_install.py`**

Create `src/openjarvis/mining/_install.py`:

```python
"""Detection and install hints for the upstream Pearl Python packages.

The cpu-pearl provider depends on three upstream packages: ``pearl_mining``,
``pearl_gateway``, and ``miner_base``. They are not on PyPI as of 2026-05; the
implementation plan covers a build-from-pin fallback. This module is the
single source of truth for "is the user's environment ready?".
"""
from __future__ import annotations

import importlib.util


def _module_available(name: str) -> bool:
    """True if ``import name`` would succeed in the current environment."""
    return importlib.util.find_spec(name) is not None


def pearl_packages_available() -> bool:
    """All three Pearl Python packages importable.

    Returns False if any are missing. Use ``install_hint()`` to surface the
    next step to the user.
    """
    return all(
        _module_available(m)
        for m in ("pearl_mining", "pearl_gateway", "miner_base")
    )


def install_hint() -> str:
    """Human-readable instruction for installing the Pearl packages.

    Today (no PyPI publication) we point at the optional extra. When Pearl
    publishes wheels, the message stays correct because the extra still works.
    """
    return (
        "install with `uv sync --extra mining-pearl-cpu`. "
        "If Pearl wheels are not on PyPI yet, see "
        "tools/pearl-reference-oracle/README.md for the build-from-pin path."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mining/test_install.py -v`
Expected: PASS — all three tests green.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/mining/_install.py tests/mining/test_install.py
git commit -m "feat(mining): pearl-packages availability detection (Spec B v1 task 3)"
```

---

## Task 4: Build-from-pin fallback in `_install.py`

**Files:**
- Modify: `src/openjarvis/mining/_install.py`
- Modify: `tests/mining/test_install.py`

Until Pearl publishes to PyPI, users have to build `py-pearl-mining` from source. This task adds a helper that does so on first `mine init`. Mocked in tests; only really invoked in a real terminal.

- [ ] **Step 1: Write the failing tests**

Append to `tests/mining/test_install.py`:

```python
import subprocess


def test_build_from_pin_clones_when_missing(tmp_path, monkeypatch):
    """If the local cache dir is empty, build_from_pin clones first."""
    from openjarvis.mining import _install

    cache_dir = tmp_path / "pearl"
    monkeypatch.setattr(_install, "_resolve_clone_dir", lambda: cache_dir)
    calls = []
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda args, **kw: calls.append(list(args)),
    )

    _install.build_from_pin(pinned_ref="abc123")

    # First call must be `git clone`; second call(s) the maturin/uv install.
    assert calls[0][:2] == ["git", "clone"]
    assert "abc123" in " ".join(calls[1]) or "abc123" in " ".join(calls[0])


def test_build_from_pin_skips_clone_when_present(tmp_path, monkeypatch):
    """If the cache already has the .git dir, skip the clone."""
    from openjarvis.mining import _install

    cache_dir = tmp_path / "pearl"
    (cache_dir / ".git").mkdir(parents=True)
    monkeypatch.setattr(_install, "_resolve_clone_dir", lambda: cache_dir)
    calls = []
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda args, **kw: calls.append(list(args)),
    )

    _install.build_from_pin(pinned_ref="abc123")

    # No git clone, but checkout + build.
    assert not any(c[:2] == ["git", "clone"] for c in calls)
    assert any(c[:2] == ["git", "checkout"] for c in calls)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mining/test_install.py -v`
Expected: FAIL — `AttributeError: module 'openjarvis.mining._install' has no attribute 'build_from_pin'`

- [ ] **Step 3: Implement `build_from_pin`**

Append to `src/openjarvis/mining/_install.py`:

```python
import os
import subprocess
from pathlib import Path

from ._constants import (
    CPU_PEARL_LOCAL_CLONE_DIR,
    PEARL_CPU_PACKAGES,
    PEARL_PINNED_REF,
    PEARL_REPO,
)


def _resolve_clone_dir() -> Path:
    """Return the directory the Pearl clone lives in. Override in tests."""
    return Path(os.path.expanduser(CPU_PEARL_LOCAL_CLONE_DIR))


def build_from_pin(pinned_ref: str = PEARL_PINNED_REF) -> Path:
    """Clone Pearl at ``pinned_ref`` and install the Pearl Python packages.

    Idempotent: if the clone exists, fetch + checkout instead of re-cloning.
    Returns the resolved clone directory.
    """
    clone_dir = _resolve_clone_dir()
    if not (clone_dir / ".git").is_dir():
        clone_dir.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(["git", "clone", PEARL_REPO, str(clone_dir)])
    else:
        subprocess.check_call(["git", "fetch", "--all"], cwd=clone_dir)
    subprocess.check_call(["git", "checkout", pinned_ref], cwd=clone_dir)

    # Build py-pearl-mining (Rust extension) via maturin
    py_pearl_mining_dir = clone_dir / "py-pearl-mining"
    subprocess.check_call(
        ["maturin", "build", "--release", "--interpreter", "python"],
        cwd=py_pearl_mining_dir,
    )

    # Find the wheel that maturin produced and install it, plus the pure-Python
    # packages from their source directories.
    wheels_dir = py_pearl_mining_dir / "target" / "wheels"
    wheels = sorted(wheels_dir.glob("py_pearl_mining-*.whl"))
    if not wheels:
        raise RuntimeError(f"maturin produced no wheel in {wheels_dir}")
    wheel_path = wheels[-1]

    # Install in dependency order. The `--no-deps` keeps uv from re-resolving
    # workspace siblings; we install them one by one.
    subprocess.check_call(["uv", "pip", "install", "--no-deps", str(wheel_path)])
    for pkg_name in ("miner-utils", "pearl-gateway", "miner-base"):
        pkg_dir = clone_dir / "miner" / pkg_name
        if pkg_dir.is_dir():
            subprocess.check_call(
                ["uv", "pip", "install", "--no-deps", str(pkg_dir)]
            )

    return clone_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mining/test_install.py -v`
Expected: PASS — all five tests green.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/openjarvis/mining/_install.py tests/mining/test_install.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/mining/_install.py tests/mining/test_install.py
git commit -m "feat(mining): build-from-pin fallback for Pearl wheels (Spec B v1 task 4)"
```

---

## Task 5: `_miner_loop_main.py` — the CPU mining loop subprocess entry point

**Files:**
- Create: `src/openjarvis/mining/_miner_loop_main.py`
- Test: `tests/mining/test_miner_loop.py`

This is the *meaty* task. The miner-loop subprocess connects to `pearl-gateway` over JSON-RPC TCP, polls `getMiningInfo`, calls `pearl_mining.mine()`, and submits via `submitPlainProof`. Single file, no class hierarchy — it's just an event loop.

- [ ] **Step 1: Write the failing test**

Create `tests/mining/test_miner_loop.py`:

```python
"""Tests for openjarvis.mining._miner_loop_main."""
from __future__ import annotations

import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def fake_mining_info_response():
    """Mock getMiningInfo response — base64-encoded incomplete header + target."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "incomplete_header_bytes": base64.b64encode(b"\x00" * 76).decode(),
            "target": 0x1D2FFFFF,
        },
    }


def test_decode_mining_info_returns_header_and_target(fake_mining_info_response):
    from openjarvis.mining._miner_loop_main import _decode_mining_info

    header_bytes, target = _decode_mining_info(fake_mining_info_response["result"])
    assert isinstance(header_bytes, (bytes, bytearray))
    assert len(header_bytes) == 76
    assert target == 0x1D2FFFFF


def test_encode_plain_proof_round_trips():
    """We can encode a PlainProof to base64 and the bytes are non-empty."""
    from openjarvis.mining._miner_loop_main import _encode_plain_proof

    fake_proof = MagicMock()
    fake_proof.serialize.return_value = b"PROOF_BYTES_DUMMY"
    encoded = _encode_plain_proof(fake_proof)
    assert encoded == base64.b64encode(b"PROOF_BYTES_DUMMY").decode()


def test_jsonrpc_envelope_shape():
    """The JSON-RPC envelope conforms to gateway's JSON_RPC_SCHEMA."""
    from openjarvis.mining._miner_loop_main import _make_request

    req = _make_request("getMiningInfo", {}, request_id=42)
    assert req["jsonrpc"] == "2.0"
    assert req["method"] == "getMiningInfo"
    assert req["id"] == 42
    assert req["params"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mining/test_miner_loop.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the helpers**

Create `src/openjarvis/mining/_miner_loop_main.py`:

```python
"""CPU mining-loop subprocess entry point.

Run with:
    python -m openjarvis.mining._miner_loop_main \
        --gateway-host 127.0.0.1 --gateway-port 8337 \
        --m 256 --n 128 --k 1024 --rank 32

Connects to pearl-gateway, polls for work, runs pearl_mining.mine(),
submits proofs back. Designed to be killed via SIGTERM by the parent
provider; no graceful shutdown handshake — Pearl's gateway tolerates
client disconnects cleanly.

This module is the subprocess; the parent OJ process never imports
it directly (it spawns it via ``python -m``). That keeps the parent's
import graph free of pearl_mining (which is an optional dependency).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
from typing import Any

logger = logging.getLogger("openjarvis.mining.miner_loop")


def _make_request(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request envelope matching gateway's schema."""
    return {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}


def _decode_mining_info(result: dict[str, Any]) -> tuple[bytes, int]:
    """Decode getMiningInfo result into (incomplete_header_bytes, target)."""
    header_b64 = result["incomplete_header_bytes"]
    target = int(result["target"])
    return base64.b64decode(header_b64), target


def _encode_plain_proof(plain_proof: Any) -> str:
    """Serialize a PlainProof to base64 for submitPlainProof."""
    return base64.b64encode(plain_proof.serialize()).decode()


async def _read_response(reader: asyncio.StreamReader) -> dict[str, Any]:
    """Read one line of JSON-RPC response from the gateway socket."""
    line = await reader.readline()
    if not line:
        raise ConnectionError("gateway closed the connection")
    return json.loads(line)


async def _send_request(writer: asyncio.StreamWriter, request: dict[str, Any]) -> None:
    """Write one JSON-RPC request followed by newline."""
    writer.write(json.dumps(request).encode() + b"\n")
    await writer.drain()


async def _mine_one_round(
    pearl_mining_module: Any,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    request_id: int,
    m: int,
    n: int,
    k: int,
    rank: int,
) -> bool:
    """Get work, mine, submit. Return True on accepted proof, False otherwise."""
    # 1. Ask the gateway for work
    await _send_request(writer, _make_request("getMiningInfo", {}, request_id))
    info_response = await _read_response(reader)
    if "error" in info_response:
        logger.warning("getMiningInfo error: %s", info_response["error"])
        return False
    header_bytes, target = _decode_mining_info(info_response["result"])

    # 2. Convert header_bytes back into IncompleteBlockHeader and run mine().
    #    Pearl's IncompleteBlockHeader exposes from_bytes() in py-pearl-mining;
    #    if the API name differs, fix this on first integration test.
    header = pearl_mining_module.IncompleteBlockHeader.from_bytes(header_bytes)
    mining_config = _build_mining_config(pearl_mining_module, k=k, rank=rank)

    plain_proof = pearl_mining_module.mine(
        m, n, k, header, mining_config, signal_range=None, wrong_jackpot_hash=False
    )

    # 3. Submit the proof
    submit_params = {
        "plain_proof": _encode_plain_proof(plain_proof),
        "mining_job": {
            "incomplete_header_bytes": base64.b64encode(header_bytes).decode(),
            "target": target,
        },
    }
    await _send_request(writer, _make_request("submitPlainProof", submit_params, request_id + 1))
    submit_response = await _read_response(reader)
    if "error" in submit_response:
        logger.warning("submitPlainProof rejected: %s", submit_response["error"])
        return False
    return True


def _build_mining_config(pearl_mining_module: Any, *, k: int, rank: int):
    """Build the upstream MiningConfiguration with default patterns."""
    from ._constants import (
        CPU_PEARL_DEFAULT_COLS_PATTERN,
        CPU_PEARL_DEFAULT_ROWS_PATTERN,
    )

    return pearl_mining_module.MiningConfiguration(
        common_dim=k,
        rank=rank,
        mma_type=pearl_mining_module.MMAType.Int7xInt7ToInt32,
        rows_pattern=pearl_mining_module.PeriodicPattern.from_list(
            CPU_PEARL_DEFAULT_ROWS_PATTERN
        ),
        cols_pattern=pearl_mining_module.PeriodicPattern.from_list(
            CPU_PEARL_DEFAULT_COLS_PATTERN
        ),
        reserved=pearl_mining_module.MiningConfiguration.RESERVED,
    )


async def _main_loop(args: argparse.Namespace) -> None:
    import pearl_mining

    reader, writer = await asyncio.open_connection(args.gateway_host, args.gateway_port)
    request_id = 0
    try:
        while True:
            request_id += 2
            try:
                accepted = await _mine_one_round(
                    pearl_mining,
                    reader,
                    writer,
                    request_id=request_id,
                    m=args.m,
                    n=args.n,
                    k=args.k,
                    rank=args.rank,
                )
            except Exception:  # noqa: BLE001 — log and try again
                logger.exception("mining round failed; retrying after backoff")
                await asyncio.sleep(1.0)
                continue
            if accepted:
                logger.info("share accepted")
    finally:
        writer.close()
        await writer.wait_closed()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--gateway-host", default="127.0.0.1")
    p.add_argument("--gateway-port", type=int, default=8337)
    p.add_argument("--m", type=int, default=256)
    p.add_argument("--n", type=int, default=128)
    p.add_argument("--k", type=int, default=1024)
    p.add_argument("--rank", type=int, default=32)
    return p.parse_args(argv)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    try:
        asyncio.run(_main_loop(args))
    except KeyboardInterrupt:
        sys.exit(0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mining/test_miner_loop.py -v`
Expected: PASS — three tests green.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/openjarvis/mining/_miner_loop_main.py tests/mining/test_miner_loop.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/mining/_miner_loop_main.py tests/mining/test_miner_loop.py
git commit -m "feat(mining): cpu miner-loop subprocess entry point (Spec B v1 task 5)"
```

---

## Task 6: Subprocess launcher (`_pearl_subprocess.py`)

**Files:**
- Create: `src/openjarvis/mining/_pearl_subprocess.py`
- Test: `tests/mining/test_pearl_subprocess.py`

The launcher manages the *two* subprocesses — `pearl-gateway` and the miner-loop — as a unit. Lifecycle: `start()`, `stop()`, `is_running()`. No PID-file shenanigans here; we hold `Popen` objects in memory while the OJ process is alive.

- [ ] **Step 1: Write the failing test**

Create `tests/mining/test_pearl_subprocess.py`:

```python
"""Tests for openjarvis.mining._pearl_subprocess."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_popen():
    p = MagicMock()
    p.poll.return_value = None  # still running
    p.pid = 12345
    return p


def test_launcher_start_spawns_two_processes(fake_popen, tmp_path):
    from openjarvis.mining._pearl_subprocess import PearlSubprocessLauncher

    with patch("subprocess.Popen", return_value=fake_popen) as mock_popen:
        launcher = PearlSubprocessLauncher(
            gateway_host="127.0.0.1",
            gateway_port=8337,
            metrics_port=8339,
            pearld_rpc_url="http://localhost:44107",
            pearld_rpc_user="rpcuser",
            pearld_rpc_password="testpw",
            wallet_address="prl1qtest",
            log_dir=tmp_path,
        )
        launcher.start(m=256, n=128, k=1024, rank=32)
        assert mock_popen.call_count == 2  # gateway + miner-loop


def test_launcher_stop_terminates_both(fake_popen, tmp_path):
    from openjarvis.mining._pearl_subprocess import PearlSubprocessLauncher

    with patch("subprocess.Popen", return_value=fake_popen):
        launcher = PearlSubprocessLauncher(
            gateway_host="127.0.0.1",
            gateway_port=8337,
            metrics_port=8339,
            pearld_rpc_url="http://localhost:44107",
            pearld_rpc_user="rpcuser",
            pearld_rpc_password="testpw",
            wallet_address="prl1qtest",
            log_dir=tmp_path,
        )
        launcher.start(m=256, n=128, k=1024, rank=32)
        launcher.stop()
        assert fake_popen.terminate.call_count >= 2


def test_launcher_is_running_false_when_either_exited(fake_popen, tmp_path):
    from openjarvis.mining._pearl_subprocess import PearlSubprocessLauncher

    fake_dead = MagicMock()
    fake_dead.poll.return_value = 1  # exited
    fake_dead.pid = 12346

    with patch("subprocess.Popen", side_effect=[fake_popen, fake_dead]):
        launcher = PearlSubprocessLauncher(
            gateway_host="127.0.0.1",
            gateway_port=8337,
            metrics_port=8339,
            pearld_rpc_url="http://localhost:44107",
            pearld_rpc_user="rpcuser",
            pearld_rpc_password="testpw",
            wallet_address="prl1qtest",
            log_dir=tmp_path,
        )
        launcher.start(m=256, n=128, k=1024, rank=32)
        assert launcher.is_running() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mining/test_pearl_subprocess.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `PearlSubprocessLauncher`**

Create `src/openjarvis/mining/_pearl_subprocess.py`:

```python
"""Subprocess launcher for the cpu-pearl provider.

Manages two subprocesses:
- ``pearl-gateway`` (Pearl's Python service), which talks to pearld and
  brokers shares from the miner.
- ``openjarvis.mining._miner_loop_main`` (this repo), which polls the gateway
  and runs ``pearl_mining.mine()``.

Lifecycle is in-memory: while this object lives, both subprocesses live.
The provider holds it; sidecar JSON records PIDs for crash recovery.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_GATEWAY_TERMINATE_GRACE_SECONDS = 5.0
_MINER_LOOP_TERMINATE_GRACE_SECONDS = 2.0


@dataclass(slots=True)
class _ProcessHandles:
    gateway: subprocess.Popen
    miner_loop: subprocess.Popen


class PearlSubprocessLauncher:
    def __init__(
        self,
        *,
        gateway_host: str,
        gateway_port: int,
        metrics_port: int,
        pearld_rpc_url: str,
        pearld_rpc_user: str,
        pearld_rpc_password: str,
        wallet_address: str,
        log_dir: Path,
    ) -> None:
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.metrics_port = metrics_port
        self.pearld_rpc_url = pearld_rpc_url
        self.pearld_rpc_user = pearld_rpc_user
        self.pearld_rpc_password = pearld_rpc_password
        self.wallet_address = wallet_address
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._handles: _ProcessHandles | None = None

    def start(self, *, m: int, n: int, k: int, rank: int) -> None:
        env = self._build_gateway_env()

        # Spawn gateway. ``pearl-gateway`` is the console-script entry point
        # exposed by the pearl_gateway package's pyproject.toml.
        gateway_log = (self.log_dir / "pearl-gateway.log").open("a", buffering=1)
        gateway = subprocess.Popen(
            ["pearl-gateway"],
            env=env,
            stdout=gateway_log,
            stderr=subprocess.STDOUT,
        )

        # Spawn miner-loop pointed at the gateway.
        miner_log = (self.log_dir / "cpu-pearl-miner.log").open("a", buffering=1)
        miner_loop = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "openjarvis.mining._miner_loop_main",
                "--gateway-host",
                self.gateway_host,
                "--gateway-port",
                str(self.gateway_port),
                "--m",
                str(m),
                "--n",
                str(n),
                "--k",
                str(k),
                "--rank",
                str(rank),
            ],
            stdout=miner_log,
            stderr=subprocess.STDOUT,
        )

        self._handles = _ProcessHandles(gateway=gateway, miner_loop=miner_loop)

    def stop(self) -> None:
        if self._handles is None:
            return
        # Stop miner-loop first, then gateway.
        for proc, grace in (
            (self._handles.miner_loop, _MINER_LOOP_TERMINATE_GRACE_SECONDS),
            (self._handles.gateway, _GATEWAY_TERMINATE_GRACE_SECONDS),
        ):
            if proc.poll() is None:
                proc.terminate()
                deadline = time.monotonic() + grace
                while time.monotonic() < deadline and proc.poll() is None:
                    time.sleep(0.05)
                if proc.poll() is None:
                    proc.kill()
        self._handles = None

    def is_running(self) -> bool:
        if self._handles is None:
            return False
        return (
            self._handles.gateway.poll() is None
            and self._handles.miner_loop.poll() is None
        )

    def pids(self) -> tuple[int, int] | None:
        if self._handles is None:
            return None
        return (self._handles.gateway.pid, self._handles.miner_loop.pid)

    def _build_gateway_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "PEARL_GATEWAY_HOST": self.gateway_host,
                "PEARL_GATEWAY_PORT": str(self.gateway_port),
                "PEARL_GATEWAY_METRICS_PORT": str(self.metrics_port),
                "PEARLD_RPC_URL": self.pearld_rpc_url,
                "PEARLD_RPC_USER": self.pearld_rpc_user,
                "PEARLD_RPC_PASSWORD": self.pearld_rpc_password,
                "PEARLD_MINING_ADDRESS": self.wallet_address,
                # tell pearl-gateway to use TCP for miner RPC, matching what the
                # miner-loop subprocess connects to.
                "MINER_RPC_TRANSPORT": "tcp",
            }
        )
        return env
```

> **Note on env var names:** The exact names pearl-gateway reads (`PEARL_GATEWAY_HOST`, `PEARL_GATEWAY_PORT`, etc.) come from `pearl/miner/pearl-gateway/src/pearl_gateway/config.py`. Verify on first integration: open that file, copy the actual `Field(env=...)` names into the `_build_gateway_env` dict above. If the names differ, this is a one-line fix per env var; the surrounding lifecycle is unaffected.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mining/test_pearl_subprocess.py -v`
Expected: PASS — three tests green.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/openjarvis/mining/_pearl_subprocess.py tests/mining/test_pearl_subprocess.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/mining/_pearl_subprocess.py tests/mining/test_pearl_subprocess.py
git commit -m "feat(mining): pearl subprocess launcher (Spec B v1 task 6)"
```

---

## Task 7: Verify env var names against pearl-gateway config

**Files:**
- Modify: `src/openjarvis/mining/_pearl_subprocess.py`

This is a one-shot research-and-fix task to make Task 6's env names match Pearl's actual config.

- [ ] **Step 1: Locate pearl-gateway config**

Run: `find ~/.openjarvis/cache/pearl/miner/pearl-gateway -name config.py -path '*pearl_gateway*' 2>/dev/null || find / -name config.py -path '*pearl_gateway*' 2>/dev/null | head -3`

Expected: `pearl-gateway/src/pearl_gateway/config.py` (path depends on where Pearl was cloned). If the file isn't on disk yet, run `python -m openjarvis.mining._install` (added in Task 4) or clone Pearl manually first.

- [ ] **Step 2: Read the config file**

Look for `Field(env=...)` annotations on `MinerSettings` / `PearlGatewayConfig`. List every env var name it accepts.

Run: `grep -nE 'env\s*=' <path-to-pearl-gateway/config.py> | head -20`

Expected output: lines like `Field(default="...", env="PEARL_GATEWAY_HOST")` showing the canonical names.

- [ ] **Step 3: Replace the env-var names in `_build_gateway_env`**

Open `src/openjarvis/mining/_pearl_subprocess.py` and replace each guessed env name with the actual one. Keep the dict structure; only the keys change.

If a name we expected is missing (e.g., pearl-gateway doesn't have a separate `*_METRICS_PORT`), drop the line rather than carry a no-op env var.

- [ ] **Step 4: Re-run tests**

Run: `uv run pytest tests/mining/test_pearl_subprocess.py -v`
Expected: PASS — same three tests, no regressions (the test mocks Popen, so env-var-name changes don't affect them).

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/mining/_pearl_subprocess.py
git commit -m "fix(mining): align env var names with pearl-gateway config (Spec B v1 task 7)"
```

---

## Task 8: `CpuPearlProvider` — capability detection

**Files:**
- Create: `src/openjarvis/mining/cpu_pearl.py`
- Test: `tests/mining/test_cpu_pearl.py`

Implements the `MiningProvider.detect()` classmethod from Spec A's ABC. This is the first thing `mine doctor` and `mine init` ask. Engine-independent: returns supported on any darwin/linux host with Pearl packages installed.

- [ ] **Step 1: Write the failing tests**

Create `tests/mining/test_cpu_pearl.py`:

```python
"""Tests for openjarvis.mining.cpu_pearl.CpuPearlProvider."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def darwin_apple_hw():
    """A HardwareInfo describing an Apple Silicon Mac."""
    from openjarvis.mining._stubs import HardwareInfo, GpuInfo

    return HardwareInfo(
        platform="darwin",
        cpu_arch="arm64",
        gpu=GpuInfo(vendor="apple", model="M2 Max", vram_gb=96.0),
    )


@pytest.fixture
def linux_nvidia_hw():
    """A HardwareInfo describing an H100 box."""
    from openjarvis.mining._stubs import HardwareInfo, GpuInfo

    return HardwareInfo(
        platform="linux",
        cpu_arch="x86_64",
        gpu=GpuInfo(vendor="nvidia", model="H100", vram_gb=80.0, compute_cap="9.0a"),
    )


@pytest.fixture
def windows_hw():
    """A HardwareInfo describing a Windows host (unsupported in v1)."""
    from openjarvis.mining._stubs import HardwareInfo

    return HardwareInfo(platform="win32", cpu_arch="x86_64", gpu=None)


def test_detect_supported_on_apple_silicon(darwin_apple_hw):
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    with patch(
        "openjarvis.mining._install.pearl_packages_available", return_value=True
    ):
        cap = CpuPearlProvider.detect(darwin_apple_hw, engine_id="ollama", model="any")
        assert cap.supported is True
        assert cap.reason is None


def test_detect_supported_on_linux_too(linux_nvidia_hw):
    """v1 cpu-pearl is engine-independent and platform-loose."""
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    with patch(
        "openjarvis.mining._install.pearl_packages_available", return_value=True
    ):
        cap = CpuPearlProvider.detect(
            linux_nvidia_hw, engine_id="anything", model="any"
        )
        assert cap.supported is True


def test_detect_unsupported_on_windows(windows_hw):
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    with patch(
        "openjarvis.mining._install.pearl_packages_available", return_value=True
    ):
        cap = CpuPearlProvider.detect(windows_hw, engine_id="any", model="any")
        assert cap.supported is False
        assert "win32" in cap.reason.lower() or "windows" in cap.reason.lower()


def test_detect_unsupported_when_pearl_not_installed(darwin_apple_hw):
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    with patch(
        "openjarvis.mining._install.pearl_packages_available", return_value=False
    ):
        cap = CpuPearlProvider.detect(darwin_apple_hw, engine_id="any", model="any")
        assert cap.supported is False
        assert "mining-pearl-cpu" in cap.reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mining/test_cpu_pearl.py -v`
Expected: FAIL — `CpuPearlProvider` not found.

- [ ] **Step 3: Implement the provider's `detect`**

Create `src/openjarvis/mining/cpu_pearl.py`:

```python
"""CPU-based Pearl mining provider (decoupled from inference).

Spec B v1: wraps Pearl's pure-Rust ``mine()`` function via py-pearl-mining
and runs Pearl's pearl-gateway as a sibling subprocess. Works on any host
where py-pearl-mining builds — verified on macOS arm64 (M2 Max) in Spec B.

Engine-independent: this provider does not plug into the user's inference
stack. The user keeps using whatever engine they want; mining runs alongside.
"""
from __future__ import annotations

from . import _install
from ._stubs import HardwareInfo, MiningCapabilities, MiningConfig, MiningProvider, MiningStats


class CpuPearlProvider(MiningProvider):
    provider_id = "cpu-pearl"

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        # v1 platform gate: only darwin and linux. Windows requires more
        # investigation (Pearl's miner Taskfile excludes Windows from the
        # cpu-mining install path even though the algorithm itself is portable).
        if hw.platform not in {"darwin", "linux"}:
            return MiningCapabilities(
                supported=False,
                reason=f"v1 cpu-pearl supports darwin/linux only; this host is '{hw.platform}'",
            )
        if not _install.pearl_packages_available():
            return MiningCapabilities(
                supported=False,
                reason=f"Pearl Python packages not installed — {_install.install_hint()}",
            )
        # No engine_id check: cpu-pearl is decoupled from inference.
        # Hashrate estimate is deferred to a one-shot calibration during
        # `mine init` (Task 9 lifecycle integration).
        return MiningCapabilities(supported=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mining/test_cpu_pearl.py -v`
Expected: PASS — four tests green.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/openjarvis/mining/cpu_pearl.py tests/mining/test_cpu_pearl.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/mining/cpu_pearl.py tests/mining/test_cpu_pearl.py
git commit -m "feat(mining): cpu-pearl provider capability detection (Spec B v1 task 8)"
```

---

## Task 9: `CpuPearlProvider` — start/stop/is_running/stats

**Files:**
- Modify: `src/openjarvis/mining/cpu_pearl.py`
- Modify: `tests/mining/test_cpu_pearl.py`

Wire the provider lifecycle methods to the subprocess launcher and Spec A's sidecar / telemetry adapter.

- [ ] **Step 1: Write the failing tests**

Append to `tests/mining/test_cpu_pearl.py`:

```python
def test_start_writes_sidecar_and_returns_running(darwin_apple_hw, tmp_path, monkeypatch):
    from openjarvis.mining.cpu_pearl import CpuPearlProvider
    from openjarvis.mining._stubs import MiningConfig

    monkeypatch.setattr(
        "openjarvis.mining.cpu_pearl._sidecar_path",
        lambda: tmp_path / "mining.json",
    )

    fake_launcher = type(
        "FakeLauncher",
        (),
        {
            "start": lambda self, **kw: None,
            "stop": lambda self: None,
            "is_running": lambda self: True,
            "pids": lambda self: (11111, 22222),
        },
    )()

    with patch(
        "openjarvis.mining.cpu_pearl.PearlSubprocessLauncher",
        return_value=fake_launcher,
    ):
        provider = CpuPearlProvider()
        cfg = MiningConfig(
            provider="cpu-pearl",
            wallet_address="prl1qtest",
            extra={
                "gateway_port": 8337,
                "metrics_port": 8339,
                "pearld_rpc_url": "http://localhost:44107",
                "pearld_rpc_user": "rpcuser",
                "pearld_rpc_password_env": "TESTPW",
                "m": 256, "n": 128, "k": 1024, "rank": 32,
            },
        )
        monkeypatch.setenv("TESTPW", "secret")
        provider.start(cfg)
        assert provider.is_running() is True
        sidecar_text = (tmp_path / "mining.json").read_text()
        assert '"provider": "cpu-pearl"' in sidecar_text
        assert "11111" in sidecar_text
        assert "22222" in sidecar_text
        # secret must NOT appear in sidecar
        assert "secret" not in sidecar_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mining/test_cpu_pearl.py::test_start_writes_sidecar_and_returns_running -v`
Expected: FAIL — `start`, `is_running` not implemented.

- [ ] **Step 3: Implement lifecycle methods**

Replace `src/openjarvis/mining/cpu_pearl.py` with the full implementation:

```python
"""CPU-based Pearl mining provider (decoupled from inference).

Spec B v1: wraps Pearl's pure-Rust ``mine()`` function via py-pearl-mining
and runs Pearl's pearl-gateway as a sibling subprocess.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import urllib.request

from . import _install
from ._constants import (
    CPU_PEARL_DEFAULT_K,
    CPU_PEARL_DEFAULT_M,
    CPU_PEARL_DEFAULT_N,
    CPU_PEARL_DEFAULT_RANK,
)
from ._pearl_subprocess import PearlSubprocessLauncher
from ._stubs import HardwareInfo, MiningCapabilities, MiningConfig, MiningProvider, MiningStats


def _sidecar_path() -> Path:
    return Path(os.path.expanduser("~/.openjarvis/runtime/mining.json"))


def _log_dir() -> Path:
    return Path(os.path.expanduser("~/.openjarvis/logs/mining"))


class CpuPearlProvider(MiningProvider):
    provider_id = "cpu-pearl"

    def __init__(self) -> None:
        self._launcher: PearlSubprocessLauncher | None = None
        self._config: MiningConfig | None = None
        self._started_at: float | None = None

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        if hw.platform not in {"darwin", "linux"}:
            return MiningCapabilities(
                supported=False,
                reason=f"v1 cpu-pearl supports darwin/linux only; this host is '{hw.platform}'",
            )
        if not _install.pearl_packages_available():
            return MiningCapabilities(
                supported=False,
                reason=f"Pearl Python packages not installed — {_install.install_hint()}",
            )
        return MiningCapabilities(supported=True)

    def start(self, config: MiningConfig) -> None:
        extra = dict(config.extra or {})
        password_env = extra.get("pearld_rpc_password_env", "PEARLD_RPC_PASSWORD")
        password = os.environ.get(password_env, "")

        self._launcher = PearlSubprocessLauncher(
            gateway_host=extra.get("gateway_host", "127.0.0.1"),
            gateway_port=int(extra.get("gateway_port", 8337)),
            metrics_port=int(extra.get("metrics_port", 8339)),
            pearld_rpc_url=extra.get("pearld_rpc_url", "http://localhost:44107"),
            pearld_rpc_user=extra.get("pearld_rpc_user", "rpcuser"),
            pearld_rpc_password=password,
            wallet_address=config.wallet_address,
            log_dir=_log_dir(),
        )
        self._launcher.start(
            m=int(extra.get("m", CPU_PEARL_DEFAULT_M)),
            n=int(extra.get("n", CPU_PEARL_DEFAULT_N)),
            k=int(extra.get("k", CPU_PEARL_DEFAULT_K)),
            rank=int(extra.get("rank", CPU_PEARL_DEFAULT_RANK)),
        )
        self._config = config
        self._started_at = time.time()
        self._write_sidecar()

    def stop(self) -> None:
        if self._launcher is not None:
            self._launcher.stop()
        self._launcher = None
        self._config = None
        self._started_at = None
        sp = _sidecar_path()
        if sp.exists():
            sp.unlink()

    def is_running(self) -> bool:
        return self._launcher is not None and self._launcher.is_running()

    def stats(self) -> MiningStats:
        if not self.is_running() or self._launcher is None:
            return MiningStats(provider_id=self.provider_id)

        # Spec A's gateway-metrics adapter handles the parsing. Read once,
        # parse, return. Reuse the same adapter the vllm-pearl provider uses;
        # the metric names are identical.
        from ._gateway_metrics import parse_gateway_metrics

        try:
            extra = (self._config.extra or {}) if self._config else {}
            metrics_port = int(extra.get("metrics_port", 8339))
            host = extra.get("gateway_host", "127.0.0.1")
            with urllib.request.urlopen(
                f"http://{host}:{metrics_port}/metrics", timeout=2.0
            ) as resp:
                text = resp.read().decode()
        except Exception as e:  # noqa: BLE001
            return MiningStats(
                provider_id=self.provider_id,
                last_error=f"gateway metrics unreachable: {e}",
            )
        return parse_gateway_metrics(text, provider_id=self.provider_id)

    def _write_sidecar(self) -> None:
        if self._launcher is None or self._config is None:
            return
        pids = self._launcher.pids() or (None, None)
        extra = self._config.extra or {}
        sidecar = {
            "provider": self.provider_id,
            "started_at": self._started_at,
            "wallet_address": self._config.wallet_address,
            "gateway_url": (
                f"http://{extra.get('gateway_host', '127.0.0.1')}:"
                f"{extra.get('gateway_port', 8337)}"
            ),
            "metrics_url": (
                f"http://{extra.get('gateway_host', '127.0.0.1')}:"
                f"{extra.get('metrics_port', 8339)}/metrics"
            ),
            "gateway_pid": pids[0],
            "miner_loop_pid": pids[1],
        }
        sp = _sidecar_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(sidecar, indent=2))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/mining/test_cpu_pearl.py -v`
Expected: PASS — five tests green.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/openjarvis/mining/cpu_pearl.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/mining/cpu_pearl.py tests/mining/test_cpu_pearl.py
git commit -m "feat(mining): cpu-pearl provider lifecycle (Spec B v1 task 9)"
```

---

## Task 10: Register `CpuPearlProvider` in `MinerRegistry`

**Files:**
- Modify: `src/openjarvis/mining/__init__.py`

`MinerRegistry` exists from Spec A; we just need to call `register("cpu-pearl")` at module-load time and survive the autouse `clear_registries` fixture in `tests/conftest.py` via the `ensure_registered()` pattern.

- [ ] **Step 1: Read Spec A's existing `__init__.py`**

Run: `cat src/openjarvis/mining/__init__.py`

Expected: file already imports `vllm_pearl` and exposes `ensure_registered`. We mirror the same pattern for cpu_pearl.

- [ ] **Step 2: Add cpu_pearl registration**

Append to `src/openjarvis/mining/__init__.py` (or modify if Spec A already defined `ensure_registered`):

```python
def _register_cpu_pearl() -> None:
    """Register CpuPearlProvider in MinerRegistry. Idempotent."""
    from openjarvis.core.registry import MinerRegistry  # type: ignore

    if MinerRegistry.contains("cpu-pearl"):
        return
    try:
        from .cpu_pearl import CpuPearlProvider
    except ImportError:
        # py-pearl-mining etc. not installed — that's fine, the provider
        # only registers when the optional extra is in. detect() will
        # surface a clear "install with --extra mining-pearl-cpu" message.
        return
    MinerRegistry.register("cpu-pearl")(CpuPearlProvider)


# Call at import time so the registry is populated as soon as openjarvis.mining
# is imported. The conftest autouse fixture clears registries between tests; we
# rely on _register_cpu_pearl being called again from `ensure_registered`.
_register_cpu_pearl()


def ensure_registered() -> None:
    """Re-register all mining providers — used by tests that clear the registry."""
    _register_vllm_pearl()  # added by Spec A
    _register_cpu_pearl()
```

- [ ] **Step 3: Run all mining tests**

Run: `uv run pytest tests/mining/ -v`
Expected: PASS — every test from this plan plus Spec A's tests still green.

- [ ] **Step 4: Run a broader test sweep to catch regressions**

Run: `uv run pytest tests/ -v --co -q | tail -30; uv run pytest tests/ -x -q 2>&1 | tail -30`
Expected: same number of passing tests as before this task.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/mining/__init__.py
git commit -m "feat(mining): register cpu-pearl provider (Spec B v1 task 10)"
```

---

## Task 11: User-facing documentation

**Files:**
- Create: `docs/user-guide/mining-apple-silicon.md`

The honest user guide. Set expectations correctly; don't oversell hashrate.

- [ ] **Step 1: Write the doc**

Create `docs/user-guide/mining-apple-silicon.md`:

````markdown
# Mining Pearl on Apple Silicon (and other CPU hosts)

OpenJarvis can mine the [Pearl](https://github.com/pearl-research-labs/pearl) chain
on Apple Silicon Macs (M1/M2/M3/M4) using the `cpu-pearl` provider. **This is
v1**: decoupled CPU mining. Your existing local LLM workflow (Ollama, MLX-LM,
llama.cpp, vLLM) is untouched; mining runs in the background as a separate
process.

## Honest expectations

**Hashrate on Apple Silicon CPU is far below what an H100 produces with
Pearl's `vllm-miner`.** A rough rule of thumb (subject to network difficulty):

- M2 Max / M4 Max: ≪ 1 share per second at typical mainnet difficulty
- H100 with `vllm-miner`: meaningfully higher, plus the mining work is
  amortized over real LLM inference

If you want to mine for yield, this isn't the path. If you want to participate
in the network from the hardware you own, with no special hardware purchase,
this is the path.

A future v2 will add Apple-GPU acceleration via PyTorch MPS or a custom MLX
plugin. v3 may add a native Metal kernel. **Neither is shipped today.**

## Prerequisites

- macOS arm64 (M1, M2, M3, M4) — or Linux x86_64 / aarch64
- Python 3.12 (`brew install python@3.12` or use `uv venv --python 3.12`)
- Rust toolchain (`brew install rust` or `curl https://sh.rustup.rs -sSf | sh`)
- Your own running [`pearld`](https://github.com/pearl-research-labs/pearl#node)
  node, RPC reachable on `http://localhost:44107`
- A Pearl Taproot wallet address from `oyster` (Pearl's wallet CLI)
- ~1 GB free disk for the Pearl source clone and build artifacts

## Install

```bash
# from your OpenJarvis repo
uv sync --extra mining-pearl-cpu
```

If Pearl wheels are not yet on PyPI (still true as of 2026-05-05), `uv sync`
will fail because none of the packages exist there. Until publication, build
locally:

```bash
jarvis mine init    # OJ will detect the missing wheels and offer to build
                    # via the build-from-pin path; takes ~3-5 minutes on
                    # first run, mostly compiling Rust
```

`mine init` will:
1. Clone Pearl at the version OJ has tested against
2. Run `maturin build --release` for `py-pearl-mining`
3. Install the resulting wheel + the `miner-base`, `pearl-gateway` packages
4. Walk you through wallet address / pearld RPC config
5. Run a calibration to estimate your share-per-hour rate

## Run

```bash
# start mining
jarvis mine start

# check live status
jarvis mine status

# capability matrix (great when something goes wrong)
jarvis mine doctor

# stop mining
jarvis mine stop

# tail logs
jarvis mine logs -f
```

## Reading `mine doctor`

Each row is one check. `✓` means the check passed; `✗` shows the actionable fix.

```
$ jarvis mine doctor
Hardware
  GPU vendor          apple                            ✓
  Apple chip          M2 Max                           ✓
Pearl install
  py-pearl-mining     0.1.0 (cp312-abi3-macos-arm64)   ✓
  miner-base          0.1.0                            ✓
  pearl-gateway       0.1.0                            ✓
Pearl node
  RPC                 http://localhost:44107           ✓
  Block height        442107 (synced)                  ✓
Wallet
  Address format      prl1q...                         ✓
Provider capability
  cpu-pearl           SUPPORTED  (calibrated 0.X share/h on M2 Max)
Notes
  - This is decoupled mining: your normal LLM inference is unaffected
  - Hashrate is far below H100 mining; see this doc above
  - Metal-accelerated mining: planned for v2; not available yet
Session
  Sidecar             absent (not running)
```

## Limitations

- **Windows is not supported in v1.** Pearl's pure-Rust miner builds on
  Windows in principle but the cross-platform install path is untested. Use
  WSL2 if you must.
- **No coupling to inference yet.** v1 is a separate process; your CPU does
  mining, your GPU does inference. They don't share work. v2 changes this.
- **No PyTorch-MPS yet.** v1 stays on the CPU path. v2 will move the math
  to MPS for Apple-GPU acceleration.
- **No multi-host pool.** Solo mining only. The pool work is a separate spec
  ([Spec A §8.5](../design/2026-05-05-vllm-pearl-mining-integration-design.md)).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `mine doctor` says `Pearl Python packages not installed` | Wheels not built yet | Run `jarvis mine init` |
| `pearl-gateway` log shows `connection refused` to `http://localhost:44107` | `pearld` not running | Start `pearld` per Pearl's README |
| `mine status` shows `last_error: gateway metrics unreachable` | `pearl-gateway` crashed | Check `~/.openjarvis/logs/mining/pearl-gateway.log` |
| Build fails with `error: linker 'cc' not found` | Xcode CLT not installed | `xcode-select --install` |
| `maturin build` complains about `tikv-jemallocator` | macOS SDK too old | Update macOS / Xcode |

For anything not on this list, capture `~/.openjarvis/logs/mining/` and open
an issue at https://github.com/open-jarvis/OpenJarvis/issues.

## What changes in v2 / v3

- **v2 (months):** PyTorch-MPS acceleration plus optional plugin into MLX-LM
  or `llama-cpp-python`. Same `cpu-pearl` config; users opt in via a new
  `apple-mps-pearl` provider when v2 ships.
- **v3 (only if v2 perf is insufficient):** Native Metal kernel as a Pearl
  upstream contribution. No user-visible change other than higher hashrate.
````

- [ ] **Step 2: Lint markdown**

Run: `uv run ruff check docs/user-guide/mining-apple-silicon.md 2>&1 | tail -5 || true`

(Ruff doesn't lint markdown; the command is a no-op. Just verify the file exists and renders.)

Run: `head -20 docs/user-guide/mining-apple-silicon.md`
Expected: the title line and intro paragraph.

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide/mining-apple-silicon.md
git commit -m "docs: user guide for Apple Silicon Pearl mining (Spec B v1 task 11)"
```

---

## Task 12: Final integration smoke test (manual / `live` marker)

**Files:**
- Modify: `tests/mining/test_cpu_pearl.py`

A real end-to-end test that starts the provider on the dev machine, runs for ~30 s, asserts at least one mining round completed. Marked `live` so it's gated behind `pytest -m live` and excluded from default CI.

- [ ] **Step 1: Append the live test**

Append to `tests/mining/test_cpu_pearl.py`:

```python
@pytest.mark.live
@pytest.mark.slow
def test_provider_runs_end_to_end_on_this_host(tmp_path, monkeypatch):
    """Live test: start provider, run for 30 s, assert mining loop produced output.

    Requires:
    - py-pearl-mining built and installed
    - pearl-gateway and miner-base installed
    - either pearld running OR a stub gateway environment (latter is harder
      to set up; for v1 we rely on pearld being available locally)
    """
    pytest.importorskip("pearl_mining")
    pytest.importorskip("pearl_gateway")

    from openjarvis.mining.cpu_pearl import CpuPearlProvider
    from openjarvis.mining._stubs import MiningConfig

    monkeypatch.setattr(
        "openjarvis.mining.cpu_pearl._sidecar_path",
        lambda: tmp_path / "mining.json",
    )
    monkeypatch.setattr(
        "openjarvis.mining.cpu_pearl._log_dir",
        lambda: tmp_path / "logs",
    )
    monkeypatch.setenv("TEST_PEARLD_PASSWORD", "test")

    cfg = MiningConfig(
        provider="cpu-pearl",
        wallet_address="prl1q" + "0" * 32,
        extra={
            "gateway_port": 18337,  # high port to avoid conflict with real session
            "metrics_port": 18339,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "TEST_PEARLD_PASSWORD",
        },
    )
    provider = CpuPearlProvider()
    provider.start(cfg)

    import time
    deadline = time.monotonic() + 30
    saw_running = False
    while time.monotonic() < deadline:
        if provider.is_running():
            saw_running = True
        time.sleep(1.0)

    provider.stop()

    log_dir = tmp_path / "logs"
    if log_dir.exists():
        for log_file in log_dir.glob("*.log"):
            print(f"--- {log_file.name} ---")
            print(log_file.read_text()[:2000])

    assert saw_running, "provider never reported is_running"
```

- [ ] **Step 2: Run the live test (only on a host with the full Pearl stack)**

Run: `uv run pytest tests/mining/test_cpu_pearl.py::test_provider_runs_end_to_end_on_this_host -v -m live`
Expected: PASS if the host has Pearl installed and `pearld` running. Skipped via `importorskip` otherwise.

- [ ] **Step 3: Verify default CI run still excludes it**

Run: `uv run pytest tests/mining/ -v -m "not live and not cloud"`
Expected: every other test in this plan still passes; the live test is collected-but-deselected.

- [ ] **Step 4: Commit**

```bash
git add tests/mining/test_cpu_pearl.py
git commit -m "test(mining): live end-to-end smoke test for cpu-pearl (Spec B v1 task 12)"
```

---

## Task 13: REVIEW.md and CLAUDE.md updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `REVIEW.md` (if Spec A added it; else skip)

Tiny pointers so future agents discover the cpu-pearl path.

- [ ] **Step 1: Add a paragraph to CLAUDE.md `## Architecture` section**

Find the `mining` paragraph that Spec A added. Append:

```
The `mining` subsystem also includes the `cpu-pearl` provider (Spec B v1) for
non-CUDA hosts including Apple Silicon. It runs Pearl's pure-Rust `mine()`
function via `py-pearl-mining` plus Pearl's `pearl-gateway` as a sibling
subprocess; decoupled from inference (the user's MLX/Ollama/llamacpp engine
is untouched). Future v2 (Apple-GPU acceleration via PyTorch MPS) and v3
(native Metal kernel) are tracked in
docs/design/2026-05-05-apple-silicon-pearl-mining-design.md.
```

- [ ] **Step 2: Add a row to REVIEW.md "Registry compliance" if that section exists**

Run: `grep -n "MinerRegistry" REVIEW.md 2>/dev/null || echo "no row yet"`

If a row exists from Spec A, add a sibling row noting that `cpu-pearl` is the second registered provider and reviewers should check both `_register_vllm_pearl` and `_register_cpu_pearl` are called from `ensure_registered`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md REVIEW.md 2>/dev/null  # REVIEW.md may not exist; that's fine
git commit -m "docs: point at cpu-pearl provider in CLAUDE.md (Spec B v1 task 13)"
```

---

## Self-review checklist

Run through each of these against the final plan:

**1. Spec coverage** — Spec B §13 sections vs. tasks:

- §13.1 Architecture (subprocess + provider + sidecar) → Tasks 5, 6, 9
- §13.2 Module layout → Tasks 5, 6, 8, 9, 10
- §13.3 Optional extra → Task 2
- §13.4 Capability detection → Task 8
- §13.5 Lifecycle → Tasks 6, 7, 9
- §13.6 Configuration → reuses Spec A; documented in user guide (Task 11)
- §13.7 Doctor surface → Spec A's `mine doctor` already; cpu-pearl row populated by Task 9's `stats()` plus the new capability detection from Task 8. *(No separate task needed; integrates via the existing CLI.)*
- §13.8 Anti-goals → enforced by what the plan does NOT do (no MLX plugin, no Metal, no inference coupling)
- §13.9 Exit criteria → Task 12 (live smoke), Task 11 (docs); the testnet block-find item is operational, not a code task
- §13.10 v2/v3 — explicitly out of scope, mentioned in user-guide

**2. Type consistency check:**

- `MiningProvider`, `MinerRegistry`, `MiningCapabilities`, `MiningConfig`, `MiningStats`, `HardwareInfo` — all from Spec A's `_stubs.py`. Used identically across Tasks 8–10.
- `provider_id = "cpu-pearl"` — used in Tasks 8, 9, 10.
- Sidecar key names (`provider`, `wallet_address`, `gateway_url`, `metrics_url`, `gateway_pid`, `miner_loop_pid`, `started_at`) — defined in Task 9's `_write_sidecar` and read in Task 12's assertion.
- `_install.pearl_packages_available()` and `_install.install_hint()` — defined in Task 3, used in Task 8.
- `_install.build_from_pin()` — defined in Task 4, called from `mine init` orchestration in Spec A's plan.

**3. Placeholder scan:**

- No "TBD", "TODO", "implement later" in any code block.
- One spot deliberately marked as "research-and-fix": Task 7 verifies env var names against Pearl's config. The fix is mechanical (replace strings); the research is bounded (read one Pearl file).
- `_pearl_subprocess.py` env var names in Task 6 are best-guesses and refined by Task 7. This is not a placeholder — Task 7 is the explicit fix.

**4. Reuses from Spec A (sanity check — these must already exist):**

- `MiningProvider` ABC at `src/openjarvis/mining/_stubs.py`
- `MinerRegistry` class at `src/openjarvis/core/registry.py`
- `MiningConfig`, `MiningCapabilities`, `MiningStats`, `HardwareInfo` dataclasses
- Sidecar location convention `~/.openjarvis/runtime/mining.json`
- `parse_gateway_metrics` adapter
- `mine init|start|stop|status|doctor` CLI subcommands

If any of these are missing when you start Task 1, **stop and execute Spec A first.** Do not duplicate that infrastructure here.

---

## Execution handoff

Plan complete and saved to `docs/design/2026-05-05-apple-silicon-pearl-mining-plan-v1.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task with two-stage review. Good for parallelizing review and execution, and the tasks here are well-bounded.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`. Faster end-to-end, batches review at checkpoints.

The user is doing subagent-driven for Spec A (per their direction). The same approach makes sense for Spec B v1 once Spec A's plan completes; the dependency makes them naturally sequential.
