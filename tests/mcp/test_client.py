"""Tests for the MCP client."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from openjarvis.mcp.client import MCPClient
from openjarvis.mcp.protocol import MCPError, MCPResponse
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
        """Calling a tool with no arguments passes empty dict."""
        result = client.call_tool("think")
        # Think tool echoes empty thought
        assert result["isError"] is False

    def test_shared_client_serializes_transport_round_trips(self):
        """Concurrent agents cannot consume one another's MCP responses."""

        class _ConcurrencyProbeTransport:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def send(self, request):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.01)
                with self.lock:
                    self.active -= 1
                return MCPResponse(result={"tools": []}, id=request.id)

            def send_notification(self, request):
                return None

            def close(self):
                return None

        transport = _ConcurrencyProbeTransport()
        shared_client = MCPClient(transport)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: shared_client.list_tools(), range(24)))

        assert transport.max_active == 1

    def test_close_interrupts_blocked_request_and_rejects_queued_request(self):
        """Shutdown reaches the transport without waiting on an in-flight call."""

        class _BlockingTransport:
            def __init__(self):
                self.send_started = threading.Event()
                self.send_released = threading.Event()
                self.close_called = threading.Event()
                self.send_count = 0

            def send(self, request):
                self.send_count += 1
                self.send_started.set()
                self.send_released.wait()
                raise RuntimeError("transport closed")

            def send_notification(self, request):
                return None

            def close(self):
                self.close_called.set()
                self.send_released.set()

        transport = _BlockingTransport()
        shared_client = MCPClient(transport)

        with ThreadPoolExecutor(max_workers=3) as pool:
            blocked_request = pool.submit(shared_client.list_tools)
            assert transport.send_started.wait(timeout=1)

            queued_request = pool.submit(shared_client.list_tools)
            close_call = pool.submit(shared_client.close)

            try:
                close_reached_transport = transport.close_called.wait(timeout=1)
            finally:
                # Keep the test failure-safe against a regression that makes
                # close wait behind the blocked request.
                transport.send_released.set()

            close_call.result(timeout=1)
            assert close_reached_transport
            with pytest.raises(RuntimeError, match="transport closed"):
                blocked_request.result(timeout=1)
            with pytest.raises(RuntimeError, match="MCP client is closed"):
                queued_request.result(timeout=1)

        assert transport.send_count == 1

    def test_close_retries_transport_cleanup_after_failure(self):
        """A failed close keeps requests blocked but permits cleanup retry."""

        transport = MagicMock()
        transport.close.side_effect = [RuntimeError("terminate timed out"), None]
        client = MCPClient(transport)

        with pytest.raises(RuntimeError, match="terminate timed out"):
            client.close()
        with pytest.raises(RuntimeError, match="MCP client is closed"):
            client.list_tools()

        client.close()
        client.close()

        assert transport.close.call_count == 2
