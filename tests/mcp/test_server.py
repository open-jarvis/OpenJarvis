"""Tests for the MCP server."""

from __future__ import annotations

import pytest

from openjarvis.mcp.protocol import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    MCPRequest,
)
from openjarvis.mcp.server import MCPServer
from openjarvis.tools.calculator import CalculatorTool
from openjarvis.tools.think import ThinkTool


@pytest.fixture
def server():
    """Create an MCP server with calculator and think tools."""
    return MCPServer([CalculatorTool(), ThinkTool()])


class TestMCPServer:
    def test_initialize(self, server):
        req = MCPRequest(method="initialize", id=1)
        resp = server.handle(req)
        assert resp.error is None
        assert resp.id == 1
        result = resp.result
        assert "protocolVersion" in result
        assert "capabilities" in result
        assert "serverInfo" in result
        assert result["serverInfo"]["name"] == "openjarvis"

    def test_initialize_capabilities(self, server):
        req = MCPRequest(method="initialize", id=1)
        resp = server.handle(req)
        caps = resp.result["capabilities"]
        assert "tools" in caps

    def test_tools_list_all(self, server):
        req = MCPRequest(method="tools/list", id=2)
        resp = server.handle(req)
        assert resp.error is None
        tools = resp.result["tools"]
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert "calculator" in names
        assert "think" in names

    def test_tools_list_includes_spec(self, server):
        req = MCPRequest(method="tools/list", id=2)
        resp = server.handle(req)
        tools = resp.result["tools"]
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    def test_tools_list_input_schema_has_properties(self, server):
        req = MCPRequest(method="tools/list", id=2)
        resp = server.handle(req)
        tools = resp.result["tools"]
        for tool in tools:
            schema = tool["inputSchema"]
            assert "properties" in schema

    def test_auto_discover_includes_agent_and_mac_tools(self):
        names = {tool.spec.name for tool in MCPServer().get_tools()}

        assert "agent_spawn" in names
        assert "agent_send" in names
        assert "agent_list" in names
        assert "agent_kill" in names
        assert "mac_automation" in names

    def test_tools_call_calculator(self, server):
        req = MCPRequest(
            method="tools/call",
            params={"name": "calculator", "arguments": {"expression": "2+2"}},
            id=3,
        )
        resp = server.handle(req)
        assert resp.error is None
        assert resp.result["isError"] is False
        content = resp.result["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert "4" in content[0]["text"]

    def test_tools_call_calculator_complex(self, server):
        req = MCPRequest(
            method="tools/call",
            params={"name": "calculator", "arguments": {"expression": "3 * (4 + 5)"}},
            id=4,
        )
        resp = server.handle(req)
        assert resp.error is None
        assert "27" in resp.result["content"][0]["text"]

    def test_tools_call_think(self, server):
        req = MCPRequest(
            method="tools/call",
            params={
                "name": "think",
                "arguments": {"thought": "Step 1: analyze the problem."},
            },
            id=5,
        )
        resp = server.handle(req)
        assert resp.error is None
        assert resp.result["isError"] is False
        assert "Step 1" in resp.result["content"][0]["text"]

    def test_tools_call_unknown_tool(self, server):
        req = MCPRequest(
            method="tools/call",
            params={"name": "nonexistent", "arguments": {}},
            id=6,
        )
        resp = server.handle(req)
        assert resp.error is not None
        assert resp.error["code"] == INVALID_PARAMS
        assert "Unknown tool" in resp.error["message"]

    def test_tools_call_missing_name(self, server):
        req = MCPRequest(
            method="tools/call",
            params={"arguments": {}},
            id=7,
        )
        resp = server.handle(req)
        assert resp.error is not None
        assert resp.error["code"] == INVALID_PARAMS
        assert "name" in resp.error["message"]

    def test_tools_call_invalid_arguments(self, server):
        req = MCPRequest(
            method="tools/call",
            params={"name": "calculator", "arguments": {}},
            id=8,
        )
        resp = server.handle(req)
        # Calculator returns failure but not a protocol error
        assert resp.error is None
        assert resp.result["isError"] is True

    def test_result_format_mcp_compliant(self, server):
        req = MCPRequest(
            method="tools/call",
            params={"name": "think", "arguments": {"thought": "hello"}},
            id=9,
        )
        resp = server.handle(req)
        result = resp.result
        assert "content" in result
        assert "isError" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"

    def test_unknown_method(self, server):
        req = MCPRequest(method="resources/list", id=10)
        resp = server.handle(req)
        assert resp.error is not None
        assert resp.error["code"] == METHOD_NOT_FOUND
        assert "Unknown method" in resp.error["message"]

    def test_response_preserves_request_id(self, server):
        req = MCPRequest(method="tools/list", id=42)
        resp = server.handle(req)
        assert resp.id == 42

    def test_response_preserves_string_id(self, server):
        req = MCPRequest(method="tools/list", id="req-abc")
        resp = server.handle(req)
        assert resp.id == "req-abc"

    def test_empty_tools_server(self):
        empty_server = MCPServer([])
        req = MCPRequest(method="tools/list", id=1)
        resp = empty_server.handle(req)
        assert resp.result["tools"] == []

    def test_tools_call_with_no_arguments_key(self, server):
        req = MCPRequest(
            method="tools/call",
            params={"name": "calculator"},
            id=11,
        )
        resp = server.handle(req)
        # Should still execute (with empty arguments)
        assert resp.error is None

    def test_calculator_division_by_zero_returns_inf(self, server):
        # Rust calculator (meval) returns inf for 1/0 rather than an error
        req = MCPRequest(
            method="tools/call",
            params={"name": "calculator", "arguments": {"expression": "1/0"}},
            id=12,
        )
        resp = server.handle(req)
        assert resp.error is None
        assert resp.result["isError"] is False
        assert "inf" in resp.result["content"][0]["text"]
