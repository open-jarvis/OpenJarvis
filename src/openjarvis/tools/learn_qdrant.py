"""Persist chunked text into Qdrant via the MCP ``qdrant-store`` tool."""

from __future__ import annotations

import json
import logging
from typing import Any, List

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.storage.chunking import ChunkConfig, chunk_text

logger = logging.getLogger(__name__)

# Avoid runaway writes when the model passes huge blobs
_MAX_CHUNKS_PER_CALL = 200


def _discover_qdrant_store_adapters() -> List[Any]:
    """Return MCP adapters named ``qdrant-store`` from configured servers."""
    from openjarvis.cli._external_mcp_tools import discover_external_mcp_tools
    from openjarvis.core.config import load_config

    cfg = load_config()
    return discover_external_mcp_tools(
        cfg,
        allowed_tool_names={"qdrant-store"},
    )


@ToolRegistry.register("learn_qdrant")
class LearnQdrantTool(BaseTool):
    """Chunk arbitrary text and store each chunk through MCP ``qdrant-store``.

    Use after high-value ``web_search`` results, ``file_read`` excerpts, or
    GitHub MCP payloads so ``qdrant-find`` can retrieve them later.
    """

    tool_id = "learn_qdrant"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="learn_qdrant",
            description=(
                "Split long text into chunks and store each in Qdrant via "
                "qdrant-store (same collection as manual memory). Use after "
                "useful web_search, file_read, or GitHub tool output so "
                "qdrant-find can recall it later. Pass a clear ``source`` label "
                "(e.g. URL or repo:path)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Full text to chunk and store.",
                    },
                    "source": {
                        "type": "string",
                        "description": (
                            "Provenance label: URL, file path, or "
                            "github:owner/repo/path."
                        ),
                    },
                    "origin": {
                        "type": "string",
                        "description": (
                            "Optional short tag: web_search, github, file_read, "
                            "user, etc."
                        ),
                    },
                    "chunk_size": {
                        "type": "integer",
                        "description": (
                            "Approximate chunk size in tokens (default 512)."
                        ),
                    },
                    "chunk_overlap": {
                        "type": "integer",
                        "description": "Token overlap between chunks (default 64).",
                    },
                    "min_chunk_size": {
                        "type": "integer",
                        "description": (
                            "Minimum tokens required to keep a chunk (default 20)."
                        ),
                    },
                    "extra_metadata": {
                        "type": "string",
                        "description": (
                            "Optional JSON object merged into each chunk's metadata."
                        ),
                    },
                },
                "required": ["text"],
            },
            category="storage",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = (params.get("text") or "").strip()
        if not text:
            return ToolResult(
                tool_name="learn_qdrant",
                content="No text provided.",
                success=False,
            )

        adapters = _discover_qdrant_store_adapters()
        if not adapters:
            return ToolResult(
                tool_name="learn_qdrant",
                content=(
                    "No MCP tool qdrant-store available. Enable [tools.mcp] with a "
                    "Qdrant MCP server and include qdrant-store in tools.enabled."
                ),
                success=False,
            )

        store = adapters[0]
        if len(adapters) > 1:
            logger.debug(
                "learn_qdrant: multiple qdrant-store adapters (%d), using first",
                len(adapters),
            )

        extra: dict[str, Any] = {}
        raw_extra = params.get("extra_metadata")
        if isinstance(raw_extra, str) and raw_extra.strip():
            try:
                parsed = json.loads(raw_extra)
                if isinstance(parsed, dict):
                    extra = parsed
            except json.JSONDecodeError as exc:
                return ToolResult(
                    tool_name="learn_qdrant",
                    content=f"extra_metadata is not valid JSON: {exc}",
                    success=False,
                )

        cfg = ChunkConfig(
            chunk_size=int(params.get("chunk_size", 512)),
            chunk_overlap=int(params.get("chunk_overlap", 64)),
            min_chunk_size=int(params.get("min_chunk_size", 20)),
        )
        source = (params.get("source") or "").strip() or "learn_qdrant"
        origin = (params.get("origin") or "").strip()

        chunks = chunk_text(text, source=source, config=cfg)
        if not chunks:
            return ToolResult(
                tool_name="learn_qdrant",
                content="No chunks produced (empty or whitespace-only text).",
                success=False,
            )

        truncated = False
        if len(chunks) > _MAX_CHUNKS_PER_CALL:
            chunks = chunks[:_MAX_CHUNKS_PER_CALL]
            truncated = True

        failures: list[str] = []
        for ch in chunks:
            meta: dict[str, Any] = {
                "source": source,
                "chunk_index": ch.index,
                "learn_qdrant": True,
                **extra,
            }
            if origin:
                meta["origin"] = origin
            result = store.execute(
                information=ch.content,
                metadata=meta,
            )
            if not result.success:
                failures.append(result.content[:200])

        if failures:
            return ToolResult(
                tool_name="learn_qdrant",
                content=(
                    f"Stored {len(chunks) - len(failures)}/{len(chunks)} chunks; "
                    f"errors: {failures[:3]}"
                ),
                success=False,
            )

        msg = f"Stored {len(chunks)} chunk(s) in Qdrant (source={source!r})."
        if truncated:
            msg += f" Truncated to {_MAX_CHUNKS_PER_CALL} chunks."
        return ToolResult(
            tool_name="learn_qdrant",
            content=msg,
            success=True,
            metadata={"chunks": len(chunks), "source": source},
        )


__all__ = ["LearnQdrantTool", "_discover_qdrant_store_adapters"]
