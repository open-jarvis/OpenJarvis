"""Presentation-session composition through the native SystemBuilder."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock, patch

from openjarvis.core.config import JarvisConfig
from openjarvis.core.types import ToolResult
from openjarvis.system.builder import SystemBuilder


class _FakePlaywrightClient:
    _server_name = "playwright"

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def call_tool(self, name: str, arguments: dict) -> dict:
        if name == "browser_tabs" and arguments == {"action": "list"}:
            return {"content": [{"type": "text", "text": "0: about:blank"}]}
        return {"content": []}


def test_builder_injects_its_presentation_manager_into_display_tools() -> None:
    """Would fail if display tools and routes could use different sessions."""
    import openjarvis.tools.display as display

    importlib.reload(display)
    config = JarvisConfig()
    config.telemetry.enabled = False
    config.traces.enabled = False
    config.skills.enabled = False
    config.agent_manager.enabled = False
    config.tools.enabled = ["display_menu"]
    config.tools.mcp.enabled = True
    config.tools.mcp.servers = json.dumps(
        [{"name": "playwright", "url": "http://localhost:8080/mcp"}]
    )
    engine = MagicMock(spec=["health", "list_models", "close"])
    engine.health.return_value = True
    client = _FakePlaywrightClient()
    builder = SystemBuilder(config).engine_instance(engine).speech(False)

    def _discover(_server_config):
        builder._mcp_clients.append(client)
        return []

    with (
        patch.object(builder, "_discover_external_mcp", side_effect=_discover),
        patch.object(builder, "_resolve_memory", return_value=None),
    ):
        system = builder.build()

    try:
        display_menu = next(
            tool for tool in system.tools if tool.spec.name == "display_menu"
        )

        assert display_menu._presentation is system.presentation_session_manager
        assert system.presentation_session_manager._client is client
    finally:
        system.close()

    assert client.closed is True


def test_builder_wires_recipe_declared_initial_display_inputs() -> None:
    config = JarvisConfig()
    config.telemetry.enabled = False
    config.traces.enabled = False
    config.agent_manager.enabled = False
    config.tools.enabled = ["http_request", "display_menu"]
    config.skills.enabled = True
    config.skills.active = "trendcoffee-menu"
    config.tools.mcp.enabled = True
    config.tools.mcp.servers = json.dumps(
        [{"name": "playwright", "url": "http://localhost:8080/mcp"}]
    )
    engine = MagicMock(spec=["health", "list_models", "close"])
    engine.health.return_value = True
    client = _FakePlaywrightClient()
    builder = SystemBuilder(config).engine_instance(engine).speech(False)

    def _discover(_server_config):
        builder._mcp_clients.append(client)
        return []

    with (
        patch.object(builder, "_discover_external_mcp", side_effect=_discover),
        patch.object(builder, "_resolve_memory", return_value=None),
    ):
        system = builder.build()

    try:
        menu = system.tool_executor.get_tool("skill_trendcoffee-menu")
        assert menu is not None
        with patch.object(
            menu,
            "execute",
            return_value=ToolResult("skill_trendcoffee-menu", "shown", True),
        ) as execute:
            system.presentation_session_manager.ensure("http://127.0.0.1:5173")

            assert system.presentation_session_manager.preload_initial_display() is True

        execute.assert_called_once_with(
            contains="", minPrice=0, maxPrice=1_000_000_000
        )
    finally:
        system.close()
