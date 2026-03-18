"""Tests for hardware detection, GPU vendor identification,
and engine recommendation."""

from __future__ import annotations

from unittest.mock import patch

from openjarvis.core.config import (
    GpuInfo,
    _detect_amd_gpu,
    _detect_apple_gpu,
    _detect_nvidia_gpu,
    recommend_engine,
)

# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------


class TestDetectHardware:
    """Tests for the top-level detect_hardware() function."""

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        return_value="NVIDIA A100-SXM4-80GB, 81920, 1",
    )
    def test_detect_nvidia_gpu(self, mock_run, mock_which):
        gpu = _detect_nvidia_gpu()
        assert gpu is not None
        assert gpu.vendor == "nvidia"
        assert "A100" in gpu.name
        assert gpu.vram_gb == 80.0
        assert gpu.count == 1

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        side_effect=[
            "AMD Instinct MI300X",  # --showproductname
            "GPU[0] : vram Total Memory (B): 206158430208",  # --showmeminfo vram
            "GPU[0] : Some info",  # --showallinfo
        ],
    )
    def test_detect_amd_gpu(self, mock_run, mock_which):
        gpu = _detect_amd_gpu()
        assert gpu is not None
        assert gpu.vendor == "amd"
        assert "MI300X" in gpu.name

    @patch("openjarvis.core.config.platform.system", return_value="Darwin")
    @patch(
        "openjarvis.core.config._run_cmd",
        return_value=(
            "Graphics/Displays:\n"
            "    Apple M4 Max:\n"
            "      Chipset Model: Apple M4 Max\n"
            "      Type: GPU\n"
            "      Bus: Built-In\n"
        ),
    )
    def test_detect_apple_silicon(self, mock_run, mock_system):
        gpu = _detect_apple_gpu()
        assert gpu is not None
        assert gpu.vendor == "apple"
        assert "M4 Max" in gpu.name

    @patch("openjarvis.core.config.shutil.which", return_value=None)
    @patch("openjarvis.core.config.platform.system", return_value="Linux")
    def test_detect_no_gpu(self, mock_system, mock_which):
        """All GPU detection methods return None when no GPU is present."""
        assert _detect_nvidia_gpu() is None
        assert _detect_amd_gpu() is None
        assert _detect_apple_gpu() is None


# ---------------------------------------------------------------------------
# Engine recommendation
# ---------------------------------------------------------------------------


class TestRecommendEngine:
    """Tests for recommend_engine() logic across hardware profiles."""

    def test_nvidia_datacenter_vllm(self, hardware_nvidia):
        assert recommend_engine(hardware_nvidia) == "vllm"

    def test_nvidia_consumer_ollama(self, hardware_nvidia_consumer):
        assert recommend_engine(hardware_nvidia_consumer) == "ollama"

    def test_amd_vllm(self, hardware_amd):
        assert recommend_engine(hardware_amd) == "vllm"

    def test_apple_mlx(self, hardware_apple):
        assert recommend_engine(hardware_apple) == "mlx"

    def test_cpu_only_llamacpp(self, hardware_cpu_only):
        assert recommend_engine(hardware_cpu_only) == "llamacpp"


# ---------------------------------------------------------------------------
# Dataclass serialization / field access
# ---------------------------------------------------------------------------


class TestHardwareProfileSerialization:
    """Tests that dataclass fields are accessible and hold correct values."""

    def test_gpu_info_fields(self, nvidia_gpu):
        assert nvidia_gpu.vendor == "nvidia"
        assert nvidia_gpu.name == "NVIDIA A100-SXM4-80GB"
        assert nvidia_gpu.vram_gb == 80.0
        assert nvidia_gpu.count == 1

    def test_hardware_info_fields(self, hardware_nvidia):
        assert hardware_nvidia.platform == "linux"
        assert hardware_nvidia.cpu_brand == "AMD EPYC 7763"
        assert hardware_nvidia.cpu_count == 64
        assert hardware_nvidia.ram_gb == 512.0
        assert hardware_nvidia.gpu is not None

    def test_vram_sufficient_for_model(self):
        """Verify that VRAM capacity can be checked against a model requirement."""
        gpu = GpuInfo(vendor="nvidia", name="NVIDIA A100", vram_gb=80.0, count=1)
        model_requirement_gb = 40.0
        assert gpu.vram_gb >= model_requirement_gb

        small_gpu = GpuInfo(vendor="nvidia", name="RTX 3060", vram_gb=12.0, count=1)
        large_model_gb = 70.0
        assert small_gpu.vram_gb < large_model_gb
