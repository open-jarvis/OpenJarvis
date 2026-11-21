"""AMD-specific hardware tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openjarvis.core.config import (
    GpuInfo,
    HardwareInfo,
    _detect_amd_gpu,
    recommend_engine,
)

pytestmark = pytest.mark.amd


# ---------------------------------------------------------------------------
# Detection / rocm-smi parsing
# ---------------------------------------------------------------------------

# `rocm-smi --showproductname` from a Ryzen AI MAX+ PRO 395 (Strix Halo,
# gfx1151), banner rules abridged to fit the line limit. Note the banner,
# the section header, the failed name probe and the "N/A" series -- the
# naive "first line" parse turned the banner into a GPU name.
STRIX_HALO_PRODUCTNAME = """\

=================== ROCm System Management Interface ===================
============================= Product Info =============================
GPU[0]\t\t: get_name, Failed to load a library
GPU[0]\t\t: Card Series: \t\tN/A
GPU[0]\t\t: Card Model: \t\t0x1586
GPU[0]\t\t: Card Vendor: \t\tAdvanced Micro Devices, Inc. [AMD/ATI]
GPU[0]\t\t: Card SKU: \t\tSTRXLGEN
GPU[0]\t\t: GFX Version: \t\tgfx1151
========================================================================
"""

# An APU reports a small UMA frame-buffer carveout next to a large GTT
# aperture. Models are allocated out of GTT.
STRIX_HALO_MEMINFO = """\
GPU[0]\t\t: VRAM Total Memory (B): 536870912
GPU[0]\t\t: VRAM Total Used Memory (B): 483176448
GPU[0]\t\t: GTT Total Memory (B): 107374182400
GPU[0]\t\t: GTT Total Used Memory (B): 1776222208
"""


class TestAMDUnifiedMemoryDetection:
    """Regression tests for APU (unified memory) detection.

    A Strix Halo was detected as a 0.5 GB GPU named "==== ROCm System
    Management Interface ====", because the name was read off line 0 and the
    capacity was read from the UMA carveout rather than GTT. `jarvis init`
    then recommended a 2B model on a machine comfortably running a 35B.
    """

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        side_effect=[STRIX_HALO_PRODUCTNAME, STRIX_HALO_MEMINFO, "GPU[0] : info"],
    )
    def test_banner_is_never_used_as_the_gpu_name(self, mock_run, mock_which):
        gpu = _detect_amd_gpu()
        assert gpu is not None
        assert "ROCm System Management" not in gpu.name
        assert "=" not in gpu.name
        assert gpu.name == "STRXLGEN"

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        side_effect=[STRIX_HALO_PRODUCTNAME, STRIX_HALO_MEMINFO, "GPU[0] : info"],
    )
    def test_gtt_is_reported_as_capacity_on_an_apu(self, mock_run, mock_which):
        gpu = _detect_amd_gpu()
        assert gpu is not None
        # 107374182400 B = 100 GB of GTT, not the 0.5 GB carveout.
        assert gpu.vram_gb == 100.0

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        side_effect=[STRIX_HALO_PRODUCTNAME, STRIX_HALO_MEMINFO, "GPU[0] : info"],
    )
    def test_gfx_version_is_captured(self, mock_run, mock_which):
        gpu = _detect_amd_gpu()
        assert gpu is not None
        assert gpu.compute_capability == "gfx1151"

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        side_effect=[
            "GPU[0]\t\t: Card Series: \t\tAMD Instinct MI300X",
            # Discrete card: real VRAM, plus a GTT host aperture that must NOT
            # be mistaken for capacity.
            "GPU[0]\t\t: VRAM Total Memory (B): 206158430208\n"
            "GPU[0]\t\t: GTT Total Memory (B): 549755813888",
            "GPU[0] : info",
        ],
    )
    def test_discrete_card_keeps_its_own_vram(self, mock_run, mock_which):
        """GTT must only win when VRAM is implausibly small for a real card."""
        gpu = _detect_amd_gpu()
        assert gpu is not None
        assert gpu.vram_gb == 192.0


class TestAMDDetection:
    """Tests for _detect_amd_gpu() against various rocm-smi outputs."""

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        side_effect=[
            "AMD Instinct MI300X",  # --showproductname
            "GPU[0] : vram Total Memory (B): 206158430208",  # --showmeminfo vram
            "GPU[0] : Some info",  # --showallinfo
        ],
    )
    def test_rocm_smi_parsing(self, mock_run, mock_which):
        gpu = _detect_amd_gpu()
        assert gpu is not None
        assert gpu.vendor == "amd"
        assert "MI300X" in gpu.name

    @patch("openjarvis.core.config.shutil.which", return_value=None)
    def test_rocm_smi_not_found(self, mock_which):
        assert _detect_amd_gpu() is None

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        side_effect=[
            "AMD Instinct MI250X\nAMD Instinct MI250X",  # --showproductname
            "",  # --showmeminfo vram (empty)
            "",  # --showallinfo (empty)
        ],
    )
    def test_amd_gpu_model(self, mock_run, mock_which):
        """First line of rocm-smi output is used as the GPU name."""
        gpu = _detect_amd_gpu()
        assert gpu is not None
        assert "MI250X" in gpu.name

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch("openjarvis.core.config._run_cmd", side_effect=["", "", ""])
    def test_rocm_smi_empty_output(self, mock_run, mock_which):
        """Empty output from rocm-smi --showproductname returns None."""
        assert _detect_amd_gpu() is None

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        side_effect=[
            "AMD Instinct MI300X",
            "GPU[0] : vram Total Memory (B): 206158430208",
            "GPU[0] : Some info",
        ],
    )
    def test_amd_vram_parsing(self, mock_run, mock_which):
        """VRAM is parsed from --showmeminfo vram output."""
        gpu = _detect_amd_gpu()
        assert gpu is not None
        # 206158430208 bytes = ~192.0 GB
        assert gpu.vram_gb == 192.0

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        side_effect=[
            "AMD Instinct MI300X",
            (
                "GPU[0] : vram Total Memory (B): 206158430208\n"
                "GPU[0] : vram Total Used Memory (B): 0\n"
                "GPU[1] : vram Total Memory (B): 206158430208\n"
                "GPU[1] : vram Total Used Memory (B): 0\n"
                "GPU[2] : vram Total Memory (B): 206158430208\n"
                "GPU[2] : vram Total Used Memory (B): 0\n"
                "GPU[3] : vram Total Memory (B): 206158430208\n"
                "GPU[3] : vram Total Used Memory (B): 0"
            ),
            (
                "GPU[0] : Info line\n"
                "GPU[1] : Info line\n"
                "GPU[2] : Info line\n"
                "GPU[3] : Info line"
            ),
        ],
    )
    def test_amd_multi_gpu_count(self, mock_run, mock_which):
        """Multiple GPU entries in --showallinfo are counted."""
        gpu = _detect_amd_gpu()
        assert gpu is not None
        assert gpu.count == 4

    @patch("openjarvis.core.config.shutil.which", return_value="/usr/bin/rocm-smi")
    @patch(
        "openjarvis.core.config._run_cmd",
        side_effect=[
            "AMD Instinct MI300X",
            "garbled output with no valid memory info",
            "GPU[0] : Some info",
        ],
    )
    def test_amd_vram_parse_failure(self, mock_run, mock_which):
        """Garbled VRAM output falls back to 0.0."""
        gpu = _detect_amd_gpu()
        assert gpu is not None
        assert gpu.vram_gb == 0.0


# ---------------------------------------------------------------------------
# Engine recommendation
# ---------------------------------------------------------------------------


class TestAMDEngineRecommendation:
    """Tests that AMD datacenter cards map to vllm, consumer cards to lemonade."""

    def test_mi300x_recommends_vllm(self):
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="AMD EPYC 9654",
            cpu_count=96,
            ram_gb=768.0,
            gpu=GpuInfo(
                vendor="amd",
                name="AMD Instinct MI300X",
                vram_gb=192.0,
                count=1,
            ),
        )
        assert recommend_engine(hw) == "vllm"

    def test_mi350_recommends_vllm(self):
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="AMD EPYC 9654",
            cpu_count=96,
            ram_gb=768.0,
            gpu=GpuInfo(
                vendor="amd",
                name="AMD Instinct MI350X",
                vram_gb=288.0,
                count=1,
            ),
        )
        assert recommend_engine(hw) == "vllm"

    def test_amd_consumer_recommends_lemonade(self):
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="AMD Ryzen 9 7950X",
            cpu_count=32,
            ram_gb=64.0,
            gpu=GpuInfo(
                vendor="amd",
                name="AMD Radeon RX 7900 XTX",
                vram_gb=24.0,
                count=1,
            ),
        )
        assert recommend_engine(hw) == "lemonade"

    def test_amd_generic_recommends_lemonade(self):
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="AMD EPYC",
            cpu_count=64,
            ram_gb=256.0,
            gpu=GpuInfo(vendor="amd", name="AMD GPU", vram_gb=0.0, count=1),
        )
        assert recommend_engine(hw) == "lemonade"

    def test_amd_multi_gpu_recommends_vllm(self):
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="AMD EPYC 9654",
            cpu_count=128,
            ram_gb=1024.0,
            gpu=GpuInfo(
                vendor="amd",
                name="AMD Instinct MI300X",
                vram_gb=192.0,
                count=4,
            ),
        )
        assert recommend_engine(hw) == "vllm"
