"""MCP transport implementations."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, List, Mapping, Optional

from openjarvis.mcp.protocol import MCPRequest, MCPResponse

_MAX_RESPONSE_CHARS = 4 * 1024 * 1024
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024

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

    def set_protocol_version(self, version: str) -> None:
        """Record the negotiated protocol version when the transport needs it."""

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
        response_timeout: float = 60.0,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._command = command
        self._response_timeout = max(1.0, min(float(response_timeout), 120.0))
        self._environment = dict(environment) if environment is not None else None
        self._process: Optional[subprocess.Popen[str]] = None
        self._io_lock = threading.Lock()
        self._start()

    def _start(self) -> None:
        """Start the subprocess."""
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=self._environment,
        )

    def send(self, request: MCPRequest) -> MCPResponse:
        """Write request as JSON line, read response line."""
        proc = self._process
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError("Transport process is not running")

        with self._io_lock:
            line = request.to_json() + "\n"
            proc.stdin.write(line)
            proc.stdin.flush()
            for _ in range(128):
                response_line = self._readline(proc)
                if not response_line:
                    raise RuntimeError("No response from subprocess")
                try:
                    payload = json.loads(response_line)
                except json.JSONDecodeError as exc:
                    self.close()
                    raise RuntimeError("MCP stdio emitted invalid JSON") from exc
                messages = payload if isinstance(payload, list) else [payload]
                if not messages or any(not isinstance(item, dict) for item in messages):
                    self.close()
                    raise RuntimeError("MCP stdio emitted an invalid message")
                for message in messages:
                    if "method" in message:
                        if "id" in message:
                            reply = {"jsonrpc": "2.0", "id": message["id"]}
                            if message.get("method") == "ping":
                                reply["result"] = {}
                            else:
                                reply["error"] = {
                                    "code": -32601,
                                    "message": "Client method is not supported",
                                }
                            proc.stdin.write(json.dumps(reply) + "\n")
                            proc.stdin.flush()
                        continue
                    if "id" not in message:
                        self.close()
                        raise RuntimeError("MCP stdio response omitted its request ID")
                    if message["id"] != request.id:
                        self.close()
                        raise RuntimeError(
                            "MCP stdio response ID did not match the request"
                        )
                    return MCPResponse.from_json(json.dumps(message))
            self.close()
            raise RuntimeError("MCP stdio sent too many messages before its response")

    def _readline(self, proc: subprocess.Popen[str]) -> str:
        results: queue.Queue[object] = queue.Queue(maxsize=1)

        def read() -> None:
            try:
                results.put(
                    proc.stdout.readline(_MAX_RESPONSE_CHARS + 1)
                    if proc.stdout is not None
                    else ""
                )
            except Exception as exc:
                results.put(exc)

        threading.Thread(target=read, name="mcp-stdio-read", daemon=True).start()
        try:
            value = results.get(timeout=self._response_timeout)
        except queue.Empty as exc:
            self.close()
            raise RuntimeError("MCP stdio response timed out") from exc
        if isinstance(value, Exception):
            raise RuntimeError("MCP stdio response failed") from value
        response = str(value)
        if len(response) > _MAX_RESPONSE_CHARS or (
            len(response) == _MAX_RESPONSE_CHARS + 1 and not response.endswith("\n")
        ):
            self.close()
            raise RuntimeError("MCP stdio response exceeded the size limit")
        return response

    def send_notification(self, request: MCPRequest) -> None:
        """Send a JSON-RPC notification — write only, never read.

        Overrides the base implementation: stdio servers do not reply
        to notifications, so the default ``send()`` would block forever
        on ``proc.stdout.readline()``.
        """
        proc = self._process
        if proc is None or proc.stdin is None:
            raise RuntimeError("Transport process is not running")
        with self._io_lock:
            line = request.to_json() + "\n"
            proc.stdin.write(line)
            proc.stdin.flush()

    def close(self) -> None:
        """Terminate the subprocess."""
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
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
        token: Optional[str] = None,
        connect_timeout: float = 10.0,
        request_timeout: float = 60.0,
    ) -> None:
        import httpx

        self._url = url
        self._token = token
        self._session_id: Optional[str] = None
        self._protocol_version: Optional[str] = None
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
        if self._protocol_version is not None:
            headers["MCP-Protocol-Version"] = self._protocol_version
        return headers

    def set_protocol_version(self, version: str) -> None:
        """Use the negotiated version header on post-initialize requests."""

        if (
            len(version) != 10
            or version[4] != "-"
            or version[7] != "-"
            or not version.replace("-", "").isdigit()
        ):
            raise RuntimeError("MCP protocol version is invalid")
        self._protocol_version = version

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

        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise RuntimeError("MCP HTTP response exceeded the size limit")

        # Track session id from the first response
        new_session_id = response.headers.get("mcp-session-id")
        if new_session_id is not None:
            if (
                not new_session_id
                or len(new_session_id) > 1024
                or any(
                    not 0x21 <= ord(character) <= 0x7E for character in new_session_id
                )
            ):
                raise RuntimeError("MCP server returned an invalid session ID")
            self._session_id = new_session_id
        return response

    @staticmethod
    def _matching_response(payload: Any, request_id: int | str) -> str | None:
        messages = payload if isinstance(payload, list) else [payload]
        for message in messages:
            if (
                isinstance(message, dict)
                and message.get("id") == request_id
                and ("result" in message or "error" in message)
            ):
                return json.dumps(message)
        return None

    @classmethod
    def _extract_json_from_sse(cls, text: str, request_id: int | str) -> str:
        """Extract the matching response while ignoring preceding messages."""

        data_lines: list[str] = []
        saw_data = False
        for line in [*text.splitlines(), ""]:
            if line == "":
                if data_lines:
                    raw_payload = "\n".join(data_lines).strip()
                    data_lines = []
                    if raw_payload and raw_payload != "[DONE]":
                        try:
                            payload = json.loads(raw_payload)
                        except json.JSONDecodeError as exc:
                            raise RuntimeError(
                                "MCP SSE contained invalid JSON"
                            ) from exc
                        match = cls._matching_response(payload, request_id)
                        if match is not None:
                            return match
                continue
            if line.startswith("data:"):
                saw_data = True
                data_lines.append(line[len("data:") :].lstrip())
        if not saw_data:
            raise RuntimeError("MCP SSE response contained no data events")
        raise RuntimeError("MCP SSE stream contained no matching response")

    def send(self, request: MCPRequest) -> MCPResponse:
        """Send request via HTTP POST following the MCP Streamable HTTP spec.

        Handles both ``application/json`` and ``text/event-stream`` responses
        as allowed by the MCP Streamable HTTP specification.
        """
        response = self._post(request)
        content_type = response.headers.get("content-type", "")
        body = response.text
        if "text/event-stream" in content_type or body.lstrip().startswith(
            ("event:", "data:", "id:")
        ):
            body = self._extract_json_from_sse(body, request.id)
        else:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise RuntimeError("MCP HTTP response contained invalid JSON") from exc
            body = self._matching_response(payload, request.id) or ""
            if not body:
                raise RuntimeError("MCP HTTP response ID did not match the request")
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
