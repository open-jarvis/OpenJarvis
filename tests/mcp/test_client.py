"""Tests for the MCP client."""

from __future__ import annotations

import pytest

from openjarvis.mcp.client import MCPClient
from openjarvis.mcp.protocol import MCPError
from openjarvis.mcp.server import MCPServer
from openjarvis.mcp.transport import InProcessTransport
from openjarvis.tools._stubs import ToolSpec
from openjarvis.tools.calculator import CalculatorTool
from openjarvis.tools.think import ThinkTool


@pytest.fixture
def client():
    """MCP client connected via in-process transport."""
    server = MCPServer([CalculatorTool(), ThinkTool()])
    transport = InProcessTransport(server)
    return MCPClient(transport)


class TestMCPClient:
    def test_initialize_handshake(self, client):
        result = client.initialize()
        assert "protocolVersion" in result
        assert "serverInfo" in result
        assert result["serverInfo"]["name"] == "openjarvis"
        assert client._initialized is True

    def test_initialize_sets_capabilities(self, client):
        client.initialize()
        assert "tools" in client._capabilities

    def test_list_tools(self, client):
        tools = client.list_tools()
        assert len(tools) == 2
        assert all(isinstance(t, ToolSpec) for t in tools)
        names = {t.name for t in tools}
        assert "calculator" in names
        assert "think" in names

    def test_list_tools_have_descriptions(self, client):
        tools = client.list_tools()
        for t in tools:
            assert t.description  # non-empty

    def test_list_tools_have_parameters(self, client):
        tools = client.list_tools()
        for t in tools:
            assert "properties" in t.parameters

    def test_call_tool_calculator(self, client):
        result = client.call_tool("calculator", {"expression": "10 + 5"})
        assert result["isError"] is False
        assert "15" in result["content"][0]["text"]

    def test_call_tool_think(self, client):
        result = client.call_tool("think", {"thought": "Reasoning step."})
        assert result["isError"] is False
        assert "Reasoning step." in result["content"][0]["text"]

    def test_call_tool_error(self, client):
        # Rust calculator (meval) returns inf for 1/0 rather than an error
        result = client.call_tool("calculator", {"expression": "1/0"})
        assert result["isError"] is False
        assert "inf" in result["content"][0]["text"]

    def test_call_unknown_tool_raises(self, client):
        with pytest.raises(MCPError) as exc_info:
            client.call_tool("nonexistent", {})
        assert "Unknown tool" in str(exc_info.value)

    def test_client_server_roundtrip(self, client):
        """Full lifecycle: initialize -> list -> call -> close."""
        info = client.initialize()
        assert "serverInfo" in info

        tools = client.list_tools()
        assert len(tools) >= 1

        result = client.call_tool("calculator", {"expression": "7 * 8"})
        assert "56" in result["content"][0]["text"]

        client.close()

    def test_close(self, client):
        client.close()
        # Close should not raise even if called multiple times
        client.close()

    def test_incremental_ids(self, client):
        """Each request should get a unique ID."""
        id1 = client._next_id()
        id2 = client._next_id()
        assert id2 > id1

    def test_call_tool_with_no_arguments(self, client):
        """Calling a tool with no arguments passes an empty object to validation."""
        result = client.call_tool("think")
        assert result["isError"] is True
        assert "required" in result["content"][0]["text"]
