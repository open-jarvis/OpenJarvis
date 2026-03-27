"""Tests for ``recommend_model()`` hardware-aware model recommendation."""

from __future__ import annotations

from openjarvis.core.config import GpuInfo, HardwareInfo, recommend_model


class TestRecommendModelGpu:
    """GPU-based model recommendation."""

    def test_24gb_gpu_picks_qwen35_35b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=64.0,
            gpu=GpuInfo(vendor="nvidia", name="RTX 4090", vram_gb=24.0, count=1),
        )
        result = recommend_model(hw, "ollama")
        # 35B * 0.5 * 1.1 = 19.25 GB; available = 24 * 0.9 = 21.6 → fits
        assert result == "qwen3.5:35b"

    def test_8gb_gpu_picks_qwen35_14b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=32.0,
            gpu=GpuInfo(vendor="nvidia", name="RTX 3070", vram_gb=8.0, count=1),
        )
        result = recommend_model(hw, "ollama")
        # 14B * 0.5 * 1.1 = 7.7 GB; available = 8 * 0.9 = 7.2 → too big
        # 8B * 0.5 * 1.1 = 4.4 GB; available = 7.2 → fits
        assert result == "qwen3.5:9b"

    def test_4gb_gpu_picks_qwen35_4b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=16.0,
            gpu=GpuInfo(vendor="nvidia", name="GTX 1650", vram_gb=4.0, count=1),
        )
        result = recommend_model(hw, "ollama")
        # 4B * 0.5 * 1.1 = 2.2 GB; available = 4 * 0.9 = 3.6 → fits
        assert result == "qwen3.5:4b"

    def test_2gb_gpu_picks_qwen35_3b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=8.0,
            gpu=GpuInfo(vendor="nvidia", name="GTX 750", vram_gb=2.0, count=1),
        )
        result = recommend_model(hw, "ollama")
        # 3B * 0.5 * 1.1 = 1.65 GB; available = 2 * 0.9 = 1.8 → fits
        assert result == "qwen3.5:2b"

    def test_multi_gpu_picks_larger_model(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=256.0,
            gpu=GpuInfo(vendor="nvidia", name="A100", vram_gb=80.0, count=2),
        )
        result = recommend_model(hw, "vllm")
        # available = 80 * 2 * 0.9 = 144 GB
        # 397B * 0.5 * 1.1 = 218.35 → too big
        # 122B * 0.5 * 1.1 = 67.1 → fits
        assert result == "qwen3.5:122b"

    def test_huge_vram_picks_397b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=512.0,
            gpu=GpuInfo(vendor="nvidia", name="H100", vram_gb=80.0, count=4),
        )
        result = recommend_model(hw, "vllm")
        # available = 80 * 4 * 0.9 = 288 GB
        # 397B * 0.5 * 1.1 = 218.35 → fits
        assert result == "qwen3.5:397b"


class TestRecommendModelCpuOnly:
    """CPU-only model recommendation."""

    def test_cpu_only_16gb_ram(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=16.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        # available = (16 - 4) * 0.8 = 9.6 GB
        # 27B * 0.5 * 1.1 = 14.85 → too big
        # 9B * 0.5 * 1.1 = 4.95 → fits
        assert result == "qwen3.5:9b"

    def test_cpu_only_8gb_ram(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=8.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        # available = (8 - 4) * 0.8 = 3.2 GB
        # 8B * 0.5 * 1.1 = 4.4 → too big
        # 4B * 0.5 * 1.1 = 2.2 → fits
        assert result == "qwen3.5:4b"

    def test_cpu_only_4gb_ram(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=4.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        # available = (4 - 4) * 0.8 = 0 → nothing fits
        assert result == ""


class TestRecommendModelEdgeCases:
    """Edge cases."""

    def test_no_ram_no_gpu(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=0.0, gpu=None)
        assert recommend_model(hw, "ollama") == ""

    def test_engine_filter(self) -> None:
        """397b is not supported on ollama, only vllm/sglang."""
        hw = HardwareInfo(
            platform="linux",
            ram_gb=512.0,
            gpu=GpuInfo(vendor="nvidia", name="H100", vram_gb=80.0, count=4),
        )
        # With ollama, 397b is excluded (only vllm, sglang)
        result = recommend_model(hw, "ollama")
        assert result == "qwen3.5:122b"


class TestRecommendModelMlx:
    """Apple Silicon (MLX) model recommendation."""

    def test_apple_silicon_8gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=8.0,
            gpu=GpuInfo(vendor="apple", name="Apple M1", vram_gb=8.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        assert result == "qwen3.5:9b"

    def test_apple_silicon_16gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=16.0,
            gpu=GpuInfo(vendor="apple", name="Apple M2", vram_gb=16.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        # available = 16 * 0.9 = 14.4 GB
        # 27B * 0.5 * 1.1 = 14.85 → too big
        # 9B * 0.5 * 1.1 = 4.95 → fits
        assert result == "qwen3.5:9b"

    def test_apple_silicon_32gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=32.0,
            gpu=GpuInfo(vendor="apple", name="Apple M2 Pro", vram_gb=32.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        assert result == "qwen3.5:27b"

    def test_apple_silicon_64gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=64.0,
            gpu=GpuInfo(vendor="apple", name="Apple M2 Max", vram_gb=64.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        assert result == "qwen3.5:27b"
