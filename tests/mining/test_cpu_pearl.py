"""Tests for openjarvis.mining.cpu_pearl.CpuPearlProvider."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

_AVAIL = "openjarvis.mining._install.pearl_packages_available"


@pytest.fixture
def darwin_apple_hw():
    """A HardwareInfo describing an Apple Silicon Mac."""
    from openjarvis.core.config import GpuInfo, HardwareInfo

    return HardwareInfo(
        platform="darwin",
        cpu_brand="Apple M2 Max",
        cpu_count=12,
        ram_gb=96.0,
        gpu=GpuInfo(vendor="apple", name="M2 Max", vram_gb=96.0, count=1),
    )


@pytest.fixture
def linux_nvidia_hw():
    """A HardwareInfo describing an H100 box."""
    from openjarvis.core.config import GpuInfo, HardwareInfo

    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Xeon",
        cpu_count=64,
        ram_gb=512.0,
        gpu=GpuInfo(
            vendor="nvidia",
            name="H100",
            vram_gb=80.0,
            compute_capability="9.0a",
            count=1,
        ),
    )


@pytest.fixture
def windows_hw():
    """A HardwareInfo describing a Windows host (unsupported in v1)."""
    from openjarvis.core.config import HardwareInfo

    return HardwareInfo(
        platform="win32", cpu_brand="x86_64", cpu_count=16, ram_gb=64.0, gpu=None
    )


def test_detect_supported_on_apple_silicon_when_packages_present(darwin_apple_hw):
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    with patch(_AVAIL, return_value=True):
        cap = CpuPearlProvider.detect(darwin_apple_hw, engine_id="ollama", model="any")
    assert cap.supported is True
    assert cap.reason is None


def test_detect_supported_on_linux_too(linux_nvidia_hw):
    """v1 cpu-pearl is engine-independent and works on linux too."""
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    with patch(_AVAIL, return_value=True):
        cap = CpuPearlProvider.detect(
            linux_nvidia_hw, engine_id="anything", model="any"
        )
    assert cap.supported is True


def test_detect_unsupported_on_windows(windows_hw):
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    with patch(_AVAIL, return_value=True):
        cap = CpuPearlProvider.detect(windows_hw, engine_id="any", model="any")
    assert cap.supported is False
    assert "win32" in cap.reason.lower() or "windows" in cap.reason.lower()


def test_detect_unsupported_when_pearl_not_installed(darwin_apple_hw):
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    with patch(_AVAIL, return_value=False):
        cap = CpuPearlProvider.detect(darwin_apple_hw, engine_id="any", model="any")
    assert cap.supported is False
    assert "mining-pearl-cpu" in cap.reason


def test_detect_engine_independent(darwin_apple_hw):
    """v1 detect() does NOT inspect engine_id — supported regardless of engine."""
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    with patch(_AVAIL, return_value=True):
        for engine in ("ollama", "llamacpp", "vllm", "mlx", "anthropic-cloud", ""):
            cap = CpuPearlProvider.detect(
                darwin_apple_hw, engine_id=engine, model="any"
            )
            assert cap.supported is True, f"engine_id={engine!r} should be supported"


# ---------------------------------------------------------------------------
# Task 9: lifecycle tests
# ---------------------------------------------------------------------------


@pytest.fixture
def cpu_pearl_config():
    """A minimal MiningConfig for cpu-pearl."""
    from openjarvis.mining._stubs import MiningConfig, SoloTarget

    return MiningConfig(
        provider="cpu-pearl",
        wallet_address="prl1qtest",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        fee_bps=0,
        fee_payout_address=None,
        extra={
            "gateway_host": "127.0.0.1",
            "gateway_port": 18337,
            "metrics_port": 19109,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "TEST_PEARLD_PASSWORD",
            "m": 256,
            "n": 128,
            "k": 1024,
            "rank": 32,
        },
    )


def test_start_writes_sidecar_and_is_running(cpu_pearl_config, tmp_path, monkeypatch):
    """After start(), is_running() returns True and sidecar JSON is on disk."""
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    sidecar = tmp_path / "mining.json"
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("openjarvis.mining.cpu_pearl._sidecar_path", lambda: sidecar)
    monkeypatch.setattr("openjarvis.mining.cpu_pearl._log_dir", lambda: log_dir)
    monkeypatch.setenv("TEST_PEARLD_PASSWORD", "secret")

    fake_launcher = MagicMock()
    fake_launcher.is_running.return_value = True
    fake_launcher.pids.return_value = (11111, 22222)

    _target = "openjarvis.mining.cpu_pearl.PearlSubprocessLauncher"
    with patch(_target, return_value=fake_launcher):
        provider = CpuPearlProvider()
        asyncio.run(provider.start(cpu_pearl_config))
        assert provider.is_running() is True

    assert sidecar.exists()
    payload = json.loads(sidecar.read_text())
    assert payload["provider"] == "cpu-pearl"
    assert payload["wallet_address"] == "prl1qtest"
    assert payload["gateway_pid"] == 11111
    assert payload["miner_loop_pid"] == 22222
    # Secret must NOT be in sidecar
    assert "secret" not in sidecar.read_text()


def test_stop_terminates_and_removes_sidecar(cpu_pearl_config, tmp_path, monkeypatch):
    """After stop(), is_running() returns False, sidecar is removed."""
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    sidecar = tmp_path / "mining.json"
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("openjarvis.mining.cpu_pearl._sidecar_path", lambda: sidecar)
    monkeypatch.setattr("openjarvis.mining.cpu_pearl._log_dir", lambda: log_dir)
    monkeypatch.setenv("TEST_PEARLD_PASSWORD", "secret")

    fake_launcher = MagicMock()
    fake_launcher.is_running.side_effect = [True, False]
    fake_launcher.pids.return_value = (11111, 22222)

    _target = "openjarvis.mining.cpu_pearl.PearlSubprocessLauncher"
    with patch(_target, return_value=fake_launcher):
        provider = CpuPearlProvider()
        asyncio.run(provider.start(cpu_pearl_config))
        asyncio.run(provider.stop())
        fake_launcher.stop.assert_called_once()
        assert provider.is_running() is False
        assert not sidecar.exists()


def test_stats_returns_zero_stats_when_not_running():
    """stats() before start() returns a MiningStats with provider_id and zeros."""
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    provider = CpuPearlProvider()
    stats = provider.stats()
    assert stats.provider_id == "cpu-pearl"
    assert stats.shares_submitted == 0
    assert stats.shares_accepted == 0


def test_parse_gateway_metrics_extracts_counters():
    """The Prometheus parser extracts the metric names we expect."""
    from openjarvis.mining.cpu_pearl import _parse_gateway_metrics

    sample = """\
