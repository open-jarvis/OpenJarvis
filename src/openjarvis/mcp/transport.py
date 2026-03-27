"""MCP transport implementations."""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, List, Optional

from openjarvis.mcp.protocol import MCPRequest, MCPResponse

if TYPE_CHECKING:
    from openjarvis.mcp.server import MCPServer


class MCPTransport(ABC):
    """Abstract transport layer for MCP communication."""

    @abstractmethod
    def send(self, request: MCPRequest) -> MCPResponse:
        """Send a request and return the response."""

    def send_notification(self, request: MCPRequest) -> None:
        """Send a JSON-RPC notification (no response expected).

        The default implementation delegates to :meth:`send` and discards the
        response.  Transports may override this when the server returns no
        body for notifications (e.g. HTTP 202 Accepted).
        """
        self.send(request)

    @abstractmethod
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
    """JSON-RPC over stdin/stdout subprocess transport.

    Launches a subprocess and communicates via JSON lines on
    stdin/stdout.
    """

    def __init__(self, command: List[str]) -> None:
        self._command = command
        self._process: Optional[subprocess.Popen[str]] = None
        self._start()

    def _start(self) -> None:
        """Start the subprocess."""
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def send(self, request: MCPRequest) -> MCPResponse:
        """Write request as JSON line, read response line."""
        proc = self._process
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError("Transport process is not running")

        line = request.to_json() + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()

        response_line = proc.stdout.readline()
        if not response_line:
            raise RuntimeError("No response from subprocess")
        return MCPResponse.from_json(response_line.strip())

    def close(self) -> None:
        """Terminate the subprocess."""
        if self._process is not None:
            self._process.terminate()
            self._process.wait(timeout=5)
            self._process = None


class StreamableHTTPTransport(MCPTransport):
    """MCP Streamable HTTP transport (JSON-RPC over HTTP).

    Uses a persistent ``httpx.Client`` session, tracks the
    ``Mcp-Session-Id`` header, and sends the ``Accept`` header
    required by the MCP Streamable HTTP specification.
    """

    def __init__(
        self,
        url: str,
        *,
        connect_timeout: float = 10.0,
        request_timeout: float = 60.0,
    ) -> None:
        import httpx

        self._url = url
        self._session_id: Optional[str] = None
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=connect_timeout,
                read=request_timeout,
                write=request_timeout,
                pool=connect_timeout,
            ),
        )

    def _safe_url(self) -> str:
        """Return scheme://host:port without path or query (avoids leaking tokens)."""
        from urllib.parse import urlparse

        parsed = urlparse(self._url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _build_headers(self) -> dict:
        """Build common request headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, request: MCPRequest) -> Any:
        """Post a request and return the raw httpx response."""
        import httpx

        headers = self._build_headers()
        try:
            response = self._client.post(
                self._url,
                json=request.to_dict(),
                headers=headers,
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Failed to connect to MCP server at {self._safe_url()}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Timeout communicating with MCP server at {self._safe_url()}: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"MCP server at {self._safe_url()} returned HTTP "
                f"{exc.response.status_code}"
            ) from exc

        # Track session id from the first response
        new_session_id = response.headers.get("mcp-session-id")
        if new_session_id is not None:
            self._session_id = new_session_id
        return response

    @staticmethod
    def _extract_json_from_sse(text: str) -> str:
        """Extract JSON payload from an SSE response body.

        MCP Streamable HTTP servers may respond with ``text/event-stream``
        instead of ``application/json``.  In that case the body looks like::

            event: message
            data: {"jsonrpc":"2.0", ...}

        This helper finds the last ``data:`` line and returns its content,
        which is the actual JSON-RPC response.
        """
        last_data = ""
        for line in text.splitlines():
            if line.startswith("data:"):
                last_data = line[len("data:") :].strip()
        if not last_data:
            raise RuntimeError(
                "SSE response contained no 'data:' lines"
                " — cannot extract JSON-RPC payload"
            )
        return last_data

    def send(self, request: MCPRequest) -> MCPResponse:
        """Send request via HTTP POST following the MCP Streamable HTTP spec.

        Handles both ``application/json`` and ``text/event-stream`` responses
        as allowed by the MCP Streamable HTTP specification.
        """
        response = self._post(request)
        content_type = response.headers.get("content-type", "")
        body = response.text
        if "text/event-stream" in content_type or body.lstrip().startswith("event:"):
            body = self._extract_json_from_sse(body)
        return MCPResponse.from_json(body)

    def send_notification(self, request: MCPRequest) -> None:
        """Send a notification — accept any 2xx, don't parse the body."""
        # Track session id but don't try to parse a JSON-RPC response.
        # Servers may return 202 Accepted with an empty body.
        self._post(request)

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()


# Backward-compatible alias
SSETransport = StreamableHTTPTransport


__all__ = [
    "InProcessTransport",
    "MCPTransport",
    "SSETransport",
    "StdioTransport",
    "StreamableHTTPTransport",
]
