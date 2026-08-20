"""Tests for MCP transport implementations."""

from __future__ import annotations

import json
import sys
import textwrap
import time
from unittest.mock import MagicMock, patch

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

    def test_concurrent_requests_remain_correlated(self, tmp_path):
        """Concurrent callers cannot consume one another's response lines."""
        import threading

        script = tmp_path / "concurrent_echo_server.py"
        script.write_text(
            textwrap.dedent("""\
            import json
            import sys
            import time

            for line in sys.stdin:
                request = json.loads(line)
                time.sleep(0.005)
                response = {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {"method": request["method"]},
                }
                sys.stdout.write(json.dumps(response) + "\\n")
                sys.stdout.flush()
        """)
        )

        transport = StdioTransport([sys.executable, str(script)], response_timeout=2.0)
        barrier = threading.Barrier(12)
        responses: dict[int, str] = {}
        errors: list[Exception] = []

        def call(request_id: int) -> None:
            try:
                barrier.wait(timeout=2)
                response = transport.send(
                    MCPRequest(method=f"test/{request_id}", id=request_id)
                )
                responses[request_id] = response.result["method"]
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        workers = [threading.Thread(target=call, args=(index,)) for index in range(12)]
        try:
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)

            assert not errors
            assert not any(worker.is_alive() for worker in workers)
            assert responses == {index: f"test/{index}" for index in range(12)}
        finally:
            transport.close()

    def test_skips_unsolicited_notification_before_response(self, tmp_path):
        """Regression for #751: a server-emitted notification (no ``id``)
        arriving on stdout before the real response must not be mistaken
        for that response.

        The old ``send()`` read exactly one line and handed it straight to
        ``MCPResponse.from_json()``. A notification has neither ``result``
        nor ``error``, so it parsed as ``MCPResponse(result=None,
        error=None)`` -- silently wrong instead of erroring -- and the real
        response was left unread in the pipe, desyncing every later call.
        """
        script = tmp_path / "noisy_notify_server.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            import json
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                req = json.loads(line)
                # Unsolicited notification (no "id") before the real reply.
                notice = {
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {"progress": 1},
                }
                sys.stdout.write(json.dumps(notice) + "\\n")
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
            assert resp.result == {"echo": "test/echo"}
            assert resp.id == 1

            # The stream must be back in sync for the next call too.
            req2 = MCPRequest(method="test/echo2", id=2)
            resp2 = transport.send(req2)
            assert resp2.result == {"echo": "test/echo2"}
        finally:
            transport.close()

    def test_skips_response_with_stale_id(self, tmp_path):
        """A response line whose id doesn't match the outstanding request
        (e.g. a stale/duplicate reply) must be skipped, not returned."""
        script = tmp_path / "stale_id_server.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            import json
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                req = json.loads(line)
                stale = {"jsonrpc": "2.0", "id": 999, "result": {"stale": True}}
                sys.stdout.write(json.dumps(stale) + "\\n")
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
            assert resp.result == {"echo": "test/echo"}
            assert resp.id == 1
        finally:
            transport.close()

    def test_skips_non_json_banner_before_response(self, tmp_path):
        """Regression for #752: a stray non-JSON line on stdout (e.g. an
        npm warning banner from a server launched via ``npx -y`` on a cold
        cache) must be skipped, not treated as a fatal parse error that
        drops discovery for the whole server.
        """
        script = tmp_path / "npm_banner_server.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            import json

            # Simulates an npm warning banner printed before the server
            # starts speaking JSON-RPC.
            sys.stdout.write("npm warn deprecated some-pkg@1.0.0: use v2\\n")
            sys.stdout.write("Fetching latest version...\\n")
            sys.stdout.flush()

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
            req = MCPRequest(method="initialize", id=1)
            resp = transport.send(req)
            assert resp.error is None
            assert resp.result == {"echo": "initialize"}
        finally:
            transport.close()

    def test_response_deadline_bounds_nonmatching_lines(self, tmp_path):
        """Noise cannot keep extending the wall-clock response deadline."""
        script = tmp_path / "never_replies_server.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            import json
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                # Never answers with a matching id -- just noise, forever.
                for _ in range(2000):
                    notice = {"jsonrpc": "2.0", "method": "notifications/progress"}
                    sys.stdout.write(json.dumps(notice) + "\\n")
                sys.stdout.flush()
        """)
        )

        transport = StdioTransport([sys.executable, str(script)], response_timeout=0.25)
        try:
            req = MCPRequest(method="test/echo", id=1)
            started = time.monotonic()
            with pytest.raises(RuntimeError, match="Timed out waiting"):
                transport.send(req)
            assert time.monotonic() - started < 2
        finally:
            transport.close()

    def test_response_deadline_bounds_blank_line_flood(self, tmp_path):
        """Blank lines are ignored, but cannot make send() wait forever."""
        script = tmp_path / "blank_line_server.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            for line in sys.stdin:
                while True:
                    sys.stdout.write("\\n")
                    sys.stdout.flush()
        """)
        )

        transport = StdioTransport([sys.executable, str(script)], response_timeout=0.25)
        try:
            started = time.monotonic()
            with pytest.raises(RuntimeError, match="Timed out waiting"):
                transport.send(MCPRequest(method="test/echo", id=1))
            assert time.monotonic() - started < 2
        finally:
            transport.close()

    def test_valid_response_survives_large_notification_burst(self, tmp_path):
        """Valid protocol traffic is not rejected by an arbitrary line cap."""
        script = tmp_path / "notification_burst_server.py"
        script.write_text(
            textwrap.dedent("""\
            import json
            import sys
            for line in sys.stdin:
                request = json.loads(line)
                for index in range(1200):
                    notification = {
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": {"progress": index},
                    }
                    sys.stdout.write(json.dumps(notification) + "\\n")
                response = {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {"complete": True},
                }
                sys.stdout.write(json.dumps(response) + "\\n")
                sys.stdout.flush()
        """)
        )

        transport = StdioTransport([sys.executable, str(script)], response_timeout=5)
        try:
            response = transport.send(MCPRequest(method="test/echo", id=1))
            assert response.result == {"complete": True}
        finally:
            transport.close()

    def test_response_deadline_bounds_silent_server(self, tmp_path):
        script = tmp_path / "silent_server.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            import time
            for line in sys.stdin:
                time.sleep(300)
        """)
        )

        transport = StdioTransport([sys.executable, str(script)], response_timeout=0.25)
        try:
            started = time.monotonic()
            with pytest.raises(RuntimeError, match="Timed out waiting"):
                transport.send(MCPRequest(method="test/echo", id=1))
            assert time.monotonic() - started < 2
        finally:
            transport.close()

    def test_send_notification_does_not_read_stdout(self, tmp_path):
        """Regression for #339: stdio servers don't reply to notifications.

        The base ``MCPTransport.send_notification`` falls back to ``send()``,
        which writes the request and then blocks on ``proc.stdout.readline()``.
        For stdio MCP servers that never reply to a notification, that read
        hangs forever, breaking the JSON-RPC ``notifications/initialized``
        handshake. ``StdioTransport.send_notification`` must override that
        behavior to be write-only.

        This test spawns a subprocess that consumes stdin without ever
        writing to stdout, then issues ``send_notification`` from a worker
        thread. If the override is missing, the thread blocks on
        ``readline()`` and the join timeout fires.
        """
        import threading

        script = tmp_path / "silent_consumer.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            for _ in sys.stdin:
                pass
        """)
        )

        transport = StdioTransport([sys.executable, str(script)])
        try:
            notification = MCPRequest(method="notifications/initialized")
            result_box: dict = {}

            def call():
                try:
                    transport.send_notification(notification)
                    result_box["ok"] = True
                except Exception as exc:  # noqa: BLE001
                    result_box["error"] = exc

            worker = threading.Thread(target=call, daemon=True)
            worker.start()
            worker.join(timeout=2.0)
            assert not worker.is_alive(), (
                "send_notification blocked on stdout — override missing"
            )
            assert result_box.get("ok") is True, result_box
        finally:
            transport.close()

    def test_survives_large_stderr_output(self, tmp_path):
        """Regression for #750: a child that fills the stderr pipe buffer
        before responding on stdout must not deadlock the transport.

        ``StdioTransport`` spawns the child with ``stderr=subprocess.PIPE``
        but nothing drains it. Once the child writes more than the OS pipe
        buffer to stderr, its write blocks and it never gets to read stdin
        or answer on stdout, so ``proc.stdout.readline()`` hangs forever.
        """
        import threading

        script = tmp_path / "noisy_server.py"
        script.write_text(
            textwrap.dedent("""\
            import sys
            import json

            # Write well past any OS pipe buffer before touching stdin.
            for _ in range(20000):
                sys.stderr.write("noisy line filling the pipe buffer\\n")
            sys.stderr.flush()

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
            result_box: dict = {}

            def call():
                try:
                    req = MCPRequest(method="test/echo", id=1)
                    result_box["resp"] = transport.send(req)
                except Exception as exc:  # noqa: BLE001
                    result_box["error"] = exc

            worker = threading.Thread(target=call, daemon=True)
            worker.start()
            worker.join(timeout=10.0)
            assert not worker.is_alive(), (
                "send() deadlocked on a full stderr pipe buffer"
            )
            assert "error" not in result_box, result_box.get("error")
            resp = result_box["resp"]
            assert resp.error is None
            assert resp.result["echo"] == "test/echo"
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
