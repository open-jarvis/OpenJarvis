"""LandhausBavariaConnector — read-only health and data access tool.

Queries approved external systems for the Landhaus Bavaria domain:
- Deskline WebClient (room availability)
- Booking.com iCal (sync status)
- Vercel API (deployment status)
- Website health (landhausbavaria.de)

Credentials are read from environment variables; they are never logged.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

import httpx

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_DESKLINE_BASE = os.environ.get("DESKLINE_BASE_URL", "https://webclient4.deskline.net")
_VERCEL_TOKEN = os.environ.get("VERCEL_API_TOKEN")
_ICAL_URL = os.environ.get("BOOKINGCOM_ICAL_URL")
_WEBSITE_URL = os.environ.get("LANDHAUS_WEBSITE", "https://www.landhausbavaria.de")


class LandhausBavariaConnector:
    """Lightweight connector for approved Landhaus Bavaria data sources."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=15.0)

    async def health(self) -> Dict[str, Any]:
        """Run health checks against all configured data sources."""
        results: Dict[str, Any] = {}

        # Website health
        try:
            resp = await self._client.get(_WEBSITE_URL, follow_redirects=True)
            results["website"] = {"status": "up" if resp.status_code == 200 else "degraded", "status_code": resp.status_code}
        except Exception as exc:
            results["website"] = {"status": "down", "error": str(exc)}

        # Deskline proxy
        if os.environ.get("DESKLINE_PROXY_URL"):
            try:
                resp = await self._client.get(os.environ["DESKLINE_PROXY_URL"] + "/health")
                results["deskline"] = {"status": "up" if resp.status_code == 200 else "degraded"}
            except Exception as exc:
                results["deskline"] = {"status": "down", "error": str(exc)}
        else:
            # Demo data so the panel always shows meaningful state
            results["deskline"] = {
                "status": "demo",
                "rooms_total": 12,
                "rooms_occupied": 8,
                "rooms_available": 4,
                "next_checkin": "2026-06-15",
            }

        # iCal sync
        if _ICAL_URL:
            try:
                resp = await self._client.get(_ICAL_URL)
                results["ical"] = {"status": "up" if resp.status_code == 200 else "degraded", "content_length": len(resp.text)}
            except Exception as exc:
                results["ical"] = {"status": "down", "error": str(exc)}
        else:
            results["ical"] = {
                "status": "demo",
                "last_sync": "2026-06-14T10:00:00Z",
                "bookings_count": 23,
                "channels": ["Booking.com"],
            }

        # Vercel
        if _VERCEL_TOKEN:
            try:
                resp = await self._client.get(
                    "https://api.vercel.com/v6/deployments",
                    headers={"Authorization": f"Bearer {_VERCEL_TOKEN}"},
                    params={"projectId": os.environ.get("VERCEL_PROJECT_ID"), "limit": 1},
                )
                data = resp.json()
                latest = data.get("deployments", [{}])[0]
                results["vercel"] = {
                    "status": "up",
                    "latest_state": latest.get("state", "unknown"),
                    "latest_url": latest.get("url"),
                }
            except Exception as exc:
                results["vercel"] = {"status": "down", "error": str(exc)}
        else:
            results["vercel"] = {
                "status": "demo",
                "deployment_state": "READY",
                "production_url": "https://www.landhausbavaria.de",
                "last_deploy": "2026-06-13T22:30:00Z",
            }

        return results

    async def room_availability(self, date_from: str, date_to: str) -> Dict[str, Any]:
        """Fetch room availability via Deskline proxy."""
        proxy = os.environ.get("DESKLINE_PROXY_URL")
        if not proxy:
            return {"error": "DESKLINE_PROXY_URL not configured"}

        try:
            resp = await self._client.get(
                f"{proxy}/availability",
                params={"from": date_from, "to": date_to},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Deskline availability query failed: %s", exc)
            return {"error": str(exc)}

    async def close(self) -> None:
        await self._client.aclose()


# Tool-adapter surface for the orchestrator
@ToolRegistry.register("landhaus_bavaria")
class LandhausBavariaTool(BaseTool):
    """Registered tool wrapper for agent integration."""

    tool_id = "landhaus_bavaria"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="landhaus_bavaria",
            description=(
                "Query Landhaus Bavaria data sources. "
                "Actions: 'health' (check all systems), "
                "'room_availability' (query Deskline for date range)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["health", "room_availability"],
                        "description": "Which operation to perform.",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD). Required for room_availability.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD). Required for room_availability.",
                    },
                },
                "required": ["action"],
            },
            category="domain",
            timeout_seconds=20.0,
        )

    def execute(self, action: str = "", **kwargs: Any) -> ToolResult:
        import asyncio
        import concurrent.futures

        async def _async_work():
            connector = LandhausBavariaConnector()
            try:
                if action == "health":
                    result = await connector.health()
                    return ToolResult(
                        tool_name="landhaus_bavaria",
                        content=str(result),
                        success=True,
                    )
                if action == "room_availability":
                    result = await connector.room_availability(
                        kwargs.get("date_from", ""),
                        kwargs.get("date_to", ""),
                    )
                    success = "error" not in result
                    return ToolResult(
                        tool_name="landhaus_bavaria",
                        content=str(result),
                        success=success,
                    )
                return ToolResult(
                    tool_name="landhaus_bavaria",
                    content=f"Unknown action: {action}",
                    success=False,
                )
            finally:
                await connector.close()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_async_work())
        # FastAPI/uvicorn already has an event loop in this thread;
        # asyncio.run() is forbidden here. Offload to a fresh thread.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, _async_work()).result(timeout=30)


__all__ = [
    "LandhausBavariaConnector",
    "LandhausBavariaTool",
]