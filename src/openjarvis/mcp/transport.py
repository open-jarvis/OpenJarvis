"""MCP transport implementations."""

from __future__ import annotations

import subprocess
import select
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

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

    def __init__(
        self,
        command: List[str],
        *,
        env: Optional[Dict[str, str]] = None,
        response_timeout: float = 30.0,
        message_framing: Literal["auto", "jsonl", "content-length"] = "auto",
    ) -> None:
        self._command = command
        self._extra_env = dict(env) if env else {}
        self._response_timeout = max(0.1, float(response_timeout))
        self._message_framing = self._resolve_message_framing(message_framing)
        self._process: Optional[subprocess.Popen[str]] = None
        self._start()

    def _resolve_message_framing(
        self,
        requested: Literal["auto", "jsonl", "content-length"],
    ) -> Literal["jsonl", "content-length"]:
        """Resolve stdio framing mode.

        ``auto`` defaults to JSONL for compatibility with common MCP stdio
        servers. Content-Length framing can be selected explicitly via
        ``message_framing='content-length'`` for servers that require it.
        """
        if requested in ("jsonl", "content-length"):
            return requested

        return "jsonl"

    def _start(self) -> None:
        """Start the subprocess."""
        import os

        proc_env = os.environ.copy()
        for key, value in self._extra_env.items():
            proc_env[key] = str(value)
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=proc_env,
        )

    def send(self, request: MCPRequest) -> MCPResponse:
        """Write request and read response.

        Some stdio MCP servers (notably Node/npm ones) can drop the very first
        request while still booting. For ``initialize``, we retry once on
        timeout if the process is still alive.
        """
        proc = self._process
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError("Transport process is not running")

        max_attempts = 2 if request.method == "initialize" else 1
        last_timeout: RuntimeError | None = None

        for attempt in range(1, max_attempts + 1):
            payload = request.to_json()
            if self._message_framing == "content-length":
                msg = (
                    f"Content-Length: {len(payload.encode('utf-8'))}\r\n\r\n{payload}"
                )
            else:
                msg = payload + "\n"
            proc.stdin.write(msg)
            proc.stdin.flush()
            try:
                ready, _, _ = select.select([proc.stdout], [], [], self._response_timeout)
            except Exception as exc:
                last_timeout = RuntimeError(
                    "Timeout waiting for MCP stdio response from "
                    f"{self._command!r} after {self._response_timeout:.1f}s"
                )
                if attempt < max_attempts and proc.poll() is None:
                    continue
                raise last_timeout from exc
            if not ready:
                last_timeout = RuntimeError(
                    "Timeout waiting for MCP stdio response from "
                    f"{self._command!r} after {self._response_timeout:.1f}s"
                )
                if attempt < max_attempts and proc.poll() is None:
                    continue
                raise last_timeout

            response_line = proc.stdout.readline()
            if not response_line:
                if proc.poll() is not None:
                    stderr_note = ""
                    if proc.stderr is not None:
                        try:
                            stderr_text = (proc.stderr.read() or "").strip()
                        except Exception:
                            stderr_text = ""
                        if stderr_text:
                            stderr_note = f" stderr: {stderr_text[:400]}"
                    raise RuntimeError(
                        "No response from subprocess; process exited "
                        f"with code {proc.returncode}.{stderr_note}"
                    )
                raise RuntimeError("No response from subprocess")

            stripped = response_line.strip()
            if stripped.lower().startswith("content-length:"):
                try:
                    content_length = int(stripped.split(":", 1)[1].strip())
                except (IndexError, ValueError) as exc:
                    raise RuntimeError(
                        f"Invalid Content-Length header from subprocess: {stripped!r}"
                    ) from exc

                # Consume remaining headers until blank line.
                while True:
                    header_line = proc.stdout.readline()
                    if not header_line or header_line in ("\n", "\r\n"):
                        break
                body = proc.stdout.read(content_length)
                if not body:
                    raise RuntimeError("No response body after Content-Length header")
                return MCPResponse.from_json(body.strip())

            return MCPResponse.from_json(stripped)

        if last_timeout is not None:
            raise last_timeout
        raise RuntimeError("MCP stdio request failed without response")

    def send_notification(self, request: MCPRequest) -> None:
        """Send JSON-RPC notification over stdio without waiting for response."""
        proc = self._process
        if proc is None or proc.stdin is None:
            raise RuntimeError("Transport process is not running")
        payload = request.to_json()
        if self._message_framing == "content-length":
            msg = f"Content-Length: {len(payload.encode('utf-8'))}\r\n\r\n{payload}"
        else:
            msg = payload + "\n"
        proc.stdin.write(msg)
        proc.stdin.flush()

    def close(self) -> None:
        """Terminate the subprocess."""
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
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
