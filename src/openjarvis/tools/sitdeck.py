"""SitDeck connector and tool for OpenJarvis agents.

Queries SitDeck's public read-only APIs:
- /api/sitdeck/widgets
- /api/sitdeck/data-sources
- /api/sitdeck/map-capabilities
- /api/sitdeck/map-types
- /api/sitdeck/plans
- /api/sitdeck/customer-count
- /api/content

No credentials are required; all endpoints are public and unauthenticated.
A demo mode returns synthetic data when the real API is unreachable.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
from typing import Any, Dict

import httpx

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_SITDECK_BASE_URL = os.environ.get("SITDECK_API_URL", "https://sitdeck.com")
_SITDECK_DEMO_MODE = os.environ.get("SITDECK_DEMO", "false").lower() in {"1", "true", "yes"}
_SITDECK_TIMEOUT_SECONDS = 15.0
_SITDECK_USER_AGENT = "OpenJarvis-SitDeckTool/1.0"

_SITDECK_ENDPOINTS = {
    "widgets": "/api/sitdeck/widgets",
    "data_sources": "/api/sitdeck/data-sources",
    "map_capabilities": "/api/sitdeck/map-capabilities",
    "map_types": "/api/sitdeck/map-types",
    "plans": "/api/sitdeck/plans",
    "customer_count": "/api/sitdeck/customer-count",
    "content": "/api/content",
}

_DEMO_DATA: Dict[str, Any] = {
    "widgets": {
        "totalWidgets": 12,
        "totalMapOverlays": 4,
        "widgetCategories": ["analytics", "map", "status", "alerts"],
    },
    "data_sources": {
        "totalDataSources": 8,
        "summary": {"online": 6, "errored": 1, "onDemand": 1},
    },
    "map_capabilities": {
        "summary": {"totalLayers": 24, "totalMapTypes": 6, "layerGroups": 5, "globe3D": 1},
    },
    "map_types": {
        "totalMapTypes": 6,
        "summary": {"vectorMaps": 4, "nonMercatorProjections": 2, "globe3D": 1},
    },
    "plans": {
        "totalPlans": 3,
        "plans": [
            {"id": "plan-1", "name": "Standard Geospatial"},
            {"id": "plan-2", "name": "Enterprise Operations"},
            {"id": "plan-3", "name": "Public Dashboard"},
        ],
    },
    "customer_count": {"count": 1428},
    "content": [
        {"id": 1, "section": "hero", "key": "headline", "content": "Geospatial intelligence made simple."},
        {"id": 2, "section": "features", "key": "maps", "content": "Interactive map layers with real-time updates."},
        {"id": 3, "section": "features", "key": "widgets", "content": "Embed live widgets on any page."},
        {"id": 4, "section": "pricing", "key": "starter", "content": "Free for public dashboards."},
        {"id": 5, "section": "contact", "key": "email", "content": "hello@sitdeck.example"},
    ],
}


_shared_client: httpx.AsyncClient | None = None


def _shared_sitdeck_client() -> httpx.AsyncClient:
    """Return the shared httpx client for SitDeck calls, creating it lazily."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=_SITDECK_TIMEOUT_SECONDS,
            follow_redirects=False,
            headers={"User-Agent": _SITDECK_USER_AGENT},
        )
    return _shared_client


def _shutdown_shared_client() -> None:
    global _shared_client
    client = _shared_client
    if client is not None and not client.is_closed:
        try:
            asyncio.run(client.aclose())
        except Exception:
            pass
    _shared_client = None


atexit.register(_shutdown_shared_client)


