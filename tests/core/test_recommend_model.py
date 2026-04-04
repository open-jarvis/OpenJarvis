"""Tests for ``recommend_model()`` hardware-aware model recommendation."""

from __future__ import annotations

from openjarvis.core.config import GpuInfo, HardwareInfo, recommend_model


class TestRecommendModelTiers:
    """Tier-based model recommendation (Qwen3.5 MoE)."""

    def test_8gb_ram_picks_qwen35_2b(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=8.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        # available = (8 - 4) * 0.8 = 3.2 GB → ≤8 tier → qwen3.5:2b
        assert result == "qwen3.5:2b"

    def test_16gb_ram_picks_qwen35_4b(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=16.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        # available = (16 - 4) * 0.8 = 9.6 GB → ≤16 tier → qwen3.5:4b
        assert result == "qwen3.5:4b"

    def test_32gb_ram_picks_qwen35_9b(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=32.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        # available = (32 - 4) * 0.8 = 22.4 GB → ≤32 tier → qwen3.5:9b
        assert result == "qwen3.5:9b"

    def test_64gb_ram_picks_qwen35_27b(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=64.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        # available = (64 - 4) * 0.8 = 48 GB → >32 → qwen3.5:27b
        assert result == "qwen3.5:27b"


class TestRecommendModelGpu:
    """GPU-based model recommendation."""

    def test_24gb_gpu_picks_qwen35_9b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=64.0,
            gpu=GpuInfo(vendor="nvidia", name="RTX 4090", vram_gb=24.0, count=1),
        )
        result = recommend_model(hw, "ollama")
        # available = 24 * 0.9 = 21.6 GB → ≤32 tier → qwen3.5:9b
        assert result == "qwen3.5:9b"

    def test_8gb_gpu_picks_qwen35_2b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=32.0,
            gpu=GpuInfo(vendor="nvidia", name="RTX 3070", vram_gb=8.0, count=1),
        )
        result = recommend_model(hw, "ollama")
        # available = 8 * 0.9 = 7.2 GB → ≤8 tier → qwen3.5:2b
        assert result == "qwen3.5:2b"

    def test_4gb_gpu_picks_qwen35_2b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=16.0,
            gpu=GpuInfo(vendor="nvidia", name="GTX 1650", vram_gb=4.0, count=1),
        )
        result = recommend_model(hw, "ollama")
        # available = 4 * 0.9 = 3.6 GB → ≤8 tier → qwen3.5:2b
        assert result == "qwen3.5:2b"

    def test_multi_gpu_picks_qwen35_27b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=256.0,
            gpu=GpuInfo(vendor="nvidia", name="A100", vram_gb=80.0, count=2),
        )
        result = recommend_model(hw, "vllm")
        # available = 80 * 2 * 0.9 = 144 GB → >64 → qwen3.5:27b (tier fallback)
        assert result == "qwen3.5:27b"

    def test_huge_vram_picks_largest_compatible(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=512.0,
            gpu=GpuInfo(vendor="nvidia", name="H100", vram_gb=80.0, count=4),
        )
        result = recommend_model(hw, "vllm")
        # available = 288 GB → tier fallback qwen3.5:27b, valid for vllm
        assert result == "qwen3.5:27b"


class TestRecommendModelEdgeCases:
    """Edge cases."""

    def test_no_ram_no_gpu(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=0.0, gpu=None)
        assert recommend_model(hw, "ollama") == ""

    def test_6gb_ram_picks_qwen35_2b(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=6.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        # available = (6 - 4) * 0.8 = 1.6 GB → ≤8 tier → qwen3.5:2b
        assert result == "qwen3.5:2b"

    def test_very_low_ram_returns_empty(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=4.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        # available = (4 - 4) * 0.8 = 0 → nothing
        assert result == ""


class TestRecommendModelMlx:
    """Apple Silicon (MLX) model recommendation."""

    def test_apple_silicon_8gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=8.0,
            gpu=GpuInfo(vendor="apple", name="Apple M1", vram_gb=8.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        # available = 8 * 0.9 = 7.2 GB → ≤8 tier → qwen3.5:2b
        assert result == "qwen3.5:2b"

    def test_apple_silicon_16gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=16.0,
            gpu=GpuInfo(vendor="apple", name="Apple M2", vram_gb=16.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        # available = 16 * 0.9 = 14.4 GB → ≤16 tier → qwen3.5:4b
        assert result == "qwen3.5:4b"

    def test_apple_silicon_32gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=32.0,
            gpu=GpuInfo(vendor="apple", name="Apple M2 Pro", vram_gb=32.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        # available = 32 * 0.9 = 28.8 GB → ≤32 tier → qwen3.5:9b
        assert result == "qwen3.5:9b"

    def test_apple_silicon_64gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=64.0,
            gpu=GpuInfo(vendor="apple", name="Apple M2 Max", vram_gb=64.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        # available = 64 * 0.9 = 57.6 GB → ≤64 tier → qwen3.5:27b
        assert result == "qwen3.5:27b"
