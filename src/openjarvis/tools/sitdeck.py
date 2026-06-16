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
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_SITDECK_BASE_URL = "https://sitdeck.com"
_SITDECK_TIMEOUT_SECONDS = 15.0

_SITDECK_ENDPOINTS = {
    "widgets": "/api/sitdeck/widgets",
    "data_sources": "/api/sitdeck/data-sources",
    "map_capabilities": "/api/sitdeck/map-capabilities",
    "map_types": "/api/sitdeck/map-types",
    "plans": "/api/sitdeck/plans",
    "customer_count": "/api/sitdeck/customer-count",
    "content": "/api/content",
}


_shared_client: httpx.AsyncClient | None = None


def _shared_sitdeck_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=_SITDECK_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "OpenJarvis-SitDeckTool/1.0"},
        )
    return _shared_client

class SitDeckConnector:
    """Lightweight connector for SitDeck public APIs."""

    def __init__(
        self,
        base_url: str = _SITDECK_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or _shared_sitdeck_client()
        self._owns_client = client is not None

    async def health(self) -> Dict[str, Any]:
        """Probe all known public endpoints and return aggregate status."""
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

    async def fetch_endpoint(self, name: str) -> Dict[str, Any]:
        """Fetch and parse a single SitDeck endpoint by key."""
        path = _SITDECK_ENDPOINTS.get(name)
        if path is None:
            return {"error": f"Unknown endpoint: {name}"}

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
            return {"endpoint": name, "error": str(exc)}

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


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
        import asyncio
        import json

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
        except Exception as exc:
            logger.error("SitDeck tool execute failed: %s", exc)
            return ToolResult(
                tool_name="sitdeck",
                content=json.dumps({"error": str(exc)}),
                success=False,
            )


__all__ = ["SitDeckConnector", "SitDeckTool"]
