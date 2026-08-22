"""Tests for GET /v1/tools endpoint."""

from unittest.mock import MagicMock

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


def test_web_search_available_without_tavily_key(monkeypatch):
    """DuckDuckGo fallback keeps web search usable without Tavily."""
    from openjarvis.server.agent_manager_routes import build_tools_list

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    tools = build_tools_list()
    web_search = next(t for t in tools if t["name"] == "web_search")

    assert web_search["configured"] is True
    assert web_search["requires_credentials"] is False


def test_weather_tool_picker_recognizes_connector_credential(tmp_path, monkeypatch):
    """An existing Weather connector keeps the native tool configured."""
    from openjarvis.server.agent_manager_routes import build_tools_list

    root = tmp_path / "openjarvis-home"
    connector_path = root / "connectors" / "weather.json"
    connector_path.parent.mkdir(parents=True)
    connector_path.write_text(
        '{"api_key":"connector-key","location":"Boston,US"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENJARVIS_HOME", str(root))
    monkeypatch.delenv("OPENWEATHERMAP_API_KEY", raising=False)

    tools = build_tools_list()
    weather = next(t for t in tools if t["name"] == "get_weather")

    assert weather["requires_credentials"] is True
    assert weather["credential_keys"] == ["OPENWEATHERMAP_API_KEY"]
    assert weather["configured"] is True


def test_tool_credentials_browser_lifecycle(tmp_path, monkeypatch):
    """The browser API can save, report, and remove a Tavily key."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.agent_manager_routes import create_agent_manager_router

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "openjarvis-home"))
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    app = FastAPI()
    tools_router = create_agent_manager_router(MagicMock())[3]
    app.include_router(tools_router)
    client = TestClient(app)

    saved = client.post(
        "/v1/tools/web_search/credentials",
        json={"TAVILY_API_KEY": "tvly-browser-test"},
    )
    assert saved.status_code == 200
    assert saved.json() == {"saved": ["TAVILY_API_KEY"]}
    assert client.get("/v1/tools/web_search/credentials/status").json() == {
        "TAVILY_API_KEY": True
    }

    deleted = client.delete(
        "/v1/tools/web_search/credentials/TAVILY_API_KEY",
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": "TAVILY_API_KEY"}
    assert client.get("/v1/tools/web_search/credentials/status").json() == {
        "TAVILY_API_KEY": False
    }


def test_weather_tool_credentials_browser_lifecycle(tmp_path, monkeypatch):
    """Weather credentials can be managed without entering config.toml."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.agent_manager_routes import create_agent_manager_router

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "openjarvis-home"))
    monkeypatch.delenv("OPENWEATHERMAP_API_KEY", raising=False)
    app = FastAPI()
    tools_router = create_agent_manager_router(MagicMock())[3]
    app.include_router(tools_router)
    client = TestClient(app)

    saved = client.post(
        "/v1/tools/get_weather/credentials",
        json={"OPENWEATHERMAP_API_KEY": "weather-browser-test"},
    )
    assert saved.status_code == 200
    assert saved.json() == {"saved": ["OPENWEATHERMAP_API_KEY"]}
    assert client.get("/v1/tools/get_weather/credentials/status").json() == {
        "OPENWEATHERMAP_API_KEY": True
    }

    deleted = client.delete(
        "/v1/tools/get_weather/credentials/OPENWEATHERMAP_API_KEY",
    )
    assert deleted.status_code == 200
    assert client.get("/v1/tools/get_weather/credentials/status").json() == {
        "OPENWEATHERMAP_API_KEY": False
    }
