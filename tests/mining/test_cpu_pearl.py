"""Tests for openjarvis.mining.cpu_pearl.CpuPearlProvider."""
from __future__ import annotations

from unittest.mock import patch

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
