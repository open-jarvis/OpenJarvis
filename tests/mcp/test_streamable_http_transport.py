"""Tests for the StreamableHTTPTransport class."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.mcp.protocol import MCPRequest


@pytest.fixture
def _mock_httpx_client():
    """Patch httpx.Client so no real HTTP connections are made."""
    with patch("httpx.Client") as mock_cls, patch("httpx.Timeout"):
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _make_http_response(result, *, session_id=None):
    """Build a mock httpx.Response with the given JSON-RPC result."""
    resp = MagicMock()
    resp.text = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})
    resp.raise_for_status = MagicMock()
    headers = {}
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    resp.headers = headers
    return resp


class TestStreamableHTTPTransport:
    def test_send_request(self, _mock_httpx_client):
        """Verify correct URL, headers, JSON body, and MCPResponse parsing."""
        from openjarvis.mcp.transport import StreamableHTTPTransport

        mock_client = _mock_httpx_client
        mock_client.post.return_value = _make_http_response({"tools": []})

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        req = MCPRequest(method="tools/list", id=1)
        resp = transport.send(req)

        # Verify the POST call
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == "http://localhost:9583/mcp"
        headers = call_kwargs[1]["headers"]
        assert headers["Content-Type"] == "application/json"
        assert "application/json" in headers["Accept"]
        assert "text/event-stream" in headers["Accept"]

        # Verify JSON body matches the request
        sent_json = call_kwargs[1]["json"]
        assert sent_json["method"] == "tools/list"
        assert sent_json["id"] == 1
        assert sent_json["jsonrpc"] == "2.0"

        # Verify response parsing
        assert resp.error is None
        assert resp.result == {"tools": []}

    def test_session_id_tracking(self, _mock_httpx_client):
        """First response sets Mcp-Session-Id, subsequent requests include it."""
        from openjarvis.mcp.transport import StreamableHTTPTransport

        mock_client = _mock_httpx_client
        # First response sets the session id
        mock_client.post.return_value = _make_http_response(
            {"capabilities": {}}, session_id="sess-abc-123"
        )

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        req1 = MCPRequest(method="initialize", id=1)
        transport.send(req1)

        assert transport._session_id == "sess-abc-123"

        # Second request — prepare new response without session header
        mock_client.post.return_value = _make_http_response({"tools": []})
        req2 = MCPRequest(method="tools/list", id=2)
        transport.send(req2)

        # Verify the second call included the session id header
        second_call_headers = mock_client.post.call_args[1]["headers"]
        assert second_call_headers["Mcp-Session-Id"] == "sess-abc-123"

    def test_first_request_has_no_session_id(self, _mock_httpx_client):
        """First request should not include Mcp-Session-Id header."""
        from openjarvis.mcp.transport import StreamableHTTPTransport

        mock_client = _mock_httpx_client
        mock_client.post.return_value = _make_http_response({})

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        transport.send(MCPRequest(method="initialize", id=1))

        first_call_headers = mock_client.post.call_args[1]["headers"]
        assert "Mcp-Session-Id" not in first_call_headers

    def test_connect_error_handling(self, _mock_httpx_client):
        """httpx.ConnectError should be wrapped in RuntimeError."""
        import httpx

        from openjarvis.mcp.transport import StreamableHTTPTransport

        mock_client = _mock_httpx_client
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        with pytest.raises(RuntimeError, match="Failed to connect"):
            transport.send(MCPRequest(method="initialize", id=1))

    def test_timeout_error_handling(self, _mock_httpx_client):
        """httpx.TimeoutException should be wrapped in RuntimeError."""
        import httpx

        from openjarvis.mcp.transport import StreamableHTTPTransport

        mock_client = _mock_httpx_client
        mock_client.post.side_effect = httpx.TimeoutException("Read timed out")

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        with pytest.raises(RuntimeError, match="Timeout communicating"):
            transport.send(MCPRequest(method="initialize", id=1))

    def test_close(self, _mock_httpx_client):
        """close() should close the underlying httpx client."""
        from openjarvis.mcp.transport import StreamableHTTPTransport

        mock_client = _mock_httpx_client
        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        transport.close()
        mock_client.close.assert_called_once()

    def test_backward_compat_alias(self):
        """SSETransport should be the same class as StreamableHTTPTransport."""
        from openjarvis.mcp.transport import SSETransport, StreamableHTTPTransport

        assert SSETransport is StreamableHTTPTransport
