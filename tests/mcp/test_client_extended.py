"""Extended tests for MCPClient — initialize params, notify, context manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openjarvis.mcp.client import MCPClient
from openjarvis.mcp.protocol import MCPRequest, MCPResponse
from openjarvis.tools._stubs import ToolSpec


@pytest.fixture
def mock_transport():
    """A mock transport that returns configurable responses."""
    transport = MagicMock()
    transport.send.return_value = MCPResponse(result={})
    return transport


class TestInitialize:
    def test_sends_correct_params(self, mock_transport):
        """initialize() must send protocolVersion, capabilities, clientInfo."""
        mock_transport.send.return_value = MCPResponse(
            result={"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}}
        )
        client = MCPClient(mock_transport)
        client.initialize()

        # First call is the initialize request
        init_call = mock_transport.send.call_args_list[0]
        req = init_call[0][0]
        assert isinstance(req, MCPRequest)
        assert req.method == "initialize"
        assert req.params["protocolVersion"] == "2025-03-26"
        assert req.params["capabilities"] == {}
        assert req.params["clientInfo"]["name"] == "openjarvis"
        assert req.params["clientInfo"]["version"] == "0.1.0"

    def test_sends_initialized_notification(self, mock_transport):
        """After initialize, notifications/initialized must be sent via
        send_notification."""
        mock_transport.send.return_value = MCPResponse(
            result={"protocolVersion": "2025-03-26", "capabilities": {}}
        )
        client = MCPClient(mock_transport)
        client.initialize()

        # initialize request goes via send(), notification via send_notification()
        assert mock_transport.send.call_count == 1
        mock_transport.send_notification.assert_called_once()
        req = mock_transport.send_notification.call_args[0][0]
        assert req.method == "notifications/initialized"
        assert req.id is None  # notifications must not have an id

    def test_stores_capabilities(self, mock_transport):
        """initialize() should store server capabilities."""
        mock_transport.send.return_value = MCPResponse(
            result={"capabilities": {"tools": {"listChanged": True}}}
        )
        client = MCPClient(mock_transport)
        client.initialize()
        assert client._capabilities == {"tools": {"listChanged": True}}


class TestNotify:
    def test_notify_sends_request(self, mock_transport):
        """notify() should send a notification with the given method and params."""
        client = MCPClient(mock_transport)
        client.notify("notifications/cancelled", {"requestId": 42})

        mock_transport.send_notification.assert_called_once()
        req = mock_transport.send_notification.call_args[0][0]
        assert req.method == "notifications/cancelled"
        assert req.params == {"requestId": 42}
        assert req.id is None  # notifications must omit id

    def test_notify_defaults_empty_params(self, mock_transport):
        """notify() with no params should send empty dict."""
        client = MCPClient(mock_transport)
        client.notify("notifications/initialized")

        req = mock_transport.send_notification.call_args[0][0]
        assert req.params == {}

    def test_notify_json_has_no_id(self, mock_transport):
        """The serialized notification JSON must not contain an 'id' field."""
        import json

        client = MCPClient(mock_transport)
        client.notify("notifications/initialized")

        req = mock_transport.send_notification.call_args[0][0]
        payload = json.loads(req.to_json())
        assert "id" not in payload


class TestContextManager:
    def test_context_manager_calls_close(self, mock_transport):
        """Using MCPClient as context manager should call close on exit."""
        with MCPClient(mock_transport) as client:
            assert client is not None
        mock_transport.close.assert_called_once()

    def test_context_manager_closes_on_exception(self, mock_transport):
        """close() should be called even if an exception occurs."""
        with pytest.raises(ValueError):
            with MCPClient(mock_transport):
                raise ValueError("test error")
        mock_transport.close.assert_called_once()


class TestListTools:
    def test_parses_tool_specs(self, mock_transport):
        """list_tools() should return ToolSpec objects from server response."""
        mock_transport.send.return_value = MCPResponse(
            result={
                "tools": [
                    {
                        "name": "get_entities",
                        "description": "Get HA entities",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"domain": {"type": "string"}},
                        },
                    },
                    {
                        "name": "call_service",
                        "description": "Call HA service",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            }
        )
        client = MCPClient(mock_transport)
        tools = client.list_tools()

        assert len(tools) == 2
        assert all(isinstance(t, ToolSpec) for t in tools)
        assert tools[0].name == "get_entities"
        assert tools[0].description == "Get HA entities"
        assert "properties" in tools[0].parameters
        assert tools[1].name == "call_service"

    def test_empty_tools_list(self, mock_transport):
        """list_tools() with no tools should return empty list."""
        mock_transport.send.return_value = MCPResponse(result={"tools": []})
        client = MCPClient(mock_transport)
        assert client.list_tools() == []


class TestCallTool:
    def test_call_tool_sends_correct_params(self, mock_transport):
        """call_tool() should send method=tools/call with name and arguments."""
        mock_transport.send.return_value = MCPResponse(
            result={"content": [{"type": "text", "text": "ok"}], "isError": False}
        )
        client = MCPClient(mock_transport)
        result = client.call_tool("get_entities", {"domain": "light"})

        req = mock_transport.send.call_args[0][0]
        assert req.method == "tools/call"
        assert req.params == {"name": "get_entities", "arguments": {"domain": "light"}}
        assert result["isError"] is False

    def test_call_tool_no_arguments(self, mock_transport):
        """call_tool() with no arguments passes empty dict."""
        mock_transport.send.return_value = MCPResponse(
            result={"content": [{"type": "text", "text": "done"}], "isError": False}
        )
        client = MCPClient(mock_transport)
        client.call_tool("ping")

        req = mock_transport.send.call_args[0][0]
        assert req.params == {"name": "ping", "arguments": {}}
