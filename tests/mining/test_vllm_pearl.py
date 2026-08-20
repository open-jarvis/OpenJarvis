"""End-to-end tests for VllmPearlProvider with mocked Docker + filesystem."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def test_vllm_pearl_detect_supported_on_h100(hopper_hw):
    from openjarvis.mining.vllm_pearl import VllmPearlProvider

    cap = VllmPearlProvider.detect(
        hopper_hw,
        engine_id="vllm",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
    )
    assert cap.supported is True


def test_vllm_pearl_detect_unsupported_on_apple(apple_hw):
    from openjarvis.mining.vllm_pearl import VllmPearlProvider

    cap = VllmPearlProvider.detect(
        apple_hw,
        engine_id="mlx",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
    )
    assert cap.supported is False


@pytest.mark.asyncio
async def test_vllm_pearl_start_writes_sidecar(tmp_path, monkeypatch):
    from openjarvis.mining._stubs import MiningConfig, SoloTarget
    from openjarvis.mining.vllm_pearl import VllmPearlProvider

    sidecar_path = tmp_path / "mining.json"
    monkeypatch.setattr("openjarvis.mining.vllm_pearl.SIDECAR_PATH", sidecar_path)
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
async def test_vllm_pearl_start_pool_target_raises_not_implemented(
    monkeypatch, tmp_path
):  # noqa: E501
    from openjarvis.mining._stubs import MiningConfig, PoolTarget
    from openjarvis.mining.vllm_pearl import VllmPearlProvider

    sidecar_path = tmp_path / "mining.json"
    monkeypatch.setattr("openjarvis.mining.vllm_pearl.SIDECAR_PATH", sidecar_path)

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

    monkeypatch.setattr("openjarvis.mining.vllm_pearl.SIDECAR_PATH", written_sidecar)
    fake_client = MagicMock()
    provider = VllmPearlProvider(docker_client=fake_client)
    provider._launcher._container = MagicMock()  # simulate running
    await provider.stop()
    assert not written_sidecar.exists()


def test_vllm_pearl_stats_reads_gateway(monkeypatch, written_sidecar):
    from openjarvis.mining.vllm_pearl import VllmPearlProvider

    monkeypatch.setattr("openjarvis.mining.vllm_pearl.SIDECAR_PATH", written_sidecar)
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


def test_vllm_pearl_stats_falls_back_to_vllm_metrics(monkeypatch, written_sidecar):
    from openjarvis.mining.vllm_pearl import VllmPearlProvider

    monkeypatch.setattr("openjarvis.mining.vllm_pearl.SIDECAR_PATH", written_sidecar)

    def fake_get(url: str, timeout: float):
        resp = MagicMock()
        if url == "http://127.0.0.1:8339/metrics":
            raise OSError("connection refused")
        assert url == "http://127.0.0.1:8000/metrics"
        resp.status_code = 200
        resp.text = "process_start_time_seconds 1\n"
        return resp

    with patch("openjarvis.mining.vllm_pearl.httpx.get", side_effect=fake_get):
        provider = VllmPearlProvider(docker_client=MagicMock())
        stats = provider.stats()
        assert stats.uptime_seconds > 0
        assert stats.last_error is None


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
