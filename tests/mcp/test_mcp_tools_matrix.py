"""Matrix tests — verify every built-in tool is discoverable and callable via MCP."""

from __future__ import annotations

import pytest

from friday_ai.mcp.client import MCPClient
from friday_ai.mcp.server import MCPServer
from friday_ai.mcp.transport import InProcessTransport
from friday_ai.tools.calculator import CalculatorTool
from friday_ai.tools.think import ThinkTool

# Tool configs: (tool_class, call_arguments, expected_substring)
_TOOL_CONFIGS = {
    "calculator": (CalculatorTool, {"expression": "2+2"}, "4"),
    "think": (ThinkTool, {"thought": "test thought"}, "test thought"),
}


def _make_client(tool_classes):
    """Create an MCP client with the given tool instances."""
    tools = [cls() for cls in tool_classes]
    server = MCPServer(tools)
    transport = InProcessTransport(server)
    return MCPClient(transport)


@pytest.mark.parametrize("tool_name", ["calculator", "think"])
class TestMCPToolsMatrix:
    def test_tool_discoverable_via_mcp(self, tool_name):
        tool_cls, _, _ = _TOOL_CONFIGS[tool_name]
        client = _make_client([tool_cls])
        tools = client.list_tools()
        names = [t.name for t in tools]
        assert tool_name in names

    def test_tool_callable_via_mcp(self, tool_name):
        tool_cls, arguments, expected = _TOOL_CONFIGS[tool_name]
        client = _make_client([tool_cls])
        result = client.call_tool(tool_name, arguments)
        assert result["isError"] is False
        assert expected in result["content"][0]["text"]

    def test_tool_has_description(self, tool_name):
        tool_cls, _, _ = _TOOL_CONFIGS[tool_name]
        client = _make_client([tool_cls])
        tools = client.list_tools()
        tool_spec = next(t for t in tools if t.name == tool_name)
        assert tool_spec.description  # non-empty

    def test_tool_has_input_schema(self, tool_name):
        tool_cls, _, _ = _TOOL_CONFIGS[tool_name]
        client = _make_client([tool_cls])
        tools = client.list_tools()
        tool_spec = next(t for t in tools if t.name == tool_name)
        assert "properties" in tool_spec.parameters

    def test_tool_result_format(self, tool_name):
        tool_cls, arguments, _ = _TOOL_CONFIGS[tool_name]
        client = _make_client([tool_cls])
        result = client.call_tool(tool_name, arguments)
        assert "content" in result
        assert "isError" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"

    def test_tool_error_handling(self, tool_name):
        """Calling with bad args should not crash the server."""
        tool_cls, _, _ = _TOOL_CONFIGS[tool_name]
        client = _make_client([tool_cls])
        # Call with empty arguments
        result = client.call_tool(tool_name, {})
        # Should return a response (not crash)
        assert "content" in result

    def test_tool_in_full_server(self, tool_name):
        """Tool should be discoverable when all tools are registered."""
        all_classes = [cls for cls, _, _ in _TOOL_CONFIGS.values()]
        client = _make_client(all_classes)
        tools = client.list_tools()
        names = [t.name for t in tools]
        assert tool_name in names