class SitDeckConnector:
    """Lightweight connector for SitDeck public APIs."""

    def __init__(
        self,
        base_url: str = _SITDECK_BASE_URL,
        client: httpx.AsyncClient | None = None,
        demo: bool = _SITDECK_DEMO_MODE,
    ) -> None:
        validated_url = _validate_base_url(base_url)
        self._base_url = validated_url.rstrip("/")
        self._client = client or _shared_sitdeck_client()
        self._close_client = client is not None
        self._demo = demo

    async def health(self) -> Dict[str, Any]:
        """Probe all known public endpoints and return aggregate status."""
        if self._demo:
            return self._demo_health()

        results: Dict[str, Any] = {}
        total_up = 0

        for name, path in _SITDECK_ENDPOINTS.items():
            url = f"{self._base_url}{path}"
            try:
                response = await self._client.get(url)
                status = "up" if response.status_code == 200 else "degraded"
                if response.status_code == 200:
                    total_up += 1
                results[name] = {
                    "status": status,
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
                    "size": len(response.content),
                }
            except Exception as exc:
                logger.error("SitDeck health probe failed for %s: %s", url, exc)
                results[name] = {"status": "down", "error": str(exc)}

        if self._should_demo_fallback(results):
            return self._demo_health()

        if total_up == len(_SITDECK_ENDPOINTS):
            overall = "up"
        elif total_up > 0:
            overall = "degraded"
        else:
            overall = "down"
        return {
            "status": overall,
            "sources": results,
            "total_up": total_up,
            "total_endpoints": len(_SITDECK_ENDPOINTS),
        }

    def _should_demo_fallback(self, results: Dict[str, Any]) -> bool:
        """Return True if every endpoint is down due to DNS/connection issues."""
        if not results:
            return False
        for meta in results.values():
            if meta.get("status") == "up":
                return False
            error = meta.get("error", "")
            if "nodename nor servname" not in error and "NXDOMAIN" not in error and "getaddrinfo" not in error:
                return False
        return True

    def _demo_health(self) -> Dict[str, Any]:
        """Return synthetic health status for demo/offline mode."""
        sources = {
            name: {
                "status": "demo",
                "status_code": 200,
                "content_type": "application/json",
                "size": len(json.dumps(_DEMO_DATA.get(name, {}))),
            }
            for name in _SITDECK_ENDPOINTS
        }
        return {
            "status": "demo",
            "sources": sources,
            "total_up": len(_SITDECK_ENDPOINTS),
            "total_endpoints": len(_SITDECK_ENDPOINTS),
            "demo": True,
        }

    async def fetch_endpoint(self, name: str) -> Dict[str, Any]:
        """Fetch and parse a single SitDeck endpoint by key."""
        path = _SITDECK_ENDPOINTS.get(name)
        if path is None:
            return {"error": f"Unknown endpoint: {name}"}

        if self._demo:
            return self._demo_endpoint(name)

        url = f"{self._base_url}{path}"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            try:
                data = response.json()
            except Exception:
                data = {"raw": response.text}
            return {"endpoint": name, "status_code": response.status_code, "data": data}
        except httpx.HTTPStatusError as exc:
            logger.error("SitDeck endpoint %s returned HTTP error: %s", name, exc)
            return {"endpoint": name, "error": f"HTTP {exc.response.status_code}"}
        except Exception as exc:
            logger.error("SitDeck endpoint %s fetch failed: %s", name, exc)
            if self._should_demo_for_error(str(exc)):
                return self._demo_endpoint(name)
            return {"endpoint": name, "error": str(exc)}

    def _should_demo_for_error(self, error: str) -> bool:
        """Return True if the error is a DNS/connection issue worth demo-fallback."""
        return "nodename nor servname" in error or "NXDOMAIN" in error or "getaddrinfo" in error

    def _demo_endpoint(self, name: str) -> Dict[str, Any]:
        """Return synthetic data for a single endpoint in demo mode."""
        data = _DEMO_DATA.get(name, {})
        return {"endpoint": name, "status_code": 200, "data": data, "demo": True}

    async def close(self) -> None:
        if self._close_client:
            await self._client.aclose()


def _validate_base_url(url: str) -> str:
    """Reject non-HTTPS or non-sitdeck base URLs to limit SSRF surface."""
    allowed_hosts = {"sitdeck.com", "www.sitdeck.com"}
    try:
        parsed = httpx.URL(url)
    except Exception as exc:
        raise ValueError(f"Invalid SitDeck base URL: {url}") from exc
    if parsed.scheme != "https":
        raise ValueError(f"SitDeck base URL must use HTTPS: {url}")
    host = parsed.host.lower()
    if host not in allowed_hosts and not host.endswith(".test") and not _SITDECK_DEMO_MODE:
        raise ValueError(f"SitDeck base URL host not allowed: {host}")
    return url


@ToolRegistry.register("sitdeck")
class SitDeckTool(BaseTool):
    """Registered tool wrapper for agent integration with SitDeck."""

    tool_id = "sitdeck"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="sitdeck",
            description=(
                "Query SitDeck's public read-only APIs. "
                "Actions: 'health' (probe all endpoints), "
                "'widgets', 'data_sources', 'map_capabilities', "
                "'map_types', 'plans', 'customer_count', 'content'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "health",
                            "widgets",
                            "data_sources",
                            "map_capabilities",
                            "map_types",
                            "plans",
                            "customer_count",
                            "content",
                        ],
                        "description": (
                            "Which SitDeck endpoint or aggregate operation "
                            "to perform."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="domain",
            timeout_seconds=60.0,
        )

    def execute(self, action: str = "", **kwargs: Any) -> ToolResult:
        async def _async_work() -> ToolResult:
            connector = SitDeckConnector()
            try:
                if action == "health":
                    result = await connector.health()
                    return ToolResult(
                        tool_name="sitdeck",
                        content=json.dumps(result, default=str),
                        success=True,
                    )
                if action in _SITDECK_ENDPOINTS:
                    result = await connector.fetch_endpoint(action)
                    success = "error" not in result
                    return ToolResult(
                        tool_name="sitdeck",
                        content=json.dumps(result, default=str),
                        success=success,
                    )
                return ToolResult(
                    tool_name="sitdeck",
                    content=json.dumps({"error": f"Unknown action: {action}"}),
                    success=False,
                )
            finally:
                await connector.close()

        try:
            return asyncio.run(_async_work())
        except RuntimeError as exc:
            logger.error("SitDeck tool execute failed: %s", exc)
            _async_error = "SitDeck tool cannot be called from an active async context"
            return ToolResult(
                tool_name="sitdeck",
                content=json.dumps({"error": _async_error}),
                success=False,
            )
        except Exception as exc:
            logger.error("SitDeck tool execute failed: %s", exc)
            return ToolResult(
                tool_name="sitdeck",
                content=json.dumps({"error": "SitDeck request failed"}),
                success=False,
            )


__all__ = ["SitDeckConnector", "SitDeckTool"]
