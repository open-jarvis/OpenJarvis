"""Tests for VLLMMetricsScraper — Prometheus text format parsing."""

from __future__ import annotations

from unittest.mock import patch

from openjarvis.telemetry.vllm_metrics import (
    VLLMMetrics,
    VLLMMetricsScraper,
    _parse_gauge,
    _parse_histogram_buckets,
    _percentile_from_buckets,
)

# ---------------------------------------------------------------------------
# Sample Prometheus text fixtures
# ---------------------------------------------------------------------------

SAMPLE_METRICS = """\
# HELP vllm:time_to_first_token_seconds Histogram of TTFT in seconds.
# TYPE vllm:time_to_first_token_seconds histogram
vllm:time_to_first_token_seconds_bucket{le="0.01"} 5
vllm:time_to_first_token_seconds_bucket{le="0.025"} 15
vllm:time_to_first_token_seconds_bucket{le="0.05"} 40
vllm:time_to_first_token_seconds_bucket{le="0.1"} 80
vllm:time_to_first_token_seconds_bucket{le="0.25"} 95
vllm:time_to_first_token_seconds_bucket{le="0.5"} 100
vllm:time_to_first_token_seconds_bucket{le="+Inf"} 100
vllm:time_to_first_token_seconds_sum 5.5
vllm:time_to_first_token_seconds_count 100
# HELP vllm:gpu_cache_usage_perc GPU KV-cache usage percentage.
# TYPE vllm:gpu_cache_usage_perc gauge
vllm:gpu_cache_usage_perc 0.42
# HELP vllm:e2e_request_latency_seconds Histogram of E2E request latency.
# TYPE vllm:e2e_request_latency_seconds histogram
vllm:e2e_request_latency_seconds_bucket{le="0.1"} 10
vllm:e2e_request_latency_seconds_bucket{le="0.5"} 50
vllm:e2e_request_latency_seconds_bucket{le="1.0"} 80
vllm:e2e_request_latency_seconds_bucket{le="2.5"} 95
vllm:e2e_request_latency_seconds_bucket{le="5.0"} 100
vllm:e2e_request_latency_seconds_bucket{le="+Inf"} 100
vllm:e2e_request_latency_seconds_sum 75.0
vllm:e2e_request_latency_seconds_count 100
# HELP vllm:num_requests_waiting Number of requests waiting in queue.
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting 3
"""


class TestVLLMMetricsDataclass:
    def test_defaults(self):
        m = VLLMMetrics()
        assert m.ttft_p50 == 0.0
        assert m.ttft_p95 == 0.0
        assert m.ttft_p99 == 0.0
        assert m.gpu_cache_usage_pct == 0.0
        assert m.e2e_latency_p50 == 0.0
        assert m.e2e_latency_p95 == 0.0
        assert m.queue_depth == 0.0

    def test_custom_values(self):
        m = VLLMMetrics(ttft_p50=0.05, gpu_cache_usage_pct=0.8)
        assert m.ttft_p50 == 0.05
        assert m.gpu_cache_usage_pct == 0.8


class TestParseHistogramBuckets:
    def test_parses_ttft_buckets(self):
        lines = SAMPLE_METRICS.splitlines()
        buckets, sum_val, count_val = _parse_histogram_buckets(
            lines, "vllm:time_to_first_token_seconds"
        )
        assert len(buckets) == 7
        assert sum_val == 5.5
        assert count_val == 100
        # First finite bucket
        assert buckets[0] == (0.01, 5.0)
        # Last finite bucket
        assert buckets[5] == (0.5, 100.0)

    def test_empty_lines(self):
        buckets, s, c = _parse_histogram_buckets([], "nonexistent")
        assert buckets == []
        assert s == 0.0
        assert c == 0.0

    def test_no_matching_metric(self):
        lines = SAMPLE_METRICS.splitlines()
        buckets, s, c = _parse_histogram_buckets(lines, "no_such_metric")
        assert buckets == []
        assert s == 0.0


