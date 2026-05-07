"""Tests for openjarvis.mining.apple_mps_pearl."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

_AVAIL = "openjarvis.mining._install.pearl_packages_available"


@pytest.fixture
def mps_config():
    from openjarvis.mining._stubs import MiningConfig, SoloTarget

    return MiningConfig(
        provider="apple-mps-pearl",
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
            "m": 128,
            "n": 128,
            "k": 1024,
            "rank": 64,
        },
    )


def test_detect_requires_macos(hopper_hw):
    from openjarvis.mining.apple_mps_pearl import AppleMpsPearlProvider

    with patch(_AVAIL, return_value=True):
        cap = AppleMpsPearlProvider.detect(hopper_hw, engine_id="mlx", model="any")
    assert cap.supported is False
    assert "macos" in cap.reason.lower()


def test_detect_requires_apple_gpu():
    from openjarvis.core.config import HardwareInfo
    from openjarvis.mining.apple_mps_pearl import AppleMpsPearlProvider

    hw = HardwareInfo(
        platform="darwin", cpu_brand="Apple", cpu_count=12, ram_gb=64.0, gpu=None
    )
    with patch(_AVAIL, return_value=True):
        cap = AppleMpsPearlProvider.detect(hw, engine_id="mlx", model="any")
    assert cap.supported is False
    assert "apple gpu" in cap.reason.lower()


def test_detect_requires_pearl_packages(apple_hw):
    from openjarvis.mining.apple_mps_pearl import AppleMpsPearlProvider

    with patch(_AVAIL, return_value=False):
        cap = AppleMpsPearlProvider.detect(apple_hw, engine_id="mlx", model="any")
    assert cap.supported is False
    assert "mining-pearl-cpu" in cap.reason


def test_detect_supported_when_torch_mps_available(apple_hw):
    from openjarvis.mining.apple_mps_pearl import AppleMpsPearlProvider

    with (
        patch("openjarvis.mining._install.pearl_packages_available", return_value=True),
        patch(
            "openjarvis.mining.apple_mps_pearl._torch_mps_available",
            return_value=(True, None),
        ),
    ):
        cap = AppleMpsPearlProvider.detect(apple_hw, engine_id="mlx", model="any")
    assert cap.supported is True


@pytest.mark.parametrize("chip", ["M2 Max", "M3 Max", "M4 Max", "M5 Max"])
def test_detect_supports_apple_silicon_gpu_generations(chip):
    from openjarvis.core.config import GpuInfo, HardwareInfo
    from openjarvis.mining.apple_mps_pearl import AppleMpsPearlProvider

    hw = HardwareInfo(
        platform="darwin",
        cpu_brand=f"Apple {chip}",
        cpu_count=16,
        ram_gb=128.0,
        gpu=GpuInfo(vendor="apple", name=chip, vram_gb=128.0, count=1),
    )
    with (
        patch(_AVAIL, return_value=True),
        patch(
            "openjarvis.mining.apple_mps_pearl._torch_mps_available",
            return_value=(True, None),
        ),
    ):
        cap = AppleMpsPearlProvider.detect(hw, engine_id="mlx", model="any")

    assert cap.supported is True


def test_start_uses_mps_miner_module(mps_config, tmp_path, monkeypatch):
    from openjarvis.mining.apple_mps_pearl import AppleMpsPearlProvider

    sidecar = tmp_path / "mining.json"
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("openjarvis.mining.cpu_pearl._sidecar_path", lambda: sidecar)
    monkeypatch.setattr("openjarvis.mining.cpu_pearl._log_dir", lambda: log_dir)
    monkeypatch.setattr("openjarvis.mining.apple_mps_pearl._log_dir", lambda: log_dir)
    monkeypatch.setenv("TEST_PEARLD_PASSWORD", "secret")
    fake_launcher = MagicMock()
    fake_launcher.is_running.return_value = True
    fake_launcher.pids.return_value = (11111, 22222)

    target = "openjarvis.mining.apple_mps_pearl.PearlSubprocessLauncher"
    with patch(target, return_value=fake_launcher) as launcher_cls:
        provider = AppleMpsPearlProvider()
        asyncio.run(provider.start(mps_config))

    assert launcher_cls.call_args.kwargs["provider_id"] == "apple-mps-pearl"
    assert (
        launcher_cls.call_args.kwargs["miner_module"]
        == "openjarvis.mining._mps_miner_loop_main"
    )
    payload = json.loads(sidecar.read_text())
    assert payload["provider"] == "apple-mps-pearl"


@pytest.mark.slow
def test_mps_noisy_gemm_plain_proof_verifies_when_mps_available():
    """Cryptographic smoke test for the MPS mining core."""
    torch = pytest.importorskip("torch")
    pearl_mining = pytest.importorskip("pearl_mining")
    pytest.importorskip("miner_base")
    if not torch.backends.mps.is_available():
        pytest.skip("MPS is not available on this host")

    from miner_base.block_submission import create_proof
    from miner_base.commitment_hash import CommitmentHasher
    from miner_base.noise_generation import NoiseGenerator
    from miner_base.noisy_gemm import POW_TARGET_EASIEST, NoisyGemm

    from openjarvis.mining._mps_miner_loop_main import (
        MpsNoisyGemmAdapter,
        _mining_config_for_shape,
    )

    header = pearl_mining.IncompleteBlockHeader(
        version=1,
        prev_block=bytes(32),
        merkle_root=bytes([1]) * 32,
        timestamp=1,
        nbits=0x207FFFFF,
    )
    header_bytes = header.to_bytes()
    # Match the provider defaults so this catches regressions in the shipped
    # Apple-MPS launch shape.
    m = n = 128
    k = 1024
    rank = 64
    mining_config = _mining_config_for_shape(pearl_mining, k=k, rank=rank)

    a_cpu = torch.randint(-64, 64, (m, k), dtype=torch.int8)
    b_cpu = torch.randint(-64, 64, (k, n), dtype=torch.int8)
    commitment_hash = CommitmentHasher.commitment_hash(
        a_cpu,
        b_cpu,
        header_bytes,
        mining_config,
    )
    noise = NoiseGenerator(noise_rank=rank, noise_range=128).generate_noise_metrices(
        commitment_hash.noise_seed_A,
        commitment_hash.noise_seed_B,
        m,
        k,
        n,
    )
    device = torch.device("mps")
    gemm = MpsNoisyGemmAdapter.build(
        NoisyGemm,
        noise_range=128,
        noise_rank=rank,
        hash_tile_h=16,
        hash_tile_w=16,
        matmul_tile_h=64,
        matmul_tile_w=64,
    )
    result, found = gemm.noisy_gemm(
        a_cpu.to(device),
        b_cpu.to(device),
        *(x.to(device) for x in noise),
        commitment_hash=commitment_hash,
        pow_target=POW_TARGET_EASIEST,
    )

    expected = torch.matmul(a_cpu.to(torch.int32), b_cpu.to(torch.int32))
    assert torch.equal(result.cpu(), expected)
    assert found is True
    plain_proof = create_proof(gemm.get_opened_block_info(), header_bytes)
    ok, msg = pearl_mining.verify_plain_proof(header, plain_proof)
    assert ok, msg
