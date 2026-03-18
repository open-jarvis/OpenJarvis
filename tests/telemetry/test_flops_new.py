"""Tests for FLOPs estimation and MFU computation."""

from __future__ import annotations

import pytest

from openjarvis.telemetry.flops import (
    GPU_PEAK_TFLOPS_BF16,
    MODEL_PARAMS_B,
    compute_mfu,
    estimate_flops,
    estimate_flops_no_kv_cache,
)


class TestEstimateFlops:
    def test_known_model(self):
        total, per_tok = estimate_flops("qwen3:8b", 100, 50)
        # 2 * 8e9 * 150 = 2.4e12
        assert total == pytest.approx(2.4e12)
        # 2 * 8e9 = 16e9
        assert per_tok == pytest.approx(16e9)

    def test_unknown_model_zero(self):
        total, per_tok = estimate_flops("totally-unknown-model", 100, 50)
        assert total == 0.0
        assert per_tok == 0.0

    def test_prefix_matching(self):
        # "llama-3.1-8b-instruct" should match prefix "llama-3.1-8b"
        total, per_tok = estimate_flops("llama-3.1-8b-instruct", 10, 10)
        assert total > 0
        # 2 * 8e9 * 20 = 3.2e11
        assert total == pytest.approx(3.2e11)

    def test_zero_tokens(self):
        total, per_tok = estimate_flops("qwen3:8b", 0, 0)
        assert total == 0.0
        assert per_tok == 0.0

    def test_flops_proportional_to_tokens(self):
        total_100, _ = estimate_flops("qwen3:8b", 50, 50)
        total_200, _ = estimate_flops("qwen3:8b", 100, 100)
        assert total_200 == pytest.approx(total_100 * 2.0)


class TestEstimateFlopsNoKvCache:
    def test_known_model(self):
        total, per_tok = estimate_flops_no_kv_cache("qwen3:8b", 100, 50)
        # P * N * (N+1) = 8e9 * 150 * 151 = 1.812e14
        assert total == pytest.approx(8e9 * 150 * 151)
        assert per_tok == pytest.approx(total / 150)

    def test_zero_tokens(self):
        total, per_tok = estimate_flops_no_kv_cache("qwen3:8b", 0, 0)
        assert total == 0.0
        assert per_tok == 0.0

    def test_unknown_model_zero(self):
        total, per_tok = estimate_flops_no_kv_cache("unknown-model", 100, 50)
        assert total == 0.0
        assert per_tok == 0.0


class TestComputeMfu:
    def test_known_gpu(self):
        # 100 TFLOPS actual for 1s on H100 → 100 / 989 * 100 ≈ 10.1%
        flops = 100e12
        mfu = compute_mfu(flops, 1.0, "H100")
        assert mfu == pytest.approx(100.0 / 989.0 * 100.0, rel=1e-3)

    def test_unknown_gpu_zero(self):
        mfu = compute_mfu(100e12, 1.0, "QuantumGPU")
        assert mfu == 0.0

    def test_zero_duration(self):
        mfu = compute_mfu(100e12, 0.0, "H100")
        assert mfu == 0.0

    def test_multi_gpu(self):
        flops = 100e12
        mfu_single = compute_mfu(flops, 1.0, "H100", num_gpus=1)
        mfu_dual = compute_mfu(flops, 1.0, "H100", num_gpus=2)
        assert mfu_dual == pytest.approx(mfu_single / 2.0)

    def test_substring_matching(self):
        # "NVIDIA H100 80GB" should match "H100"
        mfu = compute_mfu(100e12, 1.0, "NVIDIA H100 80GB")
        assert mfu > 0.0

    def test_tables_nonempty(self):
        assert len(GPU_PEAK_TFLOPS_BF16) > 0
        assert len(MODEL_PARAMS_B) > 0
