"""Tests for the MCP tool adapter — round-trip through MCPServer + MCPClient."""

from __future__ import annotations

import pytest

from friday_ai.mcp.client import MCPClient
from friday_ai.mcp.server import MCPServer
from friday_ai.mcp.transport import InProcessTransport
from friday_ai.tools._stubs import ToolSpec
from friday_ai.tools.calculator import CalculatorTool
from friday_ai.tools.mcp_adapter import MCPToolAdapter, MCPToolProvider
from friday_ai.tools.think import ThinkTool


@pytest.fixture
def server():
    """Create an MCP server with calculator and think tools."""
    return MCPServer([CalculatorTool(), ThinkTool()])


@pytest.fixture
def client(server):
    """Create an MCP client connected to the server via in-process transport."""
    transport = InProcessTransport(server)
    c = MCPClient(transport)
    c.initialize()
    return c


class TestMCPToolAdapter:
    def test_adapter_spec(self, client):
        spec = ToolSpec(
            name="calculator",
            description="Evaluate a math expression",
            parameters={
                "type": "object",
                "properties": {"expression": {"type": "string"}},
            },
        )
        adapter = MCPToolAdapter(client, spec)
        assert adapter.spec.name == "calculator"
        assert adapter.spec.description == "Evaluate a math expression"

    def test_adapter_execute_success(self, client):
        spec = ToolSpec(
            name="calculator",
            description="Calculator",
            parameters={},
        )
        adapter = MCPToolAdapter(client, spec)
        result = adapter.execute(expression="2+2")
        assert result.success is True
        assert "4" in result.content
        assert result.tool_name == "calculator"

    def test_adapter_execute_think(self, client):
        spec = ToolSpec(
            name="think",
            description="Think tool",
            parameters={},
        )
        adapter = MCPToolAdapter(client, spec)
        result = adapter.execute(thought="Let me analyze this.")
        assert result.success is True
        assert "analyze" in result.content

    def test_adapter_execute_error(self, client):
        spec = ToolSpec(
            name="calculator",
            description="Calculator",
            parameters={},
        )
        adapter = MCPToolAdapter(client, spec)
        result = adapter.execute(expression="1/0")
        assert result.success is True
        assert result.content == "inf"

    def test_adapter_unknown_tool(self, client):
        spec = ToolSpec(
            name="nonexistent",
            description="Does not exist",
            parameters={},
        )
        adapter = MCPToolAdapter(client, spec)
        result = adapter.execute(x="y")
        assert result.success is False
        assert "error" in result.content.lower() or "MCP" in result.content

    def test_adapter_tool_id(self, client):
        spec = ToolSpec(name="calculator", description="Calc", parameters={})
        adapter = MCPToolAdapter(client, spec)
        assert adapter.tool_id == "mcp_adapter"


class TestMCPToolProvider:
    def test_discover_returns_adapters(self, client):
        provider = MCPToolProvider(client)
        tools = provider.discover()
        assert len(tools) == 2
        names = {t.spec.name for t in tools}
        assert "calculator" in names
        assert "think" in names

    def test_discovered_tools_are_base_tool(self, client):
        from friday_ai.tools._stubs import BaseTool

        provider = MCPToolProvider(client)
        tools = provider.discover()
        for tool in tools:
            assert isinstance(tool, BaseTool)

    def test_discovered_tool_execution(self, client):
        provider = MCPToolProvider(client)
        tools = provider.discover()
        calc = next(t for t in tools if t.spec.name == "calculator")
        result = calc.execute(expression="3*7")
        assert result.success is True
        assert "21" in result.content


class TestMCPAdapterRoundTrip:
    """End-to-end: Server → InProcessTransport → Client → Adapter → execute."""

    def test_full_round_trip(self):
        server = MCPServer([CalculatorTool(), ThinkTool()])
        transport = InProcessTransport(server)
        client = MCPClient(transport)
        client.initialize()
        provider = MCPToolProvider(client)
        tools = provider.discover()

        calc = next(t for t in tools if t.spec.name == "calculator")
        result = calc.execute(expression="10+20")
        assert result.success is True
        assert "30" in result.content

    def test_round_trip_error_handling(self):
        server = MCPServer([CalculatorTool()])
        transport = InProcessTransport(server)
        client = MCPClient(transport)
        client.initialize()
        provider = MCPToolProvider(client)
        tools = provider.discover()

        calc = tools[0]
        result = calc.execute(expression="1/0")
        assert result.success is True
        assert result.content == "inf"

    def test_empty_server_discover(self):
        server = MCPServer([])
        transport = InProcessTransport(server)
        client = MCPClient(transport)
        client.initialize()
        provider = MCPToolProvider(client)
        tools = provider.discover()
        assert tools == []
