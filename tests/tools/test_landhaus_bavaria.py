"""Unit tests for LandhausBavariaConnector."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

import openjarvis.tools.landhaus_bavaria as lb_module
from openjarvis.tools.landhaus_bavaria import LandhausBavariaConnector

_WEBSITE_TEST_URL = "https://test.landhaus.example"


# ---------------------------------------------------------------------------
# health()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_all_up():
    """All four configured sources return healthy responses."""
    proxy_url = "http://proxy.test"
    ical_url = "http://ical.test/feed.ics"
    vercel_token = "token123"
    project_id = "proj123"

    with (
        respx.mock,
        patch.object(lb_module, "_WEBSITE_URL", _WEBSITE_TEST_URL),
        patch.object(lb_module, "_ICAL_URL", ical_url),
        patch.object(lb_module, "_VERCEL_TOKEN", vercel_token),
        patch.dict(
            os.environ,
            {"DESKLINE_PROXY_URL": proxy_url, "VERCEL_PROJECT_ID": project_id},
            clear=False,
        ),
    ):
        respx.get(_WEBSITE_TEST_URL).mock(
            return_value=httpx.Response(200, text="<html></html>")
        )
        respx.get(f"{proxy_url}/health").mock(return_value=httpx.Response(200))
        respx.get(ical_url).mock(return_value=httpx.Response(200, text="BEGIN:VCALENDAR"))
        respx.get(
            "https://api.vercel.com/v6/deployments",
            params={"projectId": project_id, "limit": 1},
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "deployments": [
                        {"state": "READY", "url": "https://app.vercel.com"}
                    ]
                },
            )
        )

        connector = LandhausBavariaConnector()
        result = await connector.health()
        await connector.close()

    assert result["website"] == {"status": "up", "status_code": 200}
    assert result["deskline"] == {"status": "up"}
    assert result["ical"] == {"status": "up", "content_length": len("BEGIN:VCALENDAR")}
    assert result["vercel"] == {
        "status": "up",
        "latest_state": "READY",
        "latest_url": "https://app.vercel.com",
    }


@pytest.mark.asyncio
async def test_health_demo_when_not_configured():
    """Missing environment variables yield 'demo' data for optional sources."""
    with (
        respx.mock,
        patch.object(lb_module, "_WEBSITE_URL", _WEBSITE_TEST_URL),
        patch.object(lb_module, "_ICAL_URL", None),
        patch.object(lb_module, "_VERCEL_TOKEN", None),
        patch.dict(os.environ, {"DESKLINE_PROXY_URL": ""}, clear=False),
    ):
        respx.get(_WEBSITE_TEST_URL).mock(
            return_value=httpx.Response(200, text="ok")
        )

        connector = LandhausBavariaConnector()
        result = await connector.health()
        await connector.close()

    assert result["website"] == {"status": "up", "status_code": 200}
    assert result["deskline"]["status"] == "demo"
    assert result["deskline"]["rooms_total"] == 12
    assert result["ical"]["status"] == "demo"
    assert result["ical"]["bookings_count"] == 23
    assert result["vercel"]["status"] == "demo"
    assert result["vercel"]["deployment_state"] == "READY"


@pytest.mark.asyncio
async def test_health_down_on_errors():
    """Network and HTTP errors are caught and reported as 'down' with an error message."""
    proxy_url = "http://proxy.test"
    ical_url = "http://ical.test/feed.ics"
    vercel_token = "token123"
    project_id = "proj123"

    with (
        respx.mock,
        patch.object(lb_module, "_WEBSITE_URL", _WEBSITE_TEST_URL),
        patch.object(lb_module, "_ICAL_URL", ical_url),
        patch.object(lb_module, "_VERCEL_TOKEN", vercel_token),
        patch.dict(
            os.environ,
            {"DESKLINE_PROXY_URL": proxy_url, "VERCEL_PROJECT_ID": project_id},
            clear=False,
        ),
    ):
        respx.get(_WEBSITE_TEST_URL).mock(
            side_effect=httpx.ConnectTimeout("Connection timed out")
        )
        respx.get(f"{proxy_url}/health").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        respx.get(ical_url).mock(side_effect=httpx.ReadTimeout("Read timed out"))
        respx.get(
            "https://api.vercel.com/v6/deployments",
            params={"projectId": project_id, "limit": 1},
        ).mock(return_value=httpx.Response(500, text="not json"))

        connector = LandhausBavariaConnector()
        result = await connector.health()
        await connector.close()

    assert result["website"]["status"] == "down"
    assert "Connection timed out" in result["website"]["error"]

    assert result["deskline"]["status"] == "down"
    assert "Connection refused" in result["deskline"]["error"]

    assert result["ical"]["status"] == "down"
    assert "Read timed out" in result["ical"]["error"]

    assert result["vercel"]["status"] == "down"
    assert "error" in result["vercel"]


# ---------------------------------------------------------------------------
# room_availability()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_availability_success():
    """Successful availability query returns the deskline JSON payload."""
    proxy_url = "http://proxy.test"
    payload = {"rooms": [{"id": "double", "available": True}]}

    with (
        respx.mock,
        patch.dict(os.environ, {"DESKLINE_PROXY_URL": proxy_url}, clear=False),
    ):
        respx.get(
            f"{proxy_url}/availability",
            params={"from": "2024-06-01", "to": "2024-06-07"},
        ).mock(return_value=httpx.Response(200, json=payload))

        connector = LandhausBavariaConnector()
        result = await connector.room_availability("2024-06-01", "2024-06-07")
        await connector.close()

    assert result == payload


@pytest.mark.asyncio
async def test_room_availability_missing_proxy():
    """Missing DESKLINE_PROXY_URL yields a clear configuration error."""
    with patch.dict(os.environ, {"DESKLINE_PROXY_URL": ""}, clear=False):
        connector = LandhausBavariaConnector()
        result = await connector.room_availability("2024-06-01", "2024-06-07")
        await connector.close()

    assert result == {"error": "DESKLINE_PROXY_URL not configured"}


@pytest.mark.asyncio
async def test_room_availability_503_error():
    """A 503 response from the proxy is surfaced as an error dict."""
    proxy_url = "http://proxy.test"

    with (
        respx.mock,
        patch.dict(os.environ, {"DESKLINE_PROXY_URL": proxy_url}, clear=False),
    ):
        respx.get(
            f"{proxy_url}/availability",
            params={"from": "2024-06-01", "to": "2024-06-07"},
        ).mock(return_value=httpx.Response(503, text="Service Unavailable"))

        connector = LandhausBavariaConnector()
        result = await connector.room_availability("2024-06-01", "2024-06-07")
        await connector.close()

    assert "error" in result
    assert "503" in result["error"] or "Service Unavailable" in result["error"]


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close():
    """close() invokes aclose on the underlying httpx client."""
    connector = LandhausBavariaConnector()
    connector._client.aclose = AsyncMock()

    await connector.close()

    connector._client.aclose.assert_awaited_once()
