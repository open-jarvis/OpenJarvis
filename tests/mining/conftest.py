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
