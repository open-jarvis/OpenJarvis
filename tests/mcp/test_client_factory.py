"""The single place that turns one MCP server config into a client.

Three call sites used to repeat the transport/client construction, so a
deployment needing a different client -- one that can cancel an in-flight call
when a realtime turn is interrupted -- had to fork all three.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from openjarvis.mcp.factory import create_mcp_client, register_mcp_client_impl


def test_missing_url_and_command_returns_none():
    assert create_mcp_client({"name": "broken"}) is None


def test_custom_implementation_is_selected_by_key():
    seen: list[dict] = []

    class _FakeClient:
        def __init__(self, cfg):
            seen.append(cfg)

    register_mcp_client_impl("fake-for-test", lambda cfg: _FakeClient(cfg))

    cfg = {"name": "playwright", "command": "npx", "client": "fake-for-test"}
    client = create_mcp_client(cfg)

    assert isinstance(client, _FakeClient)
    assert seen == [cfg]


def test_unknown_implementation_key_is_an_error():
    """Silently falling back would run the server on semantics it did not ask for."""
    cfg = {"name": "x", "command": "npx", "client": "no-such-impl"}
    with pytest.raises(ValueError, match="no-such-impl"):
        create_mcp_client(cfg)


def test_all_call_sites_use_the_factory():
    """A fourth copy of the construction logic defeats the seam."""
    import openjarvis.mcp.loader as loader_module
    import openjarvis.server.agent_manager_routes as routes_module
    import openjarvis.system.builder as builder_module

    for module in (loader_module, builder_module, routes_module):
        tree = ast.parse(inspect.getsource(module))
        direct = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "MCPClient"
        ]
        assert not direct, f"{module.__name__} still builds MCPClient directly"


def test_cancellation_is_scoped_not_global():
    """Voice barge-in must not cancel a concurrent API agent's call.

    ``_active`` used to hold a single future, so a second caller overwrote the
    first and cancel_active_call() hit the wrong one.
    """
    from openjarvis.mcp.runtime import MCPRuntime

    signature = inspect.signature(MCPRuntime.cancel_active_call)
    assert "scope" in signature.parameters

    source = inspect.getsource(MCPRuntime)
    assert "_active: dict" in source or "_active_by_scope" in source, (
        "cancellation must track one future per scope, not one globally"
    )
