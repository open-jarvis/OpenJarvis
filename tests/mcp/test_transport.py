"""Tests for MCP transport implementations."""

from __future__ import annotations

import sys

import pytest

from openjarvis.mcp.protocol import MCPRequest
from openjarvis.mcp.server import MCPServer
from openjarvis.mcp.transport import (
    InProcessTransport,
    SSETransport,
    StdioTransport,
    StreamableHTTPTransport,
)
from openjarvis.tools.calculator import CalculatorTool
from openjarvis.tools.think import ThinkTool


@pytest.fixture
def server():
    """MCP server with calculator and think tools."""
    return MCPServer([CalculatorTool(), ThinkTool()])


class TestInProcessTransport:
    def test_direct_call(self, server):
        transport = InProcessTransport(server)
        req = MCPRequest(method="initialize", id=1)
        resp = transport.send(req)
        assert resp.error is None
        assert "serverInfo" in resp.result

    def test_roundtrip_tools_list(self, server):
        transport = InProcessTransport(server)
        req = MCPRequest(method="tools/list", id=2)
        resp = transport.send(req)
        assert resp.error is None
        tools = resp.result["tools"]
        assert len(tools) == 2

    def test_roundtrip_tools_call(self, server):
        transport = InProcessTransport(server)
        req = MCPRequest(
            method="tools/call",
            params={"name": "calculator", "arguments": {"expression": "5*5"}},
            id=3,
        )
        resp = transport.send(req)
        assert resp.error is None
        assert "25" in resp.result["content"][0]["text"]

    def test_multiple_calls(self, server):
        transport = InProcessTransport(server)
        for i in range(5):
            req = MCPRequest(method="tools/list", id=i)
            resp = transport.send(req)
            assert resp.error is None

    def test_close_is_noop(self, server):
        transport = InProcessTransport(server)
        transport.close()  # Should not raise

    def test_error_method(self, server):
        transport = InProcessTransport(server)
        req = MCPRequest(method="unknown/method", id=1)
        resp = transport.send(req)
        assert resp.error is not None


class TestStdioTransport:
    """StdioTransport is an SDK connection description, not a protocol client."""

    def test_stdio_transport_is_an_sdk_connection_description(self):
        transport = StdioTransport(["npx", "-y", "@playwright/mcp@0.0.79"])
        assert transport.command == "npx"
        assert transport.args == ["-y", "@playwright/mcp@0.0.79"]
        assert not hasattr(transport, "_process")

    def test_stdio_transport_does_not_launch_a_process(self):
        transport = StdioTransport([sys.executable, "-c", "raise SystemExit(1)"])
        assert transport.command == sys.executable
        transport.close()  # no owned process to release

    def test_stdio_transport_exposes_sdk_client_factory(self):
        transport = StdioTransport(["npx", "-y", "@playwright/mcp@0.0.79"])
        assert callable(transport.sdk_client)

    def test_stdio_transport_send_is_not_supported(self):
        transport = StdioTransport(["npx"])
        with pytest.raises(NotImplementedError):
            transport.send(MCPRequest(method="tools/list", id=1))


class TestStreamableHTTPTransport:
    """StreamableHTTPTransport is an SDK connection description."""

    def test_http_transport_retains_endpoint_and_bearer_header(self):
        transport = StreamableHTTPTransport("https://mcp.example.test", token="secret")
        assert transport.url == "https://mcp.example.test"
        assert transport.headers == {"Authorization": "Bearer secret"}

    def test_http_transport_without_token_sends_no_authorization(self):
        transport = StreamableHTTPTransport("https://mcp.example.test")
        assert transport.headers == {}

    def test_http_transport_empty_token_sends_no_authorization(self):
        transport = StreamableHTTPTransport("https://mcp.example.test", token="")
        assert transport.headers == {}

    def test_http_transport_owns_no_httpx_client(self):
        transport = StreamableHTTPTransport("https://mcp.example.test")
        assert not hasattr(transport, "_client")
        transport.close()

    def test_http_transport_exposes_sdk_client_factory(self):
        transport = StreamableHTTPTransport("https://mcp.example.test")
        assert callable(transport.sdk_client)

    def test_sse_transport_alias(self):
        """SSETransport should be an alias for StreamableHTTPTransport."""
        assert SSETransport is StreamableHTTPTransport


class TestStdioEnvironmentInheritance:
    """The SDK's default env filter drops DISPLAY, forcing headless browsers."""

    def test_stdio_server_parameters_inherit_the_process_environment(self, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
        captured = {}

        def _fake_stdio_client(server):
            captured["env"] = server.env
            return server

        monkeypatch.setattr("mcp.client.stdio.stdio_client", _fake_stdio_client)
        StdioTransport(["npx", "-y", "@playwright/mcp@0.0.79"]).sdk_client()

        assert captured["env"] is not None, "env=None makes the SDK filter DISPLAY out"
        assert captured["env"]["DISPLAY"] == ":0"
        assert captured["env"]["WAYLAND_DISPLAY"] == "wayland-1"
