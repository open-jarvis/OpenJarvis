"""Tests for inter-token latency percentile computation."""

from __future__ import annotations

import pytest

from openjarvis.telemetry.itl import compute_itl_stats


class TestComputeItlStats:
    def test_empty_timestamps(self):
        result = compute_itl_stats([])
        assert result["p50_ms"] == 0
        assert result["mean_ms"] == 0

    def test_single_timestamp(self):
        result = compute_itl_stats([100.0])
        assert result["p50_ms"] == 0
        assert result["max_ms"] == 0

    def test_two_timestamps(self):
        result = compute_itl_stats([0.0, 10.0])
        assert result["p50_ms"] == 10.0
        assert result["mean_ms"] == 10.0
        assert result["min_ms"] == 10.0
        assert result["max_ms"] == 10.0

    def test_uniform_spacing(self):
        # 11 timestamps 5ms apart → 10 ITLs all = 5.0
        timestamps = [i * 5.0 for i in range(11)]
        result = compute_itl_stats(timestamps)
        assert result["p50_ms"] == pytest.approx(5.0)
        assert result["p90_ms"] == pytest.approx(5.0)
        assert result["p95_ms"] == pytest.approx(5.0)
        assert result["p99_ms"] == pytest.approx(5.0)
        assert result["mean_ms"] == pytest.approx(5.0)
        assert result["min_ms"] == pytest.approx(5.0)
        assert result["max_ms"] == pytest.approx(5.0)

    def test_varying_spacing(self):
        # [0, 1, 3, 6, 10] → ITLs = [1, 2, 3, 4]
        timestamps = [0.0, 1.0, 3.0, 6.0, 10.0]
        result = compute_itl_stats(timestamps)
        assert result["min_ms"] == pytest.approx(1.0)
        assert result["max_ms"] == pytest.approx(4.0)
        assert result["mean_ms"] == pytest.approx(2.5)
        # Median of sorted [1,2,3,4] → 2.5
        assert result["p50_ms"] == pytest.approx(2.5)

    def test_percentile_ordering(self):
        timestamps = [float(i) for i in range(101)]
        result = compute_itl_stats(timestamps)
        assert result["p50_ms"] <= result["p90_ms"]
        assert result["p90_ms"] <= result["p95_ms"]
        assert result["p95_ms"] <= result["p99_ms"]

    def test_all_keys_present(self):
        result = compute_itl_stats([0.0, 5.0, 10.0])
        expected_keys = {
            "p50_ms",
            "p90_ms",
            "p95_ms",
            "p99_ms",
            "mean_ms",
            "min_ms",
            "max_ms",
        }
        assert set(result.keys()) == expected_keys
