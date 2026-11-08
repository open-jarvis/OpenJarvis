"""Inter-token latency percentile computation."""

from __future__ import annotations

import statistics


def compute_itl_stats(token_timestamps: list[float]) -> dict:
    """Compute ITL statistics from token arrival timestamps (in ms).

    Returns dict with p50_ms, p90_ms, p95_ms, p99_ms, mean_ms, min_ms, max_ms.
    """
    if len(token_timestamps) < 2:
        return {
            "p50_ms": 0,
            "p90_ms": 0,
            "p95_ms": 0,
            "p99_ms": 0,
            "mean_ms": 0,
            "min_ms": 0,
            "max_ms": 0,
        }

    # Compute inter-token latencies
    itls = [
        token_timestamps[i] - token_timestamps[i - 1]
        for i in range(1, len(token_timestamps))
    ]
    itls.sort()

    def percentile(data: list[float], p: float) -> float:
        k = (len(data) - 1) * p
        f = int(k)
        c = f + 1
        if c >= len(data):
            return data[-1]
        return data[f] + (k - f) * (data[c] - data[f])

    return {
        "p50_ms": percentile(itls, 0.50),
        "p90_ms": percentile(itls, 0.90),
        "p95_ms": percentile(itls, 0.95),
        "p99_ms": percentile(itls, 0.99),
        "mean_ms": statistics.mean(itls),
        "min_ms": min(itls),
        "max_ms": max(itls),
    }
