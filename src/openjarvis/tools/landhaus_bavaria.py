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
from typing import Any, Dict, Optional

import httpx

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

        # Deskline proxy (if configured)
        if os.environ.get("DESKLINE_PROXY_URL"):
            try:
                resp = await self._client.get(os.environ["DESKLINE_PROXY_URL"] + "/health")
                results["deskline"] = {"status": "up" if resp.status_code == 200 else "degraded"}
            except Exception as exc:
                results["deskline"] = {"status": "down", "error": str(exc)}
        else:
            results["deskline"] = {"status": "not_configured"}

        # iCal sync (if configured)
        if _ICAL_URL:
            try:
                resp = await self._client.get(_ICAL_URL)
                results["ical"] = {"status": "up" if resp.status_code == 200 else "degraded", "content_length": len(resp.text)}
            except Exception as exc:
                results["ical"] = {"status": "down", "error": str(exc)}
        else:
            results["ical"] = {"status": "not_configured"}

        # Vercel (if token available)
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
            results["vercel"] = {"status": "not_configured"}

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
class LandhausBavariaTool:
    """Stub-compatible tool wrapper for agent integration."""

    name = "landhaus_bavaria"
    description = "Query Landhaus Bavaria data sources (website, deskline, iCal, Vercel)."

    async def run(self, action: str, **kwargs: Any) -> Dict[str, Any]:
        connector = LandhausBavariaConnector()
        try:
            if action == "health":
                return await connector.health()
            if action == "room_availability":
                return await connector.room_availability(
                    kwargs.get("date_from", ""), kwargs.get("date_to", "")
                )
            return {"error": f"Unknown action: {action}"}
        finally:
            await connector.close()
