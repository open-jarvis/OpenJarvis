"""Tests for MCP transport implementations."""

from __future__ import annotations

import json
import sys
import textwrap
from unittest.mock import MagicMock

import pytest

from openjarvis.mcp.protocol import MCPRequest
from openjarvis.mcp.server import MCPServer
from openjarvis.mcp.transport import InProcessTransport, SSETransport, StdioTransport
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
    def test_send_receive(self, tmp_path):
        """Use a simple Python echo script as the subprocess."""
        script = tmp_path / "echo_server.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            import json
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                req = json.loads(line)
                resp = {
                    "jsonrpc": "2.0",
                    "id": req.get("id", 0),
                    "result": {"echo": req.get("method", "")},
                }
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()
        """)
        )

        transport = StdioTransport([sys.executable, str(script)])
        try:
            req = MCPRequest(method="test/echo", id=1)
            resp = transport.send(req)
            assert resp.error is None
            assert resp.result["echo"] == "test/echo"
            assert resp.id == 1
        finally:
            transport.close()

    def test_multiple_requests(self, tmp_path):
        """Send multiple requests to the subprocess."""
        script = tmp_path / "echo_server.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            import json
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                req = json.loads(line)
                resp = {
                    "jsonrpc": "2.0",
                    "id": req.get("id", 0),
                    "result": {"method": req.get("method", "")},
                }
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()
        """)
        )

        transport = StdioTransport([sys.executable, str(script)])
        try:
            for i in range(3):
                req = MCPRequest(method=f"test/{i}", id=i)
                resp = transport.send(req)
                assert resp.result["method"] == f"test/{i}"
        finally:
            transport.close()

    def test_close_terminates_process(self, tmp_path):
        script = tmp_path / "sleep_server.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            import time
            time.sleep(300)
        """)
        )

        transport = StdioTransport([sys.executable, str(script)])
        proc = transport._process
        assert proc is not None
        assert proc.poll() is None  # still running
        transport.close()
        assert transport._process is None

    def test_close_idempotent(self, tmp_path):
        script = tmp_path / "sleep_server.py"
        script.write_text("import time; time.sleep(300)")
        transport = StdioTransport([sys.executable, str(script)])
        transport.close()
        transport.close()  # Should not raise


class TestSSETransport:
    def test_send_receive(self, monkeypatch):
        """Mock httpx to simulate HTTP response."""
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        )
        mock_response.raise_for_status = MagicMock()

        mock_httpx = MagicMock()
        mock_httpx.post.return_value = mock_response
        monkeypatch.setitem(sys.modules, "httpx", mock_httpx)

        transport = SSETransport("http://localhost:8080/mcp")
        req = MCPRequest(method="tools/list", id=1)
        resp = transport.send(req)
        assert resp.error is None
        assert resp.result == {"tools": []}

    def test_send_posts_json(self, monkeypatch):
        """Verify the HTTP POST includes correct headers and body."""
        mock_response = MagicMock()
        mock_response.text = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
        mock_response.raise_for_status = MagicMock()

        mock_httpx = MagicMock()
        mock_httpx.post.return_value = mock_response
        monkeypatch.setitem(sys.modules, "httpx", mock_httpx)

        transport = SSETransport("http://localhost:8080/mcp")
        req = MCPRequest(method="initialize", id=1)
        transport.send(req)

        call_args = mock_httpx.post.call_args
        assert call_args[0][0] == "http://localhost:8080/mcp"
        assert call_args[1]["headers"]["Content-Type"] == "application/json"

    def test_close_is_noop(self):
        transport = SSETransport("http://localhost:8080/mcp")
        transport.close()  # Should not raise

    def test_error_response(self, monkeypatch):
        """Simulate server returning an error response."""
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32601, "message": "Not found"},
            }
        )
        mock_response.raise_for_status = MagicMock()

        mock_httpx = MagicMock()
        mock_httpx.post.return_value = mock_response
        monkeypatch.setitem(sys.modules, "httpx", mock_httpx)

        transport = SSETransport("http://localhost:8080/mcp")
        req = MCPRequest(method="unknown", id=1)
        resp = transport.send(req)
        assert resp.error is not None
        assert resp.error["code"] == -32601
