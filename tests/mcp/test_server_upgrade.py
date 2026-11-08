"""Tests for MCP server upgrade to protocol version 2025-11-25."""

from __future__ import annotations

import pytest

from friday_ai.mcp.protocol import MCPRequest
from friday_ai.mcp.server import MCPServer
from friday_ai.tools.calculator import CalculatorTool
from friday_ai.tools.think import ThinkTool


@pytest.fixture
def server():
    return MCPServer([CalculatorTool(), ThinkTool()])


class TestProtocolVersion:
    def test_protocol_version_2025(self, server):
        assert server.PROTOCOL_VERSION == "2025-11-25"

    def test_initialize_returns_2025_version(self, server):
        req = MCPRequest(method="initialize", id=1)
        resp = server.handle(req)
        assert resp.result["protocolVersion"] == "2025-11-25"


class TestServerTitle:
    def test_initialize_includes_title(self, server):
        req = MCPRequest(method="initialize", id=1)
        resp = server.handle(req)
        server_info = resp.result["serverInfo"]
        assert "title" in server_info
        assert server_info["title"] == "FridayAI Tool Server"


class TestListChanged:
    def test_tools_capability_list_changed_true(self, server):
        req = MCPRequest(method="initialize", id=1)
        resp = server.handle(req)
        caps = resp.result["capabilities"]
        assert caps["tools"]["listChanged"] is True


class TestAnnotations:
    def test_calculator_has_read_only_annotation(self, server):
        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        tools = resp.result["tools"]
        calc = next(t for t in tools if t["name"] == "calculator")
        assert "annotations" in calc
        assert calc["annotations"]["readOnlyHint"] is True
        assert calc["annotations"]["destructiveHint"] is False

    def test_think_has_read_only_annotation(self, server):
        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        tools = resp.result["tools"]
        think = next(t for t in tools if t["name"] == "think")
        assert "annotations" in think
        assert think["annotations"]["readOnlyHint"] is True


class TestAutoDiscovery:
    def test_auto_discover_creates_server(self):
        """MCPServer() with no tools arg should auto-discover."""
        server = MCPServer()
        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        # Should have at least calculator and think (via direct import)
        names = {t["name"] for t in resp.result["tools"]}
        assert "calculator" in names
        assert "think" in names

    def test_auto_discover_includes_storage_tools(self):
        """Auto-discovered server should include storage tools."""
        server = MCPServer()
        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        names = {t["name"] for t in resp.result["tools"]}
        assert "memory_store" in names
        assert "memory_retrieve" in names
        assert "memory_search" in names
        assert "memory_index" in names

    def test_auto_discover_tool_count(self):
        """Auto-discovered server should have all built-in tools."""
        server = MCPServer()
        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        # At least: calculator, think, file_read, web_search,
        # code_interpreter, memory_store/retrieve/search/index,
        # llm, retrieval
        assert len(resp.result["tools"]) >= 8

    def test_explicit_tools_override_auto_discover(self):
        """Passing explicit tools should NOT auto-discover."""
        server = MCPServer([CalculatorTool()])
        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        tools = resp.result["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "calculator"

    def test_empty_list_means_no_tools(self):
        """Passing empty list should give empty tools (not auto-discover)."""
        server = MCPServer([])
        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        assert resp.result["tools"] == []


class TestStorageToolAnnotations:
    def test_memory_store_destructive(self):
        from friday_ai.tools.storage_tools import MemoryStoreTool

        server = MCPServer([MemoryStoreTool()])
        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        tool = resp.result["tools"][0]
        assert tool["annotations"]["destructiveHint"] is True
        assert tool["annotations"]["readOnlyHint"] is False

    def test_memory_retrieve_read_only(self):
        from friday_ai.tools.storage_tools import MemoryRetrieveTool

        server = MCPServer([MemoryRetrieveTool()])
        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        tool = resp.result["tools"][0]
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["annotations"]["destructiveHint"] is False
