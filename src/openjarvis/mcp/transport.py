"""MCP transport implementations.

Two kinds of transport live here:

* ``InProcessTransport`` speaks OpenJarvis's own JSON-RPC objects directly to
  an in-process :class:`~openjarvis.mcp.server.MCPServer` — no protocol I/O.
* ``StdioTransport`` and ``StreamableHTTPTransport`` are *connection
  descriptions* for the official MCP Python SDK.  They hold the command,
  endpoint, headers, and timeouts; the SDK owns process launch, framing,
  session ids, SSE parsing, and teardown via :mod:`openjarvis.mcp.runtime`.
"""

from __future__ import annotations

import os
from abc import ABC
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from openjarvis.mcp.protocol import MCPRequest, MCPResponse

if TYPE_CHECKING:
    from openjarvis.mcp.server import MCPServer


class MCPTransport(ABC):
    """Abstract transport layer for MCP communication.

    A transport implements *either* :meth:`send` (in-process JSON-RPC) or
    :meth:`sdk_client` (an official SDK connection); the unimplemented half
    raises ``NotImplementedError`` so both kinds stay instantiable.
    """

    def send(self, request: MCPRequest) -> MCPResponse:
        """Send a request and return the response."""
        raise NotImplementedError(
            f"{type(self).__name__} has no in-process request path; "
            "use sdk_client() through MCPRuntime"
        )

    def send_notification(self, request: MCPRequest) -> None:
        """Send a JSON-RPC notification (no response expected).

        The default implementation delegates to :meth:`send` and discards the
        response.  Transports may override this when the server returns no
        body for notifications (e.g. HTTP 202 Accepted).
        """
        self.send(request)

    def sdk_client(self) -> Any:
        """Return an async context manager yielding official SDK streams."""
        raise NotImplementedError(
            f"{type(self).__name__} is not an official SDK connection description"
        )

    def close(self) -> None:
        """Release transport resources."""


class InProcessTransport(MCPTransport):
    """Direct in-process transport for testing.

    Routes requests directly to an ``MCPServer`` instance without
    serialization overhead.
    """

    def __init__(self, server: MCPServer) -> None:
        self._server = server

    def send(self, request: MCPRequest) -> MCPResponse:
        """Dispatch request directly to the server."""
        return self._server.handle(request)

    def close(self) -> None:
        """No resources to release."""


class StdioTransport(MCPTransport):
    """Description of an MCP server launched over stdio.

    The official SDK's ``stdio_client`` owns the subprocess: constructing this
    class launches nothing and holds no file descriptors.
    """

    def __init__(self, command: List[str]) -> None:
        if not command:
            raise ValueError("StdioTransport requires a non-empty command")
        self.command = command[0]
        self.args = list(command[1:])

    def sdk_client(self) -> Any:
        """Return the official stdio client context manager."""
        from mcp.client.stdio import stdio_client

        from mcp import StdioServerParameters

        # Inherit the full environment, as the previous subprocess.Popen
        # transport did. The SDK's default is a small whitelist that drops
        # DISPLAY/WAYLAND_DISPLAY, which silently forces a headed browser
        # server (Playwright MCP) into headless mode.
        return stdio_client(
            StdioServerParameters(
                command=self.command, args=self.args, env=dict(os.environ)
            )
        )


class StreamableHTTPTransport(MCPTransport):
    """Description of an MCP server reached over Streamable HTTP.

    The official SDK's ``streamablehttp_client`` owns the HTTP client, the
    ``Mcp-Session-Id`` lifecycle, and SSE framing.
    """

    def __init__(
        self,
        url: str,
        *,
        token: Optional[str] = None,
        connect_timeout: float = 10.0,
        request_timeout: float = 60.0,
    ) -> None:
        self.url = url
        # Falsy tokens (None / empty string) deliberately send no header (#461):
        # `Authorization: Bearer ` is malformed and yields a confusing 400.
        self.headers: Dict[str, str] = (
            {"Authorization": f"Bearer {token}"} if token else {}
        )
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout

    def sdk_client(self) -> Any:
        """Return the official Streamable HTTP client context manager."""
        from mcp.client.streamable_http import streamablehttp_client

        return streamablehttp_client(
            self.url,
            headers=self.headers,
            timeout=timedelta(seconds=self.request_timeout),
        )


# Backward-compatible alias
SSETransport = StreamableHTTPTransport


__all__ = [
    "InProcessTransport",
    "MCPTransport",
    "SSETransport",
    "StdioTransport",
    "StreamableHTTPTransport",
]
