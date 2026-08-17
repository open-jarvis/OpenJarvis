"""MCP Client — connects to MCP servers and discovers/calls tools."""

from __future__ import annotations

import itertools
import threading
from typing import Any, Dict, List

from openjarvis.mcp.protocol import MCPError, MCPRequest, MCPResponse
from openjarvis.mcp.transport import MCPTransport
from openjarvis.tools._stubs import ToolSpec


class MCPClient:
    """Client that communicates with an MCP server via a transport.

    In-process transports keep the hand-written JSON-RPC path.  External
    transports (stdio, Streamable HTTP) are official SDK connection
    descriptions driven through one long-lived
    :class:`~openjarvis.mcp.runtime.MCPRuntime` session.  Public method
    signatures and return shapes are identical for both paths.

    Parameters
    ----------
    transport:
        The transport layer to use for communication.
    """

    def __init__(
        self,
        transport: MCPTransport,
        *,
        server_name: str = "",
    ) -> None:
        self._transport = transport
        self._server_name = server_name
        self._initialized = False
        self._capabilities: Dict[str, Any] = {}
        self._id_counter = itertools.count(1)
        self._runtime: Any = None
        # A client may be shared by server, scheduled, and channel agents.
        # Keep each transport request/response exchange atomic so stdio
        # readers cannot consume another thread's JSON-RPC response.
        self._request_lock = threading.RLock()
        # Closing must not wait for ``_request_lock``: transport.close() is
        # what interrupts a request that is blocked in a transport read.
        # An event lets queued requests fail before touching that transport,
        # while this separate lock keeps close itself idempotent.
        self._closed = threading.Event()
        self._transport_closed = threading.Event()
        self._close_lock = threading.Lock()
        # SDK connection descriptions override sdk_client(); the in-process
        # transport (and test doubles that speak MCPRequest) do not.
        self._external = isinstance(transport, MCPTransport) and (
            type(transport).sdk_client is not MCPTransport.sdk_client
        )

    def _ensure_runtime(self) -> Any:
        """Return the lazily created official-SDK runtime."""
        if self._runtime is None:
            self._raise_if_closed()
            from openjarvis.mcp.runtime import MCPRuntime

            self._runtime = MCPRuntime(self._transport)
        return self._runtime

    def _next_id(self) -> int:
        return next(self._id_counter)

    def _send(self, method: str, params: Dict[str, Any] | None = None) -> MCPResponse:
        """Send a request and check for errors."""
        with self._request_lock:
            self._raise_if_closed()
            request = MCPRequest(
                method=method,
                params=params or {},
                id=self._next_id(),
            )
            response = self._transport.send(request)
        if response.error is not None:
            raise MCPError(
                code=response.error.get("code", -1),
                message=response.error.get("message", "Unknown error"),
                data=response.error.get("data"),
            )
        return response

    def _raise_if_closed(self) -> None:
        if self._closed.is_set():
            raise RuntimeError("MCP client is closed")

    def initialize(self) -> Dict[str, Any]:
        """Perform the MCP initialize handshake.

        Sends the required client info and protocol version, then
        confirms with a ``notifications/initialized`` notification
        as required by the MCP specification.

        Returns the server capabilities.
        """
        if self._external:
            result = self._ensure_runtime().initialize()
            self._initialized = True
            self._capabilities = result.get("capabilities", {})
            return result

        params = {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "openjarvis", "version": "0.1.0"},
        }
        response = self._send("initialize", params)
        self._initialized = True
        self._capabilities = response.result.get("capabilities", {})
        # Send the required initialized notification per MCP spec
        self.notify("notifications/initialized")
        return response.result

    def notify(self, method: str, params: Dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected).

        Per JSON-RPC 2.0 spec, notifications omit the ``id`` field entirely.
        """
        request = MCPRequest(
            method=method,
            params=params or {},
            id=None,  # None → no id field in JSON (notification)
        )
        with self._request_lock:
            self._raise_if_closed()
            self._transport.send_notification(request)

    def list_tools(self) -> List[ToolSpec]:
        """Discover available tools from the server.

        Returns a list of ``ToolSpec`` objects.
        """
        if self._external:
            tools = self._ensure_runtime().list_tools()
        else:
            response = self._send("tools/list")
            tools = response.result.get("tools", [])
        # MCP tools often wrap long-running pentest/scan commands. The default
        # ToolSpec timeout (30s) kills them mid-scan. Bump to 600s — individual
        # MCP servers can shorten via their own protocol if needed.
        specs: list[ToolSpec] = []
        for tool in tools:
            annotations = tool.get("annotations", {})
            if not isinstance(annotations, dict):
                annotations = {}
            metadata: Dict[str, Any] = {}
            if self._server_name or annotations:
                metadata["mcp"] = {
                    "server": self._server_name,
                    "annotations": dict(annotations),
                }
            specs.append(
                ToolSpec(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    parameters=tool.get("inputSchema", {}),
                    timeout_seconds=600.0,
                    metadata=metadata,
                )
            )
        return specs

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Call a tool on the server.

        Returns the result dictionary with ``content`` and ``isError`` fields.
        """
        if self._external:
            from openjarvis.agents._stubs import register_agent_worker_cancellation

            runtime = self._ensure_runtime()
            # Only the active call is cancellable — discovery and finished
            # calls must never be dropped by a walked-away caller.
            unregister = register_agent_worker_cancellation(runtime.cancel_active_call)
            try:
                return runtime.call_tool(name, arguments or {})
            finally:
                unregister()

        response = self._send(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        return response.result

    def close(self) -> None:
        """Close the SDK session (if any) and the transport. Idempotent."""
        # Do not acquire _request_lock here. A transport request can be stuck
        # waiting for a server response, and closing the underlying transport
        # is the mechanism that unblocks it.
        with self._close_lock:
            if self._transport_closed.is_set():
                return
            self._closed.set()
            # The SDK session owns the transport on the external path, so it
            # closes first; its own close is what releases a blocked read.
            runtime, self._runtime = self._runtime, None
            if runtime is not None:
                runtime.close()
            self._transport.close()
            self._transport_closed.set()

    def __enter__(self) -> MCPClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = ["MCPClient"]
