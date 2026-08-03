"""MCP Client — connects to MCP servers and discovers/calls tools."""

from __future__ import annotations

import itertools
from typing import Any, Dict, List

from openjarvis.mcp.protocol import (
    INVALID_REQUEST,
    MCP_PROTOCOL_VERSION,
    MCPError,
    MCPRequest,
    MCPResponse,
)
from openjarvis.mcp.transport import MCPTransport
from openjarvis.tools._stubs import ToolSpec


class MCPClient:
    """Client that communicates with an MCP server via a transport.

    Parameters
    ----------
    transport:
        The transport layer to use for communication.
    """

    _SUPPORTED_PROTOCOL_VERSIONS = frozenset(
        {MCP_PROTOCOL_VERSION, "2025-06-18", "2025-03-26"}
    )

    def __init__(self, transport: MCPTransport) -> None:
        self._transport = transport
        self._initialized = False
        self._capabilities: Dict[str, Any] = {}
        self._id_counter = itertools.count(1)

    def _next_id(self) -> int:
        return next(self._id_counter)

    def _send(self, method: str, params: Dict[str, Any] | None = None) -> MCPResponse:
        """Send a request and check for errors."""
        request = MCPRequest(
            method=method,
            params=params or {},
            id=self._next_id(),
        )
        response = self._transport.send(request)
        if response.id != request.id:
            raise MCPError(
                code=INVALID_REQUEST,
                message="MCP response ID did not match the request",
            )
        if response.error is not None:
            raise MCPError(
                code=response.error.get("code", -1),
                message=response.error.get("message", "Unknown error"),
                data=response.error.get("data"),
            )
        return response

    def initialize(self) -> Dict[str, Any]:
        """Perform the MCP initialize handshake.

        Sends the required client info and protocol version, then
        confirms with a ``notifications/initialized`` notification
        as required by the MCP specification.

        Returns the server capabilities.
        """
        params = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "openjarvis", "version": "0.1.0"},
        }
        response = self._send("initialize", params)
        if not isinstance(response.result, dict):
            raise MCPError(INVALID_REQUEST, "MCP initialize result must be an object")
        negotiated_version = str(response.result.get("protocolVersion", ""))
        if negotiated_version not in self._SUPPORTED_PROTOCOL_VERSIONS:
            self.close()
            raise MCPError(
                INVALID_REQUEST,
                "MCP server selected an unsupported protocol version",
            )
        capabilities = response.result.get("capabilities", {})
        if not isinstance(capabilities, dict):
            self.close()
            raise MCPError(INVALID_REQUEST, "MCP server capabilities must be an object")
        self._transport.set_protocol_version(negotiated_version)
        self._initialized = True
        self._capabilities = capabilities
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
        self._transport.send_notification(request)

    def list_tools(self) -> List[ToolSpec]:
        """Discover available tools from the server.

        Returns a list of ``ToolSpec`` objects.
        """
        response = self._send("tools/list")
        if not isinstance(response.result, dict):
            raise MCPError(INVALID_REQUEST, "MCP tools/list result must be an object")
        tools = response.result.get("tools", [])
        if not isinstance(tools, list) or len(tools) > 512:
            raise MCPError(INVALID_REQUEST, "MCP tool list is invalid or too large")
        # MCP tools often wrap long-running pentest/scan commands. The default
        # ToolSpec timeout (30s) kills them mid-scan. Bump to 600s — individual
        # MCP servers can shorten via their own protocol if needed.
        specs: List[ToolSpec] = []
        for item in tools:
            if not isinstance(item, dict):
                raise MCPError(INVALID_REQUEST, "MCP tool entry must be an object")
            name = item.get("name")
            description = item.get("description", "")
            parameters = item.get("inputSchema", {})
            if (
                not isinstance(name, str)
                or not name
                or len(name) > 200
                or not isinstance(description, str)
                or not isinstance(parameters, dict)
            ):
                raise MCPError(INVALID_REQUEST, "MCP tool metadata is invalid")
            specs.append(
                ToolSpec(
                    name=name,
                    description=description[:4096],
                    parameters=parameters,
                    timeout_seconds=600.0,
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
        response = self._send(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        if not isinstance(response.result, dict):
            raise MCPError(INVALID_REQUEST, "MCP tools/call result must be an object")
        return response.result

    def close(self) -> None:
        """Close the transport connection."""
        self._transport.close()

    def __enter__(self) -> MCPClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = ["MCPClient"]
