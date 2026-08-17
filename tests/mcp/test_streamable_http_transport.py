"""Tests for the StreamableHTTPTransport SDK connection description.

The official MCP Python SDK owns Streamable HTTP protocol I/O (session ids,
SSE framing, retries).  This transport is now only the description of *how* to
connect: endpoint, headers, timeout.
"""

from __future__ import annotations

import pytest

from openjarvis.mcp.protocol import MCPRequest


class TestStreamableHTTPTransport:
    def test_retains_endpoint(self):
        from openjarvis.mcp.transport import StreamableHTTPTransport

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        assert transport.url == "http://localhost:9583/mcp"

    def test_authorization_header_with_token(self):
        """Regression for #461 — token kwarg → Authorization: Bearer header."""
        from openjarvis.mcp.transport import StreamableHTTPTransport

        transport = StreamableHTTPTransport(
            "http://homeassistant.local:8123/mcp",
            token="ha-long-lived-token-xyz",
        )
        assert transport.headers == {"Authorization": "Bearer ha-long-lived-token-xyz"}

    def test_no_authorization_header_without_token(self):
        """Backward compat — no token kwarg → no Authorization header."""
        from openjarvis.mcp.transport import StreamableHTTPTransport

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        assert "Authorization" not in transport.headers

    def test_empty_token_does_not_send_header(self):
        """token='' → no Authorization (empty/falsy tokens skip the header).

        Matters because ``cfg.get('token')`` returns ``''`` if the user wrote
        ``token = ""`` in config.toml.  We don't want to send ``Authorization:
        Bearer `` (with a trailing space) — that's a malformed header that
        most servers reject with a confusing 400 rather than 401.
        """
        from openjarvis.mcp.transport import StreamableHTTPTransport

        transport = StreamableHTTPTransport("http://localhost:9583/mcp", token="")
        assert "Authorization" not in transport.headers

    def test_request_timeout_is_retained(self):
        from openjarvis.mcp.transport import StreamableHTTPTransport

        transport = StreamableHTTPTransport(
            "http://localhost:9583/mcp", request_timeout=42.0
        )
        assert transport.request_timeout == 42.0

    def test_constructor_creates_no_http_client(self):
        from openjarvis.mcp.transport import StreamableHTTPTransport

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        assert not hasattr(transport, "_client")

    def test_exposes_sdk_client_factory(self):
        from openjarvis.mcp.transport import StreamableHTTPTransport

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        assert callable(transport.sdk_client)

    def test_send_is_not_supported(self):
        from openjarvis.mcp.transport import StreamableHTTPTransport

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        with pytest.raises(NotImplementedError):
            transport.send(MCPRequest(method="tools/list", id=1))

    def test_close_is_idempotent(self):
        from openjarvis.mcp.transport import StreamableHTTPTransport

        transport = StreamableHTTPTransport("http://localhost:9583/mcp")
        transport.close()
        transport.close()

    def test_backward_compat_alias(self):
        """SSETransport should be the same class as StreamableHTTPTransport."""
        from openjarvis.mcp.transport import SSETransport, StreamableHTTPTransport

        assert SSETransport is StreamableHTTPTransport
