"""Tests for MiningTelemetryCollector, shipped in v1 but unwired."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_collector_collect_once_returns_stats(written_sidecar):
    from openjarvis.mining._collector import MiningTelemetryCollector

    sample = (
        "pearl_gateway_shares_submitted_total 50\n"
        "pearl_gateway_shares_accepted_total 49\n"
    )
    with patch("openjarvis.mining._collector.httpx.get") as get:
        get.return_value.status_code = 200
        get.return_value.text = sample
        store = MagicMock()
        collector = MiningTelemetryCollector(
            sidecar_path=written_sidecar,
            telemetry_store=store,
            interval_s=0.05,
        )

        stats = await collector.collect_once()

    assert stats.shares_submitted == 50
    assert stats.shares_accepted == 49
    get.assert_called_once_with("http://127.0.0.1:8339/metrics", timeout=5.0)


@pytest.mark.asyncio
async def test_collector_run_loop_writes_to_store_then_stops(written_sidecar):
    from openjarvis.mining._collector import MiningTelemetryCollector

    sample = "pearl_gateway_shares_submitted_total 1\n"
    with patch("openjarvis.mining._collector.httpx.get") as get:
        get.return_value.status_code = 200
        get.return_value.text = sample
        store = MagicMock()
        collector = MiningTelemetryCollector(
            sidecar_path=written_sidecar,
            telemetry_store=store,
            interval_s=0.01,
        )

        task = asyncio.create_task(collector.run())
        await asyncio.sleep(0.05)
        collector.stop()
        await asyncio.wait_for(task, timeout=1.0)

    assert store.record_mining_stats.call_count >= 1


@pytest.mark.asyncio
async def test_collector_handles_gateway_errors_gracefully(written_sidecar):
    from openjarvis.mining._collector import MiningTelemetryCollector

    with patch("openjarvis.mining._collector.httpx.get") as get:
        get.side_effect = ConnectionError("nope")
        store = MagicMock()
        collector = MiningTelemetryCollector(
            sidecar_path=written_sidecar,
            telemetry_store=store,
        )

        stats = await collector.collect_once()

    assert stats.last_error == "nope"
