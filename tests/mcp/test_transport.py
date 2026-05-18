"""Tests for MCP transport implementations."""

from __future__ import annotations

import json
import sys
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.mcp.protocol import MCPRequest
from openjarvis.mcp.client import MCPClient
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

    def test_send_times_out_when_subprocess_is_silent(self, tmp_path):
        script = tmp_path / "silent_server.py"
        script.write_text(
            textwrap.dedent("""\
            import time
            while True:
                time.sleep(1)
        """)
        )

        transport = StdioTransport(
            [sys.executable, str(script)],
            response_timeout=0.2,
        )
        try:
            req = MCPRequest(method="test/timeout", id=99)
            with pytest.raises(RuntimeError, match="Timeout waiting for MCP stdio"):
                transport.send(req)
        finally:
            transport.close()

    def test_content_length_framing_when_explicitly_requested(self, tmp_path):
        script = tmp_path / "content_length_server.py"
        script.write_text(
            textwrap.dedent("""\
            import json
            import sys

            def read_headers(stdin):
                headers = {}
                while True:
                    line = stdin.readline()
                    if not line or line in ("\\n", "\\r\\n"):
                        break
                    if ":" not in line:
                        continue
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
                return headers

            while True:
                headers = read_headers(sys.stdin)
                if not headers:
                    break
                length = int(headers.get("content-length", "0"))
                if length <= 0:
                    continue
                body = sys.stdin.read(length)
                req = json.loads(body)
                resp = {
                    "jsonrpc": "2.0",
                    "id": req.get("id", 0),
                    "result": {"ok": True, "method": req.get("method", "")},
                }
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()
        """)
        )

        transport = StdioTransport(
            [sys.executable, str(script)],
            message_framing="content-length",
        )
        try:
            req = MCPRequest(method="initialize", id=5)
            resp = transport.send(req)
            assert resp.error is None
            assert resp.result["ok"] is True
            assert resp.result["method"] == "initialize"
        finally:
            transport.close()

    def test_initialize_retries_once_on_timeout(self, tmp_path):
        script = tmp_path / "drop_first_request.py"
        script.write_text(
            textwrap.dedent("""\
            import json
            import sys

            first = True
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                req = json.loads(line)
                if first:
                    first = False
                    # Simulate startup race: silently drop first request.
                    continue
                resp = {
                    "jsonrpc": "2.0",
                    "id": req.get("id", 0),
                    "result": {"ok": True},
                }
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()
        """)
        )

        transport = StdioTransport(
            [sys.executable, str(script)],
            response_timeout=0.2,
        )
        try:
            req = MCPRequest(method="initialize", id=7)
            resp = transport.send(req)
            assert resp.error is None
            assert resp.result["ok"] is True
        finally:
            transport.close()

    def test_notification_does_not_wait_for_response(self, tmp_path):
        script = tmp_path / "init_no_notification_response.py"
        script.write_text(
            textwrap.dedent("""\
            import json
            import sys

            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                req = json.loads(line)
                if req.get("method") == "initialize":
                    resp = {
                        "jsonrpc": "2.0",
                        "id": req.get("id", 0),
                        "result": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "serverInfo": {"name": "test", "version": "0.1"},
                        },
                    }
                    sys.stdout.write(json.dumps(resp) + "\\n")
                    sys.stdout.flush()
                # For notifications and all other methods: intentionally no stdout.
        """)
        )

        transport = StdioTransport([sys.executable, str(script)], response_timeout=0.5)
        client = MCPClient(transport)
        try:
            result = client.initialize()
            assert result["serverInfo"]["name"] == "test"
        finally:
            transport.close()


class TestStreamableHTTPTransport:
    """Tests for StreamableHTTPTransport (also aliased as SSETransport)."""

    def _make_mock_response(self, body: dict) -> MagicMock:
        """Create a mock httpx.Response with the given JSON body."""
        mock_response = MagicMock()
        mock_response.text = json.dumps(body)
        mock_response.headers = {}
        mock_response.raise_for_status = MagicMock()
        return mock_response

    @patch("httpx.Client")
    def test_send_receive(self, mock_client_cls):
        """Mock httpx.Client to simulate HTTP response."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.post.return_value = self._make_mock_response(
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        )

        transport = StreamableHTTPTransport("http://localhost:8080/mcp")
        req = MCPRequest(method="tools/list", id=1)
        resp = transport.send(req)
        assert resp.error is None
        assert resp.result == {"tools": []}

    @patch("httpx.Client")
    def test_send_posts_json(self, mock_client_cls):
        """Verify the HTTP POST includes correct headers and body."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.post.return_value = self._make_mock_response(
            {"jsonrpc": "2.0", "id": 1, "result": {}}
        )

        transport = StreamableHTTPTransport("http://localhost:8080/mcp")
        req = MCPRequest(method="initialize", id=1)
        transport.send(req)

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:8080/mcp"
        assert call_args[1]["headers"]["Content-Type"] == "application/json"

    @patch("httpx.Client")
    def test_close_closes_client(self, mock_client_cls):
        """close() should close the underlying httpx.Client."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        transport = StreamableHTTPTransport("http://localhost:8080/mcp")
        transport.close()
        mock_client.close.assert_called_once()

    @patch("httpx.Client")
    def test_error_response(self, mock_client_cls):
        """Simulate server returning an error response."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.post.return_value = self._make_mock_response(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32601, "message": "Not found"},
            }
        )

        transport = StreamableHTTPTransport("http://localhost:8080/mcp")
        req = MCPRequest(method="unknown", id=1)
        resp = transport.send(req)
        assert resp.error is not None
        assert resp.error["code"] == -32601

    @patch("httpx.Client")
    def test_session_id_tracking(self, mock_client_cls):
        """Verify Mcp-Session-Id is tracked from response and sent on subsequent
        requests."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # First response sets a session id
        first_response = self._make_mock_response(
            {"jsonrpc": "2.0", "id": 1, "result": {}}
        )
        first_response.headers = {"mcp-session-id": "sess-abc-123"}

        # Second response
        second_response = self._make_mock_response(
            {"jsonrpc": "2.0", "id": 2, "result": {}}
        )
        second_response.headers = {}

        mock_client.post.side_effect = [first_response, second_response]

        transport = StreamableHTTPTransport("http://localhost:8080/mcp")
        transport.send(MCPRequest(method="initialize", id=1))
        assert transport._session_id == "sess-abc-123"

        transport.send(MCPRequest(method="tools/list", id=2))
        # Second call should include session id in headers
        second_call_headers = mock_client.post.call_args_list[1][1]["headers"]
        assert second_call_headers["Mcp-Session-Id"] == "sess-abc-123"

    def test_sse_transport_alias(self):
        """SSETransport should be an alias for StreamableHTTPTransport."""
        assert SSETransport is StreamableHTTPTransport
