"""Storage MCP tools — expose MemoryBackend operations as BaseTool instances.

These tools wrap the ``MemoryBackend`` ABC so that memory operations
(store, retrieve, search, index) are discoverable and callable via MCP.
"""

from __future__ import annotations

import os
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.storage._stubs import MemoryBackend


@ToolRegistry.register("memory_store")
class MemoryStoreTool(BaseTool):
    """MCP-exposed tool: store content into memory backend."""

    tool_id = "memory_store"

    def __init__(self, backend: MemoryBackend | None = None) -> None:
        self._backend = backend

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_store",
            description="Store content in the memory backend for later retrieval.",
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The text content to store.",
                    },
                    "source": {
                        "type": "string",
                        "description": "Optional source identifier for the content.",
                    },
                },
                "required": ["content"],
            },
            category="storage",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._backend is None:
            return ToolResult(
                tool_name="memory_store",
                content="No memory backend configured.",
                success=False,
            )
        content = params.get("content", "")
        if not content:
            return ToolResult(
                tool_name="memory_store",
                content="No content provided.",
                success=False,
            )
        try:
            doc_id = self._backend.store(
                content,
                source=params.get("source", ""),
            )
            return ToolResult(
                tool_name="memory_store",
                content=f"Stored as {doc_id}",
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="memory_store",
                content=f"Store error: {exc}",
                success=False,
            )


@ToolRegistry.register("memory_retrieve")
class MemoryRetrieveTool(BaseTool):
    """MCP-exposed tool: retrieve from memory backend."""

    tool_id = "memory_retrieve"

    def __init__(self, backend: MemoryBackend | None = None) -> None:
        self._backend = backend

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_retrieve",
            description="Retrieve relevant content from the memory backend.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default 5).",
                    },
                },
                "required": ["query"],
            },
            category="storage",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._backend is None:
            return ToolResult(
                tool_name="memory_retrieve",
                content="No memory backend configured.",
                success=False,
            )
        query = params.get("query", "")
        if not query:
            return ToolResult(
                tool_name="memory_retrieve",
                content="No query provided.",
                success=False,
            )
        try:
            top_k = int(params.get("top_k", 5))
            results = self._backend.retrieve(query, top_k=top_k)
            if not results:
                return ToolResult(
                    tool_name="memory_retrieve",
                    content="No results found.",
                    success=True,
                )
            formatted = "\n---\n".join(f"[{r.score:.2f}] {r.content}" for r in results)
            return ToolResult(
                tool_name="memory_retrieve",
                content=formatted,
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="memory_retrieve",
                content=f"Retrieve error: {exc}",
                success=False,
            )


@ToolRegistry.register("memory_search")
class MemorySearchTool(BaseTool):
    """MCP-exposed tool: search memory with agent-friendly formatting."""

    tool_id = "memory_search"

    def __init__(self, backend: MemoryBackend | None = None) -> None:
        self._backend = backend

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_search",
            description=(
                "Search memory for content relevant to a query."
                " Returns results with scores and sources."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results (default 5).",
                    },
                },
                "required": ["query"],
            },
            category="storage",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._backend is None:
            return ToolResult(
                tool_name="memory_search",
                content="No memory backend configured.",
                success=False,
            )
        query = params.get("query", "")
        if not query:
            return ToolResult(
                tool_name="memory_search",
                content="No query provided.",
                success=False,
            )
        try:
            top_k = int(params.get("top_k", 5))
            results = self._backend.retrieve(query, top_k=top_k)
            if not results:
                return ToolResult(
                    tool_name="memory_search",
                    content="No results found.",
                    success=True,
                )
            lines = []
            for i, r in enumerate(results, 1):
                source = f" (source: {r.source})" if r.source else ""
                lines.append(f"{i}. [{r.score:.2f}]{source} {r.content}")
            return ToolResult(
                tool_name="memory_search",
                content="\n".join(lines),
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="memory_search",
                content=f"Search error: {exc}",
                success=False,
            )


@ToolRegistry.register("memory_index")
class MemoryIndexTool(BaseTool):
    """MCP-exposed tool: index a file or directory into memory."""

    tool_id = "memory_index"

    def __init__(self, backend: MemoryBackend | None = None) -> None:
        self._backend = backend

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_index",
            description="Index a file or directory into the memory backend.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to file or directory to index.",
                    },
                    "chunk_size": {
                        "type": "integer",
                        "description": "Chunk size in characters (default 512).",
                    },
                    "chunk_overlap": {
                        "type": "integer",
                        "description": "Overlap between chunks (default 64).",
                    },
                },
                "required": ["path"],
            },
            category="storage",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._backend is None:
            return ToolResult(
                tool_name="memory_index",
                content="No memory backend configured.",
                success=False,
            )
        path = params.get("path", "")
        if not path:
            return ToolResult(
                tool_name="memory_index",
                content="No path provided.",
                success=False,
            )
        if not os.path.exists(path):
            return ToolResult(
                tool_name="memory_index",
                content=f"Path does not exist: {path}",
                success=False,
            )
        try:
            from pathlib import Path

            from openjarvis.tools.storage.chunking import ChunkConfig
            from openjarvis.tools.storage.ingest import ingest_path

            chunk_cfg = ChunkConfig(
                chunk_size=int(params.get("chunk_size", 512)),
                chunk_overlap=int(params.get("chunk_overlap", 64)),
            )
            chunks = ingest_path(Path(path), config=chunk_cfg)
            stored = 0
            for chunk in chunks:
                self._backend.store(chunk.content, source=chunk.source)
                stored += 1
            return ToolResult(
                tool_name="memory_index",
                content=f"Indexed {stored} chunks from {path}",
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="memory_index",
                content=f"Index error: {exc}",
                success=False,
            )


__all__ = [
    "MemoryIndexTool",
    "MemoryRetrieveTool",
    "MemorySearchTool",
    "MemoryStoreTool",
]
