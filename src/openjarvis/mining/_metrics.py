# src/openjarvis/mining/_metrics.py
"""Pearl/vLLM Prometheus → MiningStats adapter.

The original v1 design expected Pearl gateway metrics on ``:8339/metrics``.
The live Pearl miner currently exposes the vLLM Prometheus endpoint on
``:8000/metrics`` instead, while the gateway listens on a Unix socket for miner
RPC. Keep both parsers here so ``jarvis mine status`` can report a healthy
runtime even when share/block counters are not exposed by the gateway yet.

If Pearl renames metrics, change the ``PROM_*`` constants here — that's the
only place the metric names live.
"""

from __future__ import annotations

import logging
import time

from openjarvis.mining._stubs import MiningStats

log = logging.getLogger(__name__)

# Pearl metric names. See spec §8.2 — verify against the fixture committed
# in tests/mining/fixtures/gateway_metrics_sample.txt.
PROM_SHARES_SUBMITTED = "pearl_gateway_shares_submitted_total"
PROM_SHARES_ACCEPTED = "pearl_gateway_shares_accepted_total"
PROM_BLOCKS_FOUND = "pearl_gateway_blocks_found_total"
PROM_LAST_SHARE_TS = "pearl_gateway_last_share_timestamp"
PROM_ERRORS_TOTAL = "pearl_gateway_errors_total"
PROM_PROCESS_START = "process_start_time_seconds"


def _parse_simple_metric(text: str, name: str) -> float | None:
    """Find the first occurrence of a simple, label-less metric.

    Lines look like ``metric_name 12345`` or ``metric_name{label="x"} 12345``.
    For the v1 adapter we ignore labels and take the first non-comment match.
    """
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        # Split on the first whitespace; the metric name is everything up to
        # an optional `{...}` label block.
        head, _, value = line.partition(" ")
        head = head.split("{", 1)[0]
        if head == name:
            try:
                return float(value.strip())
            except ValueError:
                return None
    return None


def parse_gateway_metrics(text: str, *, provider_id: str) -> MiningStats:
    """Convert a Prometheus exposition payload into a ``MiningStats``."""
    submitted = _parse_simple_metric(text, PROM_SHARES_SUBMITTED) or 0.0
    accepted = _parse_simple_metric(text, PROM_SHARES_ACCEPTED) or 0.0
    blocks = _parse_simple_metric(text, PROM_BLOCKS_FOUND) or 0.0
    last_share_ts = _parse_simple_metric(text, PROM_LAST_SHARE_TS)
    errors = _parse_simple_metric(text, PROM_ERRORS_TOTAL) or 0.0
    proc_start = _parse_simple_metric(text, PROM_PROCESS_START)

    uptime = 0.0
    if proc_start is not None:
        uptime = max(0.0, time.time() - proc_start)

    last_error: str | None = None
    if errors > 0:
        last_error = f"{int(errors)} gateway errors observed"

    return MiningStats(
        provider_id=provider_id,
        shares_submitted=int(submitted),
        shares_accepted=int(accepted),
        blocks_found=int(blocks),
        # Hashrate as a derived rate is not meaningful from a single snapshot;
        # the v1.x persistent collector will compute it. v1 leaves it 0.
        hashrate=0.0,
        uptime_seconds=uptime,
        last_share_at=last_share_ts,
        last_error=last_error,
    )


def parse_vllm_metrics(text: str, *, provider_id: str) -> MiningStats:
    """Convert vLLM Prometheus metrics into best-effort mining runtime stats.

    vLLM does not expose Pearl share/block counters, but its metrics endpoint
    proves the mining-backed inference server is alive and can provide uptime.
    """
    proc_start = _parse_simple_metric(text, "process_start_time_seconds")
    uptime = 0.0
    if proc_start is not None:
        uptime = max(0.0, time.time() - proc_start)

    return MiningStats(provider_id=provider_id, uptime_seconds=uptime)
