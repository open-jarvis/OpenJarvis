"""MCP Server — wraps OpenJarvis tools as MCP-discoverable tools."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from openjarvis.core.types import ToolCall
from openjarvis.mcp.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    MCPRequest,
    MCPResponse,
)
from openjarvis.tools._stubs import BaseTool, ToolExecutor

logger = logging.getLogger(__name__)

# Tool annotation hints per MCP spec 2025-11-25
_TOOL_ANNOTATIONS: Dict[str, Dict[str, Any]] = {
    "memory_store": {"destructiveHint": True, "readOnlyHint": False},
    "memory_retrieve": {"readOnlyHint": True, "destructiveHint": False},
    "memory_search": {"readOnlyHint": True, "destructiveHint": False},
    "memory_index": {"destructiveHint": True, "readOnlyHint": False},
    "calculator": {"readOnlyHint": True, "destructiveHint": False},
    "think": {"readOnlyHint": True, "destructiveHint": False},
    "retrieval": {"readOnlyHint": True, "destructiveHint": False},
    "llm": {"readOnlyHint": False, "destructiveHint": False},
    "file_read": {"readOnlyHint": True, "destructiveHint": False},
    "web_search": {"readOnlyHint": True, "destructiveHint": False},
    "code_interpreter": {"destructiveHint": True, "readOnlyHint": False},
    "repl": {"destructiveHint": True, "readOnlyHint": False},
    "channel_send": {"destructiveHint": True, "readOnlyHint": False},
    "channel_list": {"readOnlyHint": True, "destructiveHint": False},
    "channel_status": {"readOnlyHint": True, "destructiveHint": False},
}


class MCPServer:
    """MCP server that exposes OpenJarvis tools via JSON-RPC.

    Parameters
    ----------
    tools:
        List of ``BaseTool`` instances to expose.  If ``None``, auto-discovers
        all registered tools from ``ToolRegistry``.
    """

    SERVER_NAME = "openjarvis"
    SERVER_VERSION = "0.1.0"
    PROTOCOL_VERSION = "2025-11-25"

    def __init__(self, tools: Optional[List[BaseTool]] = None) -> None:
        if tools is None:
            tools = self._auto_discover_tools()
        self._tools: Dict[str, BaseTool] = {t.spec.name: t for t in tools}
        self._executor = ToolExecutor(tools)

    @staticmethod
    def _auto_discover_tools() -> List[BaseTool]:
        """Auto-discover all built-in tools by direct import.

        Does not rely on ToolRegistry state — imports each tool class
        directly and attempts instantiation with no arguments.
        """
        tools: List[BaseTool] = []
        _tool_classes: List[type] = []

        # Built-in API tools
        try:
            from openjarvis.tools.calculator import CalculatorTool

            _tool_classes.append(CalculatorTool)
        except ImportError:
            pass
        try:
            from openjarvis.tools.think import ThinkTool

            _tool_classes.append(ThinkTool)
        except ImportError:
            pass
        try:
            from openjarvis.tools.file_read import FileReadTool

            _tool_classes.append(FileReadTool)
        except ImportError:
            pass
        try:
            from openjarvis.tools.web_search import WebSearchTool

            _tool_classes.append(WebSearchTool)
        except ImportError:
            pass
        try:
            from openjarvis.tools.code_interpreter import CodeInterpreterTool

            _tool_classes.append(CodeInterpreterTool)
        except ImportError:
            pass
        try:
            from openjarvis.tools.repl import ReplTool

            _tool_classes.append(ReplTool)
        except ImportError:
            pass

        # Storage MCP tools
        try:
            from openjarvis.tools.storage_tools import (
                MemoryIndexTool,
                MemoryRetrieveTool,
                MemorySearchTool,
                MemoryStoreTool,
            )

            _tool_classes.extend(
                [
                    MemoryStoreTool,
                    MemoryRetrieveTool,
                    MemorySearchTool,
                    MemoryIndexTool,
                ]
            )
        except ImportError:
            pass

        # Channel MCP tools
        try:
            from openjarvis.tools.channel_tools import (
                ChannelListTool,
                ChannelSendTool,
                ChannelStatusTool,
            )

            _tool_classes.extend(
                [
                    ChannelSendTool,
                    ChannelListTool,
                    ChannelStatusTool,
                ]
            )
        except ImportError:
            pass

        # LM tool (needs engine/model — instantiate with None)
        try:
            from openjarvis.tools.llm_tool import LLMTool

            _tool_classes.append(LLMTool)
        except ImportError:
            pass

        # Retrieval tool (needs backend — instantiate with None)
        try:
            from openjarvis.tools.retrieval import RetrievalTool

            _tool_classes.append(RetrievalTool)
        except ImportError:
            pass

        for cls in _tool_classes:
            try:
                tools.append(cls())
            except Exception as exc:
                logger.warning("Failed to instantiate tool from %r: %s", cls, exc)

        # Also check ToolRegistry for any user-registered tools
        try:
            from openjarvis.core.registry import ToolRegistry

            known_names = {t.spec.name for t in tools}
            for key in ToolRegistry.keys():
                if key not in known_names:
                    try:
                        tool = ToolRegistry.create(key)
                        if isinstance(tool, BaseTool):
                            tools.append(tool)
                    except Exception as exc:
                        logger.warning("Failed to register user tool: %s", exc)
        except Exception as exc:
            logger.warning("Failed to discover tools from registry: %s", exc)

        return tools

    def get_tools(self) -> List[BaseTool]:
        """Return all tool instances (for use by SystemBuilder)."""
        return list(self._tools.values())

    def handle(self, request: MCPRequest) -> MCPResponse:
        """Dispatch an MCP request and return a response."""
        if request.method == "initialize":
            return self._handle_initialize(request)
        elif request.method == "tools/list":
            return self._handle_tools_list(request)
        elif request.method == "tools/call":
            return self._handle_tools_call(request)
        else:
            return MCPResponse.error_response(
                request.id,
                METHOD_NOT_FOUND,
                f"Unknown method: {request.method}",
            )

    def _handle_initialize(self, req: MCPRequest) -> MCPResponse:
        """Handle the initialize handshake."""
        return MCPResponse(
            result={
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": True},
                },
                "serverInfo": {
                    "name": self.SERVER_NAME,
                    "version": self.SERVER_VERSION,
                    "title": "OpenJarvis Tool Server",
                },
            },
            id=req.id,
        )

    def _handle_tools_list(self, req: MCPRequest) -> MCPResponse:
        """Handle tools/list — return specs for all registered tools."""
        tool_list = []
        for tool in self._tools.values():
            s = tool.spec
            entry: Dict[str, Any] = {
                "name": s.name,
                "description": s.description,
                "inputSchema": s.parameters,
            }
            # Add annotations if available (MCP spec 2025-11-25)
            annotations = _TOOL_ANNOTATIONS.get(s.name)
            if annotations:
                entry["annotations"] = annotations
            tool_list.append(entry)
        return MCPResponse(result={"tools": tool_list}, id=req.id)

    def _handle_tools_call(self, req: MCPRequest) -> MCPResponse:
        """Handle tools/call — execute a tool and return the result."""
        tool_name = req.params.get("name")
        arguments = req.params.get("arguments", {})

        if not tool_name:
            return MCPResponse.error_response(
                req.id,
                INVALID_PARAMS,
                "Missing required parameter: name",
            )

        if tool_name not in self._tools:
            return MCPResponse.error_response(
                req.id,
                INVALID_PARAMS,
                f"Unknown tool: {tool_name}",
            )

        try:
            import json

            tool_call = ToolCall(
                id=f"mcp-{req.id}",
                name=tool_name,
                arguments=json.dumps(arguments),
            )
            result = self._executor.execute(tool_call)
            return MCPResponse(
                result={
                    "content": [
                        {"type": "text", "text": result.content},
                    ],
                    "isError": not result.success,
                },
                id=req.id,
            )
        except Exception as exc:
            return MCPResponse.error_response(
                req.id,
                INTERNAL_ERROR,
                f"Tool execution error: {exc}",
            )


__all__ = ["MCPServer"]
