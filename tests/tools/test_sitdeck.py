"""Tests for the SitDeck tool and connector."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from openjarvis.tools.sitdeck import SitDeckConnector, SitDeckTool


@pytest.fixture
def connector():
    return SitDeckConnector(base_url="https://sitdeck.test")


def _mock_response(status_code: int = 200, json_data: dict | None = None):
    response = AsyncMock()
    response.status_code = status_code
    response.content = str(json_data or {}).encode()
    response.json = Mock(return_value=json_data or {})
    response.headers = {"content-type": "application/json"}
    response.text = str(json_data or {})
    response.is_closed = False
    if status_code >= 400:
        response.raise_for_status = Mock(side_effect=Exception(f"HTTP {status_code}"))
    else:
        response.raise_for_status = Mock()
    return response


@pytest.mark.anyio
async def test_health_reports_all_endpoints(connector: SitDeckConnector):
    response = _mock_response(200, {"ok": True})
    with patch("httpx.AsyncClient.get", return_value=response) as mock_get:
        result = await connector.health()
        await connector.close()

    assert result["status"] == "up"
    assert result["total_up"] == result["total_endpoints"]
    assert all(source["status"] == "up" for source in result["sources"].values())
    assert mock_get.call_count == 7


@pytest.mark.anyio
async def test_health_marks_degraded_on_failure(connector: SitDeckConnector):
    ok_response = _mock_response(200, {})
    fail_response = _mock_response(500, {})

    async def _side_effect(url: str, **_kwargs):
        if "/data-sources" in url:
            return fail_response
        return ok_response

    with patch("httpx.AsyncClient.get", side_effect=_side_effect):
        result = await connector.health()
        await connector.close()

    assert result["status"] == "degraded"
    assert result["sources"]["data_sources"]["status"] == "degraded"
    assert result["total_up"] == result["total_endpoints"] - 1


@pytest.mark.anyio
async def test_fetch_endpoint_returns_json(connector: SitDeckConnector):
    response = _mock_response(200, {"widgets": [{"id": "w1"}]})
    with patch("httpx.AsyncClient.get", return_value=response):
        result = await connector.fetch_endpoint("widgets")
        await connector.close()

    assert result["endpoint"] == "widgets"
    assert result["status_code"] == 200
    assert result["data"]["widgets"][0]["id"] == "w1"


@pytest.mark.anyio
async def test_fetch_endpoint_reports_http_error(connector: SitDeckConnector):
    response = _mock_response(500, {})
    with patch("httpx.AsyncClient.get", return_value=response):
        result = await connector.fetch_endpoint("widgets")
        await connector.close()

    assert "error" in result


@pytest.mark.anyio
async def test_fetch_endpoint_reports_error_for_unknown_key(
    connector: SitDeckConnector,
):
    result = await connector.fetch_endpoint("not_a_key")
    await connector.close()
    assert "error" in result


def test_tool_spec_has_expected_actions():
    tool = SitDeckTool()
    spec = tool.spec
    assert spec.name == "sitdeck"
    assert "health" in spec.parameters["properties"]["action"]["enum"]
    assert "widgets" in spec.parameters["properties"]["action"]["enum"]


def test_tool_execute_health_returns_success():
    response = _mock_response(200, {"ok": True})
    with patch("httpx.AsyncClient.get", return_value=response):
        tool = SitDeckTool()
        result = tool.execute(action="health")

    assert result.success is True
    assert result.tool_name == "sitdeck"
    data = json.loads(result.content)
    assert data["status"] == "up"


def test_tool_execute_widgets_returns_success():
    response = _mock_response(200, {"widgets": []})
    with patch("httpx.AsyncClient.get", return_value=response):
        tool = SitDeckTool()
        result = tool.execute(action="widgets")

    assert result.success is True
    data = json.loads(result.content)
    assert data["endpoint"] == "widgets"


def test_tool_execute_unknown_action_returns_failure():
    tool = SitDeckTool()
    result = tool.execute(action="invalid_action")
    assert result.success is False
    data = json.loads(result.content)
    assert "Unknown action" in data["error"]

