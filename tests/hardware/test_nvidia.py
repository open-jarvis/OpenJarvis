"""NVIDIA-specific hardware tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openjarvis.core.config import (
    GpuInfo,
    HardwareInfo,
    _detect_nvidia_gpu,
    recommend_engine,
)

pytestmark = pytest.mark.nvidia


# ---------------------------------------------------------------------------
# Detection / nvidia-smi parsing
# ---------------------------------------------------------------------------


class TestNVIDIADetection:
    """Tests for _detect_nvidia_gpu() against various nvidia-smi outputs."""

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        return_value="NVIDIA A100-SXM4-80GB, 81920, 1",
    )
    def test_nvidia_smi_parsing(self, mock_run, mock_which):
        gpu = _detect_nvidia_gpu()
        assert gpu is not None
        assert gpu.name == "NVIDIA A100-SXM4-80GB"
        assert gpu.vram_gb == 80.0
        assert gpu.count == 1
        assert gpu.vendor == "nvidia"

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        return_value=(
            "NVIDIA H100 80GB HBM3, 81920, 4\n"
            "NVIDIA H100 80GB HBM3, 81920, 4\n"
            "NVIDIA H100 80GB HBM3, 81920, 4\n"
            "NVIDIA H100 80GB HBM3, 81920, 4"
        ),
    )
    def test_nvidia_smi_multi_gpu(self, mock_run, mock_which):
        """First line is parsed; count field captures GPU count."""
        gpu = _detect_nvidia_gpu()
        assert gpu is not None
        assert gpu.count == 4
        assert "H100" in gpu.name

    @patch("openjarvis.core.config.shutil.which", return_value=None)
    def test_nvidia_smi_not_found(self, mock_which):
        assert _detect_nvidia_gpu() is None

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch("openjarvis.core.config._run_cmd", return_value="")
    def test_nvidia_smi_error(self, mock_run, mock_which):
        """Empty output from nvidia-smi returns None."""
        assert _detect_nvidia_gpu() is None

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        return_value="NVIDIA GeForce RTX 4090, 24564, 1",
    )
    def test_vram_detection(self, mock_run, mock_which):
        gpu = _detect_nvidia_gpu()
        assert gpu is not None
        # 24564 MB -> ~24.0 GB
        assert gpu.vram_gb == pytest.approx(24.0, abs=0.1)

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        return_value="NVIDIA A100-SXM4-80GB, 81920, 1",
    )
    def test_compute_capability(self, mock_run, mock_which):
        """compute_capability defaults to empty string when not parsed."""
        gpu = _detect_nvidia_gpu()
        assert gpu is not None
        assert gpu.compute_capability == ""


# ---------------------------------------------------------------------------
# Engine recommendation
# ---------------------------------------------------------------------------


class TestNVIDIAEngineRecommendation:
    """Tests that NVIDIA cards map to the correct inference engine."""

    def test_a100_recommends_vllm(self):
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="EPYC",
            cpu_count=64,
            ram_gb=512.0,
            gpu=GpuInfo(
                vendor="nvidia",
                name="NVIDIA A100-SXM4-80GB",
                vram_gb=80.0,
                count=1,
            ),
        )
        assert recommend_engine(hw) == "vllm"

    def test_h100_recommends_vllm(self):
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="EPYC",
            cpu_count=64,
            ram_gb=512.0,
            gpu=GpuInfo(
                vendor="nvidia",
                name="NVIDIA H100 80GB HBM3",
                vram_gb=80.0,
                count=1,
            ),
        )
        assert recommend_engine(hw) == "vllm"

    def test_v100_recommends_ollama(self):
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="Xeon",
            cpu_count=32,
            ram_gb=256.0,
            gpu=GpuInfo(
                vendor="nvidia",
                name="NVIDIA Tesla V100-SXM2-32GB",
                vram_gb=32.0,
                count=1,
            ),
        )
        assert recommend_engine(hw) == "ollama"

    def test_rtx_4090_recommends_ollama(self):
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="i9-14900K",
            cpu_count=24,
            ram_gb=64.0,
            gpu=GpuInfo(
                vendor="nvidia",
                name="NVIDIA GeForce RTX 4090",
                vram_gb=24.0,
                count=1,
            ),
        )
        assert recommend_engine(hw) == "ollama"

    def test_multi_gpu_config(self):
        """Multi-GPU datacenter setup still recommends vllm."""
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="EPYC",
            cpu_count=128,
            ram_gb=1024.0,
            gpu=GpuInfo(vendor="nvidia", name="NVIDIA H100", vram_gb=80.0, count=8),
        )
        assert recommend_engine(hw) == "vllm"
        assert hw.gpu.count == 8
