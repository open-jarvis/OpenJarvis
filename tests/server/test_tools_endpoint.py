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
