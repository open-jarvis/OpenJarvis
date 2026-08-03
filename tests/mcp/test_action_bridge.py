"""Security and live-policy tests for the canonical MCP action bridge."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.mcp.action_bridge import _manifest, _runtime, discover_action_tools
from openjarvis.tasks.policy import RiskLevel
from openjarvis.tools.action_service import ToolActionService
from openjarvis.tools.action_store import ActionStore
from openjarvis.tools.manifest import ToolManifestCatalog


def _adapter(name: str = "weather", schema: dict | None = None) -> MagicMock:
    adapter = MagicMock()
    adapter.spec.name = name
    adapter.spec.description = "Untrusted remote description"
    adapter.spec.parameters = schema or {"type": "object", "properties": {}}
    adapter.spec.timeout_seconds = 30.0
    return adapter


def test_manifest_rejects_unenforced_schema_constraints() -> None:
    adapter = _adapter(
        schema={
            "type": "object",
            "properties": {"value": {"$ref": "#/$defs/value"}},
            "$defs": {"value": {"type": "string"}},
        }
    )

    with pytest.raises(ValueError, match="unsupported constraints"):
        _manifest("test", adapter, "read", http=True)


def test_manifest_rejects_declared_secret_arguments() -> None:
    adapter = _adapter(
        schema={
            "type": "object",
            "properties": {"api_key": {"type": "string"}},
        }
    )

    with pytest.raises(ValueError, match="transport authentication"):
        _manifest("test", adapter, "read", http=True)


def test_runtime_rejects_nested_secret_arguments() -> None:
    adapter = _adapter()
    runtime = _runtime(adapter, SimpleNamespace(), "test")

    with pytest.raises(ValueError, match="transport authentication"):
        runtime.handler({"options": {"password": "must-not-leave"}})
    adapter.execute.assert_not_called()


def test_live_policy_change_replaces_policy_but_not_schema(tmp_path) -> None:
    catalog = ToolManifestCatalog(())
    service = ToolActionService(
        catalog=catalog,
        store=ActionStore(tmp_path / "actions.sqlite3"),
        context_factory=lambda _proposal: None,
        runtimes={},
        artifact_root=tmp_path / "artifacts",
    )
    state = SimpleNamespace(tool_action_service=service)
    adapter = _adapter()

    def config(policy: str) -> MagicMock:
        value = MagicMock()
        value.tools.mcp.enabled = True
        value.tools.mcp.servers = json.dumps(
            [
                {
                    "name": "test",
                    "url": "http://127.0.0.1:8765/mcp",
                    "tool_policies": {"weather": policy},
                }
            ]
        )
        return value

    with (
        patch("openjarvis.core.config.load_config", return_value=config("write")),
        patch("openjarvis.mcp.transport.StreamableHTTPTransport"),
        patch("openjarvis.mcp.client.MCPClient"),
        patch("openjarvis.tools.mcp_adapter.MCPToolProvider") as provider,
    ):
        provider.return_value.discover.return_value = [adapter]
        tools, _ = discover_action_tools(state, force=True)

    tool_id = tools[0]["function"]["name"]
    assert catalog.get(tool_id).risk_level is RiskLevel.DESTRUCTIVE_OR_SENSITIVE

    with (
        patch("openjarvis.core.config.load_config", return_value=config("read")),
        patch("openjarvis.mcp.transport.StreamableHTTPTransport"),
        patch("openjarvis.mcp.client.MCPClient"),
        patch("openjarvis.tools.mcp_adapter.MCPToolProvider") as provider,
    ):
        provider.return_value.discover.return_value = [adapter]
        tools, _ = discover_action_tools(state, force=True)

    assert tools[0]["function"]["name"] == tool_id
    assert catalog.get(tool_id).risk_level is RiskLevel.READ_ONLY
    assert service.runtime_available(tool_id)