class TestPercentileFromBuckets:
    def test_empty_buckets(self):
        assert _percentile_from_buckets([], 50) == 0.0

    def test_zero_count(self):
        buckets = [(0.1, 0.0), (0.5, 0.0)]
        assert _percentile_from_buckets(buckets, 50) == 0.0

    def test_median_interpolation(self):
        lines = SAMPLE_METRICS.splitlines()
        buckets, _, _ = _parse_histogram_buckets(
            lines, "vllm:time_to_first_token_seconds"
        )
        p50 = _percentile_from_buckets(buckets, 50)
        # 50th percentile: target = 50 out of 100
        # Bucket le=0.05 has 40, le=0.1 has 80
        # fraction = (50-40)/(80-40) = 0.25
        # result = 0.05 + 0.25 * (0.1-0.05) = 0.0625
        assert abs(p50 - 0.0625) < 1e-6

    def test_p95(self):
        lines = SAMPLE_METRICS.splitlines()
        buckets, _, _ = _parse_histogram_buckets(
            lines, "vllm:time_to_first_token_seconds"
        )
        p95 = _percentile_from_buckets(buckets, 95)
        # target = 95, bucket le=0.25 has 95 exactly
        # le=0.1 has 80, le=0.25 has 95
        # fraction = (95-80)/(95-80) = 1.0
        # result = 0.1 + 1.0 * (0.25 - 0.1) = 0.25
        assert abs(p95 - 0.25) < 1e-6


class TestParseGauge:
    def test_parses_gauge(self):
        lines = SAMPLE_METRICS.splitlines()
        val = _parse_gauge(lines, "vllm:gpu_cache_usage_perc")
        assert val == 0.42

    def test_missing_gauge(self):
        lines = SAMPLE_METRICS.splitlines()
        val = _parse_gauge(lines, "nonexistent_gauge")
        assert val == 0.0

    def test_queue_depth(self):
        lines = SAMPLE_METRICS.splitlines()
        val = _parse_gauge(lines, "vllm:num_requests_waiting")
        assert val == 3.0


class TestVLLMMetricsScraper:
    def test_parse_full_metrics(self):
        scraper = VLLMMetricsScraper("http://localhost:8000")
        metrics = scraper._parse(SAMPLE_METRICS)

        assert metrics.gpu_cache_usage_pct == 0.42
        assert metrics.queue_depth == 3.0
        assert metrics.ttft_p50 > 0
        assert metrics.ttft_p95 > 0
        assert metrics.ttft_p99 > 0
        assert metrics.e2e_latency_p50 > 0
        assert metrics.e2e_latency_p95 > 0

    def test_scrape_connection_error(self):
        scraper = VLLMMetricsScraper("http://localhost:99999")
        metrics = scraper.scrape()
        # Should return zeroed metrics, not raise
        assert metrics == VLLMMetrics()

    def test_scrape_success_with_mock(self):
        scraper = VLLMMetricsScraper("http://localhost:8000")

        class FakeResp:
            status_code = 200
            text = SAMPLE_METRICS

            def raise_for_status(self):
                pass

        target = "openjarvis.telemetry.vllm_metrics.httpx.get"
        with patch(target, return_value=FakeResp()):
            metrics = scraper.scrape()

        assert metrics.gpu_cache_usage_pct == 0.42
        assert metrics.queue_depth == 3.0
        assert metrics.ttft_p50 > 0

    def test_scrape_http_error(self):
        import httpx as _httpx

        scraper = VLLMMetricsScraper("http://localhost:8000")

        def raise_status_error(*args, **kwargs):
            request = _httpx.Request("GET", "http://localhost:8000/metrics")
            response = _httpx.Response(500, request=request)
            raise _httpx.HTTPStatusError(
                "Server Error", request=request, response=response
            )

        target = "openjarvis.telemetry.vllm_metrics.httpx.get"
        with patch(target, side_effect=raise_status_error):
            metrics = scraper.scrape()

        assert metrics == VLLMMetrics()

    def test_empty_response(self):
        scraper = VLLMMetricsScraper()
        metrics = scraper._parse("")
        assert metrics == VLLMMetrics()