# HELP pearl_gateway_shares_submitted_total Total shares submitted.
# TYPE pearl_gateway_shares_submitted_total counter
pearl_gateway_shares_submitted_total 42
# HELP pearl_gateway_shares_accepted_total Total shares accepted.
# TYPE pearl_gateway_shares_accepted_total counter
pearl_gateway_shares_accepted_total 40
pearl_gateway_blocks_found_total 1
"""
    stats = _parse_gateway_metrics(sample, provider_id="cpu-pearl")
    assert stats.provider_id == "cpu-pearl"
    assert stats.shares_submitted == 42
    assert stats.shares_accepted == 40
    assert stats.blocks_found == 1


@pytest.mark.live
@pytest.mark.slow
def test_provider_runs_end_to_end_on_this_host(tmp_path, monkeypatch):
    """Live test: start provider, run for ~30 s, assert is_running was True.

    Requires that py-pearl-mining, miner-base, and pearl-gateway are installed
    in the venv (e.g., via the build-from-pin path) AND that pearld is running
    locally. Otherwise the test is skipped via importorskip.

    Use a non-default port pair (18337/19109) so it doesn't collide with a real
    cpu-pearl session.
    """
    pytest.importorskip("pearl_mining")
    pytest.importorskip("pearl_gateway")

    from openjarvis.mining._stubs import MiningConfig, SoloTarget
    from openjarvis.mining.cpu_pearl import CpuPearlProvider

    sidecar = tmp_path / "mining.json"
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("openjarvis.mining.cpu_pearl._sidecar_path", lambda: sidecar)
    monkeypatch.setattr("openjarvis.mining.cpu_pearl._log_dir", lambda: log_dir)
    monkeypatch.setenv("TEST_PEARLD_PASSWORD", "test")

    cfg = MiningConfig(
        provider="cpu-pearl",
        wallet_address="prl1q" + "0" * 32,
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        fee_bps=0,
        fee_payout_address=None,
        extra={
            "gateway_host": "127.0.0.1",
            "gateway_port": 18337,
            "metrics_port": 19109,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "TEST_PEARLD_PASSWORD",
        },
    )

    provider = CpuPearlProvider()
    asyncio.run(provider.start(cfg))
    still_running_at_end = False
    try:
        import time as _time

        deadline = _time.monotonic() + 30
        saw_running = False
        while _time.monotonic() < deadline:
            if provider.is_running():
                saw_running = True
            else:
                if saw_running:
                    break
            _time.sleep(1.0)
        still_running_at_end = provider.is_running()
    finally:
        asyncio.run(provider.stop())

    if log_dir.exists():
        for log_file in log_dir.glob("*.log"):
            print(f"--- {log_file.name} ---")
            print(log_file.read_text()[:2000])

    assert saw_running, "provider never reported is_running"
    assert still_running_at_end, "provider exited before the live smoke window ended"
