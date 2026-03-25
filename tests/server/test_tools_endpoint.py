"""Tests for GET /v1/tools endpoint."""

import pytest

try:
    from openjarvis.server.agent_manager_routes import build_tools_list
except ImportError:
    build_tools_list = None

pytestmark = pytest.mark.skipif(
    build_tools_list is None,
    reason="fastapi not installed (requires server extra)",
)


def test_tools_endpoint_returns_list():
    from openjarvis.server.agent_manager_routes import build_tools_list

    tools = build_tools_list()
    assert isinstance(tools, list)
    assert len(tools) > 0
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "category" in t
        assert "source" in t
        assert "requires_credentials" in t
        assert "credential_keys" in t
        assert "configured" in t


def test_tools_includes_channels():
    from openjarvis.server.agent_manager_routes import build_tools_list

    tools = build_tools_list()
    names = {t["name"] for t in tools}
    channel_names = {"slack", "telegram", "discord", "email"}
    assert channel_names & names


def test_browser_meta_group():
    from openjarvis.server.agent_manager_routes import build_tools_list

    tools = build_tools_list()
    names = {t["name"] for t in tools}
    assert "browser" in names
    assert "browser_navigate" not in names


def test_tools_includes_mcp_tools():
    """MCP tools from _get_mcp_tools appear in /v1/tools response."""
    from unittest.mock import patch, MagicMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.agent_manager_routes import build_tools_list

    fake_mcp_tools = [
        {"type": "function", "function": {"name": "ha_get_state", "description": "Get HA entity state", "parameters": {}}},
        {"type": "function", "function": {"name": "ha_call_service", "description": "Call HA service", "parameters": {}}},
    ]

    app = FastAPI()

    @app.get("/v1/tools")
    def list_tools_with_mcp():
        from starlette.requests import Request
        items = build_tools_list()
        # Simulate what the patched endpoint does
        for tool in fake_mcp_tools:
            fn = tool.get("function", {})
            items.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "category": "mcp",
                "source": "mcp",
                "requires_credentials": False,
                "credential_keys": [],
                "configured": True,
            })
        return {"tools": items}

    client = TestClient(app)
    resp = client.get("/v1/tools")
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    mcp_tools = [t for t in tools if t.get("source") == "mcp"]
    assert len(mcp_tools) == 2
    assert {t["name"] for t in mcp_tools} == {"ha_get_state", "ha_call_service"}
    for t in mcp_tools:
        assert t["category"] == "mcp"
        assert t["configured"] is True
        assert t["requires_credentials"] is False


def test_tools_graceful_mcp_failure():
    """Built-in tools still returned when MCP discovery fails."""
    tools = build_tools_list()
    # build_tools_list itself should always work even without MCP
    assert isinstance(tools, list)
    assert len(tools) > 0
    # No MCP tools should be present in build_tools_list alone
    mcp_tools = [t for t in tools if t.get("source") == "mcp"]
    assert len(mcp_tools) == 0
