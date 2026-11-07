"""Tests for MFU/MBU efficiency calculator."""

from __future__ import annotations

import pytest

from friday_ai.telemetry.efficiency import (
    EfficiencyMetrics,
    compute_efficiency,
    estimate_model_bytes_per_token,
    estimate_model_flops_per_token,
)

# ---------------------------------------------------------------------------
# Constants: A100 SXM4 80GB specs
# ---------------------------------------------------------------------------
A100_PEAK_TFLOPS = 312.0  # FP16 Tensor Core
A100_PEAK_BW_GB_S = 2039.0  # HBM2e


# ---------------------------------------------------------------------------
# estimate_model_flops_per_token
# ---------------------------------------------------------------------------
class TestEstimateModelFlopsPerToken:
    def test_7b_dense(self) -> None:
        flops = estimate_model_flops_per_token(7.0)
        assert flops == pytest.approx(14e9)

    def test_70b_dense(self) -> None:
        flops = estimate_model_flops_per_token(70.0)
        assert flops == pytest.approx(140e9)

    def test_moe_mixtral(self) -> None:
        # Mixtral 8x7B: ~47B total, ~13B active per token
        flops = estimate_model_flops_per_token(47.0, active_params_b=13.0)
        assert flops == pytest.approx(26e9)

    def test_active_params_none_uses_total(self) -> None:
        result = estimate_model_flops_per_token(7.0, None)
        assert result == estimate_model_flops_per_token(7.0)


# ---------------------------------------------------------------------------
# estimate_model_bytes_per_token
# ---------------------------------------------------------------------------
class TestEstimateModelBytesPerToken:
    def test_7b_fp16(self) -> None:
        bpt = estimate_model_bytes_per_token(7.0)
        assert bpt == pytest.approx(14e9)

    def test_7b_int8(self) -> None:
        bpt = estimate_model_bytes_per_token(7.0, bytes_per_param=1.0)
        assert bpt == pytest.approx(7e9)

    def test_70b_fp16(self) -> None:
        bpt = estimate_model_bytes_per_token(70.0)
        assert bpt == pytest.approx(140e9)


