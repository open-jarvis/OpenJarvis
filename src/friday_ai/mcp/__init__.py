"""MCP (Model Context Protocol) layer for FridayAI."""

from friday_ai.mcp.client import MCPClient
from friday_ai.mcp.protocol import MCPError, MCPNotification, MCPRequest, MCPResponse
from friday_ai.mcp.server import MCPServer
from friday_ai.mcp.transport import (
    InProcessTransport,
    MCPTransport,
    SSETransport,
    StdioTransport,
    StreamableHTTPTransport,
)

__all__ = [
    "MCPClient",
    "MCPError",
    "MCPNotification",
    "MCPRequest",
    "MCPResponse",
    "MCPServer",
    "MCPTransport",
    "InProcessTransport",
    "SSETransport",
    "StdioTransport",
    "StreamableHTTPTransport",
]
