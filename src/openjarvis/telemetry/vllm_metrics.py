"""vLLM Prometheus metrics scraper — fetches and parses /metrics endpoint."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List, Tuple

import httpx

logger = logging.getLogger(__name__)


@dataclass
class VLLMMetrics:
    """Parsed vLLM performance metrics."""

    ttft_p50: float = 0.0
    ttft_p95: float = 0.0
    ttft_p99: float = 0.0
    gpu_cache_usage_pct: float = 0.0
    e2e_latency_p50: float = 0.0
    e2e_latency_p95: float = 0.0
    queue_depth: float = 0.0


def _parse_histogram_buckets(
    lines: List[str], metric_prefix: str
) -> Tuple[List[Tuple[float, float]], float, float]:
    """Parse Prometheus histogram buckets, sum, and count for a metric.

    Returns (buckets, sum_value, count_value) where buckets is a sorted
    list of (upper_bound, cumulative_count) pairs.
    """
    buckets: List[Tuple[float, float]] = []
    sum_value = 0.0
    count_value = 0.0

    for line in lines:
        line = line.strip()
        if line.startswith("#") or not line:
            continue

        if line.startswith(f"{metric_prefix}_bucket{{"):
            # Parse: metric_bucket{le="0.5"} 123
            try:
                le_start = line.index('le="') + 4
                le_end = line.index('"', le_start)
                le_str = line[le_start:le_end]
                bound = float(le_str) if le_str != "+Inf" else math.inf
                count_str = line.rsplit(None, 1)[-1]
                buckets.append((bound, float(count_str)))
            except (ValueError, IndexError) as exc:
                logger.debug("Failed to parse vLLM metric line: %s", exc)
                continue

        elif line.startswith(f"{metric_prefix}_sum "):
            try:
                sum_value = float(line.split()[-1])
            except (ValueError, IndexError) as exc:
                logger.debug("Failed to parse vLLM metric line: %s", exc)

        elif line.startswith(f"{metric_prefix}_count "):
            try:
                count_value = float(line.split()[-1])
            except (ValueError, IndexError) as exc:
                logger.debug("Failed to parse vLLM metric line: %s", exc)

    buckets.sort(key=lambda x: x[0])
    return buckets, sum_value, count_value


def _percentile_from_buckets(
    buckets: List[Tuple[float, float]], percentile: float
) -> float:
    """Estimate a percentile from Prometheus histogram buckets.

    Uses linear interpolation between bucket boundaries.
    """
    if not buckets:
        return 0.0

    total = buckets[-1][1] if buckets else 0.0
    if total == 0:
        return 0.0

    target = total * (percentile / 100.0)

    prev_bound = 0.0
    prev_count = 0.0
    for bound, count in buckets:
        if bound == math.inf:
            return prev_bound
        if count >= target:
            # Linear interpolation within this bucket
            if count == prev_count:
                return bound
            fraction = (target - prev_count) / (count - prev_count)
            return prev_bound + fraction * (bound - prev_bound)
        prev_bound = bound
        prev_count = count

    # Fallback: return last finite bound
    for bound, _ in reversed(buckets):
        if bound != math.inf:
            return bound
    return 0.0


def _parse_gauge(lines: List[str], metric_name: str) -> float:
    """Parse a Prometheus gauge value."""
    for line in lines:
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        if line.startswith(f"{metric_name} "):
            try:
                return float(line.split()[-1])
            except (ValueError, IndexError) as exc:
                logger.debug("Failed to parse vLLM metric line: %s", exc)
    return 0.0


class VLLMMetricsScraper:
    """Scrapes vLLM's Prometheus /metrics endpoint."""

    def __init__(self, host: str = "http://localhost:8000") -> None:
        self._host = host.rstrip("/")

    def scrape(self) -> VLLMMetrics:
        """Fetch and parse vLLM metrics. Returns zeroed metrics on error."""
        try:
            resp = httpx.get(f"{self._host}/metrics", timeout=5.0)
            resp.raise_for_status()
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
        ) as exc:
            logger.debug("Failed to fetch vLLM metrics: %s", exc)
            return VLLMMetrics()

        return self._parse(resp.text)

    def _parse(self, text: str) -> VLLMMetrics:
        """Parse Prometheus text format into VLLMMetrics."""
        lines = text.splitlines()

        # TTFT histogram
        ttft_buckets, _, _ = _parse_histogram_buckets(
            lines, "vllm:time_to_first_token_seconds"
        )
        ttft_p50 = _percentile_from_buckets(ttft_buckets, 50)
        ttft_p95 = _percentile_from_buckets(ttft_buckets, 95)
        ttft_p99 = _percentile_from_buckets(ttft_buckets, 99)

        # GPU cache usage (gauge)
        gpu_cache = _parse_gauge(lines, "vllm:gpu_cache_usage_perc")

        # E2E latency histogram
        e2e_buckets, _, _ = _parse_histogram_buckets(
            lines, "vllm:e2e_request_latency_seconds"
        )
        e2e_p50 = _percentile_from_buckets(e2e_buckets, 50)
        e2e_p95 = _percentile_from_buckets(e2e_buckets, 95)

        # Queue depth (gauge) — num_requests_waiting
        queue_depth = _parse_gauge(lines, "vllm:num_requests_waiting")

        return VLLMMetrics(
            ttft_p50=ttft_p50,
            ttft_p95=ttft_p95,
            ttft_p99=ttft_p99,
            gpu_cache_usage_pct=gpu_cache,
            e2e_latency_p50=e2e_p50,
            e2e_latency_p95=e2e_p95,
            queue_depth=queue_depth,
        )


__all__ = ["VLLMMetrics", "VLLMMetricsScraper"]
