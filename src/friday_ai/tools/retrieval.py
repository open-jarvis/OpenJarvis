"""Retrieval tool — search memory backends for relevant context."""

from __future__ import annotations

from typing import Any, Optional

from friday_ai.core.registry import ToolRegistry
from friday_ai.core.types import ToolResult
from friday_ai.tools._stubs import BaseTool, ToolSpec
from friday_ai.tools.storage._stubs import MemoryBackend
from friday_ai.tools.storage.context import format_context


@ToolRegistry.register("retrieval")
class RetrievalTool(BaseTool):
    """Search the memory backend and return formatted context."""

    tool_id = "retrieval"

    def __init__(
        self,
        backend: Optional[MemoryBackend] = None,
        *,
        top_k: int = 5,
    ) -> None:
        self._backend = backend
        self._top_k = top_k

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="retrieval",
            description=(
                "Search the knowledge base for relevant"
                " information. Returns context with sources."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant information.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5).",
                    },
                },
                "required": ["query"],
            },
            category="memory",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._backend is None:
            return ToolResult(
                tool_name="retrieval",
                content="No memory backend configured.",
                success=False,
            )
        query = params.get("query", "")
        if not query:
            return ToolResult(
                tool_name="retrieval",
                content="No query provided.",
                success=False,
            )
        top_k = params.get("top_k", self._top_k)
        try:
            results = self._backend.retrieve(query, top_k=top_k)
        except Exception as exc:
            return ToolResult(
                tool_name="retrieval",
                content=f"Retrieval error: {exc}",
                success=False,
            )
        if not results:
            return ToolResult(
                tool_name="retrieval",
                content="No relevant results found.",
                success=True,
            )
        formatted = format_context(results)
        return ToolResult(
            tool_name="retrieval",
            content=formatted,
            success=True,
            metadata={"num_results": len(results)},
        )


__all__ = ["RetrievalTool"]
