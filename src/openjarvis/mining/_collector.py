# src/openjarvis/mining/_collector.py
"""Background poller for mining telemetry.

Shipped in v1 but not wired into the gateway daemon. v1's status command
reads on demand; v1.x can register this collector as a periodic daemon task
without changing the collector contract.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from openjarvis.mining._metrics import parse_gateway_metrics
from openjarvis.mining._stubs import MiningStats, Sidecar

log = logging.getLogger(__name__)


class MiningTelemetryCollector:
    """Poll Pearl gateway metrics and write ``MiningStats`` to a store.

    ``telemetry_store`` is duck-typed and must implement
    ``record_mining_stats(stats: MiningStats) -> None``.
    """

    def __init__(
        self,
        sidecar_path: Path,
        telemetry_store: Any,
        interval_s: float = 30.0,
    ) -> None:
        self._sidecar_path = sidecar_path
        self._store = telemetry_store
        self._interval_s = interval_s
        self._stop = False

    async def collect_once(self) -> MiningStats:
        sidecar = Sidecar.read(self._sidecar_path)
        if sidecar is None:
            return MiningStats(provider_id="unknown")

        provider_id = sidecar.get("provider", "unknown")
        url = sidecar.get("gateway_metrics_url")
        if not url:
            return MiningStats(provider_id=provider_id)

        try:
            resp = httpx.get(f"{url.rstrip('/')}/metrics", timeout=5.0)
            if resp.status_code != 200:
                return MiningStats(
                    provider_id=provider_id,
                    last_error=f"gateway HTTP {resp.status_code}",
                )
            return parse_gateway_metrics(resp.text, provider_id=provider_id)
        except Exception as exc:  # noqa: BLE001 - collector must not crash daemon
            message = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
            return MiningStats(provider_id=provider_id, last_error=message)

    async def run(self) -> None:
        while not self._stop:
            try:
                stats = await self.collect_once()
                self._store.record_mining_stats(stats)
            except Exception as exc:  # noqa: BLE001 - keep background task alive
                log.warning("MiningTelemetryCollector tick error: %s", exc)

            try:
                await asyncio.sleep(self._interval_s)
            except asyncio.CancelledError:
                break

    def stop(self) -> None:
        self._stop = True