# ---------------------------------------------------------------------------
# compute_efficiency
# ---------------------------------------------------------------------------
class TestComputeEfficiency:
    def test_7b_100tps_single_gpu(self) -> None:
        """7B model, 100 tok/s, single A100."""
        m = compute_efficiency(
            param_count_b=7.0,
            active_params_b=None,
            gpu_peak_tflops=A100_PEAK_TFLOPS,
            gpu_peak_bandwidth_gb_s=A100_PEAK_BW_GB_S,
            tokens_per_sec=100.0,
        )
        # actual_flops = 14e9 * 100 = 1.4e12
        assert m.actual_flops == pytest.approx(1.4e12)
        # peak_flops = 312e12
        assert m.peak_flops == pytest.approx(312e12)
        # MFU = 1.4e12 / 312e12 * 100 ≈ 0.4487%
        expected_mfu = 1.4e12 / 312e12 * 100.0
        assert m.mfu_pct == pytest.approx(expected_mfu)

        # actual_bandwidth = 14e9 * 100 / 1e9 = 1400 GB/s
        assert m.actual_bandwidth_gb_s == pytest.approx(1400.0)
        # MBU = 1400 / 2039 * 100 ≈ 68.66%
        expected_mbu = 1400.0 / 2039.0 * 100.0
        assert m.mbu_pct == pytest.approx(expected_mbu)

    def test_multi_gpu_scaling(self) -> None:
        """2 GPUs should double peak, halving utilization at same throughput."""
        m1 = compute_efficiency(
            param_count_b=7.0,
            active_params_b=None,
            gpu_peak_tflops=A100_PEAK_TFLOPS,
            gpu_peak_bandwidth_gb_s=A100_PEAK_BW_GB_S,
            tokens_per_sec=100.0,
            num_gpus=1,
        )
        m2 = compute_efficiency(
            param_count_b=7.0,
            active_params_b=None,
            gpu_peak_tflops=A100_PEAK_TFLOPS,
            gpu_peak_bandwidth_gb_s=A100_PEAK_BW_GB_S,
            tokens_per_sec=100.0,
            num_gpus=2,
        )
        assert m2.mfu_pct == pytest.approx(m1.mfu_pct / 2.0)
        assert m2.mbu_pct == pytest.approx(m1.mbu_pct / 2.0)
        assert m2.peak_flops == pytest.approx(m1.peak_flops * 2.0)
        assert m2.peak_bandwidth_gb_s == pytest.approx(m1.peak_bandwidth_gb_s * 2.0)

    def test_ipj_with_energy(self) -> None:
        m = compute_efficiency(
            param_count_b=7.0,
            active_params_b=None,
            gpu_peak_tflops=A100_PEAK_TFLOPS,
            gpu_peak_bandwidth_gb_s=A100_PEAK_BW_GB_S,
            tokens_per_sec=100.0,
            energy_joules=50.0,
            accuracy=0.8,
        )
        assert m.ipj == pytest.approx(0.8 / 50.0)

    def test_ipj_zero_energy(self) -> None:
        m = compute_efficiency(
            param_count_b=7.0,
            active_params_b=None,
            gpu_peak_tflops=A100_PEAK_TFLOPS,
            gpu_peak_bandwidth_gb_s=A100_PEAK_BW_GB_S,
            tokens_per_sec=100.0,
            energy_joules=0.0,
            accuracy=0.8,
        )
        assert m.ipj == 0.0

    def test_zero_tokens_per_sec(self) -> None:
        m = compute_efficiency(
            param_count_b=7.0,
            active_params_b=None,
            gpu_peak_tflops=A100_PEAK_TFLOPS,
            gpu_peak_bandwidth_gb_s=A100_PEAK_BW_GB_S,
            tokens_per_sec=0.0,
        )
        assert m.mfu_pct == 0.0
        assert m.mbu_pct == 0.0
        assert m.actual_flops == 0.0
        assert m.actual_bandwidth_gb_s == 0.0

    def test_moe_efficiency(self) -> None:
        """MoE model: FLOPs use active params, bandwidth uses total params."""
        m = compute_efficiency(
            param_count_b=47.0,
            active_params_b=13.0,
            gpu_peak_tflops=A100_PEAK_TFLOPS,
            gpu_peak_bandwidth_gb_s=A100_PEAK_BW_GB_S,
            tokens_per_sec=50.0,
        )
        # actual_flops based on active params: 2*13e9*50 = 1.3e12
        assert m.actual_flops == pytest.approx(1.3e12)
        # bandwidth based on total params: 47e9*2*50/1e9 = 4700 GB/s
        assert m.actual_bandwidth_gb_s == pytest.approx(4700.0)

    def test_returns_dataclass(self) -> None:
        m = compute_efficiency(
            param_count_b=7.0,
            active_params_b=None,
            gpu_peak_tflops=A100_PEAK_TFLOPS,
            gpu_peak_bandwidth_gb_s=A100_PEAK_BW_GB_S,
            tokens_per_sec=100.0,
        )
        assert isinstance(m, EfficiencyMetrics)

    def test_custom_bytes_per_param(self) -> None:
        """INT4 quantization: 0.5 bytes per param."""
        m = compute_efficiency(
            param_count_b=7.0,
            active_params_b=None,
            gpu_peak_tflops=A100_PEAK_TFLOPS,
            gpu_peak_bandwidth_gb_s=A100_PEAK_BW_GB_S,
            tokens_per_sec=100.0,
            bytes_per_param=0.5,
        )
        # bandwidth = 7e9 * 0.5 * 100 / 1e9 = 350 GB/s
        assert m.actual_bandwidth_gb_s == pytest.approx(350.0)
        # MFU should be unchanged (FLOPs don't depend on bytes_per_param)
        m_fp16 = compute_efficiency(
            param_count_b=7.0,
            active_params_b=None,
            gpu_peak_tflops=A100_PEAK_TFLOPS,
            gpu_peak_bandwidth_gb_s=A100_PEAK_BW_GB_S,
            tokens_per_sec=100.0,
        )
        assert m.mfu_pct == pytest.approx(m_fp16.mfu_pct)
