"""MCP transport implementations."""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, List, Optional

from openjarvis.mcp.protocol import MCPRequest, MCPResponse

if TYPE_CHECKING:
    from openjarvis.mcp.server import MCPServer

logger = logging.getLogger(__name__)


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

    _STDOUT_QUEUE_SIZE = 1024
    _STDOUT_EOF = object()

    def __init__(
        self,
        command: List[str],
        *,
        response_timeout: float = 600.0,
    ) -> None:
        if response_timeout <= 0:
            raise ValueError("response_timeout must be positive")
        self._command = command
        self._response_timeout = response_timeout
        self._process: Optional[subprocess.Popen[str]] = None
        self._stdout_queue: queue.Queue[Any] = queue.Queue(
            maxsize=self._STDOUT_QUEUE_SIZE
        )
        self._reader_stop = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        # A single stdout stream cannot safely serve multiple independent
        # readers: one request could consume and discard another request's
        # response. Serialize complete write/read exchanges (and notification
        # writes) so response correlation remains lossless.
        self._request_lock = threading.Lock()
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
        self._reader_thread = threading.Thread(
            target=self._read_stdout,
            name="openjarvis-mcp-stdout",
            daemon=True,
        )
        self._reader_thread.start()
        # Nothing else reads stderr. Once the child writes more than the OS
        # pipe buffer to it, the child blocks on that write and never gets
        # to answer on stdout. Drain it continuously on a background thread.
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(self._process,),
            name="openjarvis-mcp-stderr",
            daemon=True,
        )
        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        """Read the subprocess pipe without tying up the request thread.

        A dedicated reader is portable to Windows, where ``select`` cannot
        wait on an anonymous subprocess pipe. The bounded queue also applies
        backpressure if a server writes stdout while no request is reading.
        """
        proc = self._process
        stdout = proc.stdout if proc is not None else None
        if stdout is None:
            return

        try:
            while not self._reader_stop.is_set():
                line = stdout.readline()
                if not line:
                    break
                while not self._reader_stop.is_set():
                    try:
                        self._stdout_queue.put(line, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        finally:
            while not self._reader_stop.is_set():
                try:
                    self._stdout_queue.put(self._STDOUT_EOF, timeout=0.1)
                    break
                except queue.Full:
                    continue

    def _next_stdout_line(self, deadline: float, request_id: Any) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"Timed out waiting for MCP response id {request_id!r}")
        try:
            item = self._stdout_queue.get(timeout=remaining)
        except queue.Empty as exc:
            raise RuntimeError(
                f"Timed out waiting for MCP response id {request_id!r}"
            ) from exc
        if item is self._STDOUT_EOF:
            raise RuntimeError("No response from subprocess")
        return item

    def _drain_stderr(self, proc: subprocess.Popen[str]) -> None:
        """Continuously read the child's stderr so its pipe never fills."""
        if proc.stderr is None:
            return
        for line in proc.stderr:
            line = line.rstrip("\n")
            if line:
                logger.debug("[%s stderr] %s", self._command[0], line)

    def send(self, request: MCPRequest) -> MCPResponse:
        """Write request as JSON line, read lines until the matching response.

        MCP servers may emit unsolicited notifications or stray/stale
        replies on stdout before the real response. Skip anything that
        isn't a well-formed JSON-RPC response carrying this request's id,
        rather than treating the first line as gospel (#751).
        """
        with self._request_lock:
            proc = self._process
            if proc is None or proc.stdin is None or proc.stdout is None:
                raise RuntimeError("Transport process is not running")

            line = request.to_json() + "\n"
            proc.stdin.write(line)
            proc.stdin.flush()

            deadline = time.monotonic() + self._response_timeout
            while True:
                # Check the wall-clock deadline even when a server continuously
                # floods stdout, so queued blank/noise/notification lines cannot
                # keep extending the request forever.
                response_line = self._next_stdout_line(deadline, request.id)
                response_line = response_line.strip()
                if not response_line:
                    continue

                try:
                    parsed = json.loads(response_line)
                except (json.JSONDecodeError, ValueError):
                    parsed = None

                is_response = (
                    isinstance(parsed, dict)
                    and "id" in parsed
                    and ("result" in parsed or "error" in parsed)
                    and parsed["id"] == request.id
                )
                if is_response:
                    return MCPResponse.from_json(response_line)

    def send_notification(self, request: MCPRequest) -> None:
        """Send a JSON-RPC notification — write only, never read.

        Overrides the base implementation: stdio servers do not reply
        to notifications, so the default ``send()`` would block forever
        on ``proc.stdout.readline()``.
        """
        with self._request_lock:
            proc = self._process
            if proc is None or proc.stdin is None:
                raise RuntimeError("Transport process is not running")
            line = request.to_json() + "\n"
            proc.stdin.write(line)
            proc.stdin.flush()

    def close(self) -> None:
        """Terminate the subprocess."""
        if self._process is not None:
            self._reader_stop.set()
            # Wake a request waiting on the queue before stopping the process.
            try:
                self._stdout_queue.put_nowait(self._STDOUT_EOF)
            except queue.Full:
                try:
                    self._stdout_queue.get_nowait()
                    self._stdout_queue.put_nowait(self._STDOUT_EOF)
                except (queue.Empty, queue.Full):
                    pass
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            if self._reader_thread is not None:
                self._reader_thread.join(timeout=1)
                self._reader_thread = None
            self._process = None
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=5)
            self._stderr_thread = None


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
        token: Optional[str] = None,
        connect_timeout: float = 10.0,
        request_timeout: float = 60.0,
    ) -> None:
        import httpx

        self._url = url
        self._token = token
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
        """Build common request headers.

        Sends ``Authorization: Bearer <token>`` when the transport was
        constructed with a token (#461) — required by authenticated MCP
        servers such as Home Assistant's. Falsy tokens (None / empty
        string) deliberately do NOT send the header, matching the
        upstream MCP spec and the cfg.get("token") plumbing in the
        builder.
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
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
