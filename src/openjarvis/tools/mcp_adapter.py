"""MCP tool adapter — wraps external MCP server tools as native BaseTool instances."""

from __future__ import annotations

from typing import Any, List

from openjarvis.core.types import ToolResult
from openjarvis.mcp.client import MCPClient
from openjarvis.tools._stubs import BaseTool, ToolSpec


class MCPToolAdapter(BaseTool):
    """Wraps a single MCP-hosted tool as a native BaseTool.

    This adapter enables tools discovered from external MCP servers to
    be used seamlessly within OpenJarvis agents via the ``ToolExecutor``.

    Parameters
    ----------
    client:
        The ``MCPClient`` connected to the external MCP server.
    tool_spec:
        The ``ToolSpec`` describing this tool (from ``MCPClient.list_tools()``).
    """

    tool_id = "mcp_adapter"

    def __init__(self, client: MCPClient, tool_spec: ToolSpec) -> None:
        self._client = client
        self._spec = tool_spec

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def execute(self, **params: Any) -> ToolResult:
        """Execute the remote MCP tool and return a ToolResult."""
        try:
            result = self._client.call_tool(self._spec.name, params)
            content_parts = result.get("content", [])
            text = "\n".join(
                p.get("text", "") for p in content_parts if isinstance(p, dict)
            )
            return ToolResult(
                tool_name=self._spec.name,
                content=text,
                success=not result.get("isError", False),
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self._spec.name,
                content=f"MCP tool error: {exc}",
                success=False,
            )


class MCPToolProvider:
    """Discovers tools from an MCP server and returns BaseTool adapters.

    Parameters
    ----------
    client:
        The ``MCPClient`` connected to the MCP server.
    """

    def __init__(self, client: MCPClient) -> None:
        self._client = client

    def discover(self) -> List[BaseTool]:
        """Discover available tools and return them as BaseTool adapters."""
        specs = self._client.list_tools()
        return [MCPToolAdapter(self._client, s) for s in specs]


__all__ = ["MCPToolAdapter", "MCPToolProvider"]
