"""KnowledgeSearchTool — filtered BM25 retrieval with source attribution.

Wraps ``KnowledgeStore`` so agents can search ingested documents by text query
and optional provenance filters (source, doc_type, author, date range).
Optionally delegates to a ``TwoStageRetriever`` for BM25 + reranking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from friday_ai.connectors.store import KnowledgeStore
from friday_ai.core.registry import ToolRegistry
from friday_ai.core.types import ToolResult
from friday_ai.tools._stubs import BaseTool, ToolSpec

if TYPE_CHECKING:
    from friday_ai.connectors.retriever import TwoStageRetriever


@ToolRegistry.register("knowledge_search")
class KnowledgeSearchTool(BaseTool):
    """Search the knowledge store using filtered BM25 retrieval.

    Results include source attribution so agents can cite provenance.
    When a ``TwoStageRetriever`` is supplied it is used in place of the
    store's direct ``retrieve`` method, enabling optional semantic reranking.
    """

    tool_id = "knowledge_search"

    def __init__(
        self,
        store: Optional[KnowledgeStore] = None,
        retriever: Optional["TwoStageRetriever"] = None,
    ) -> None:
        self._store = store
        self._retriever = retriever

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="knowledge_search",
            description=(
                "Search ingested personal knowledge (emails, Slack messages,"
                " documents) using full-text BM25 retrieval with optional"
                " filters for source, type, author, and date range."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Full-text search query.",
                    },
                    "source": {
                        "type": "string",
                        "description": (
                            "Filter by source connector"
                            " (e.g. 'gmail', 'slack', 'obsidian')."
                        ),
                    },
                    "doc_type": {
                        "type": "string",
                        "description": (
                            "Filter by document type"
                            " (e.g. 'email', 'message', 'document')."
                        ),
                    },
                    "author": {
                        "type": "string",
                        "description": "Filter by author.",
                    },
                    "since": {
                        "type": "string",
                        "description": (
                            "Exclude documents before this ISO 8601 timestamp."
                        ),
                    },
                    "until": {
                        "type": "string",
                        "description": (
                            "Exclude documents after this ISO 8601 timestamp."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of results (default 10).",
                    },
                },
                "required": ["query"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._store is None and self._retriever is None:
            return ToolResult(
                tool_name="knowledge_search",
                content="No knowledge store configured.",
                success=False,
            )

        query: str = params.get("query", "")
        if not query:
            return ToolResult(
                tool_name="knowledge_search",
                content="No query provided.",
                success=False,
            )

        raw_top_k = params.get("top_k")
        try:
            top_k: int = int(raw_top_k) if raw_top_k not in (None, "") else 10
        except (ValueError, TypeError, OverflowError):
            top_k = 10
        top_k = max(1, top_k)

        filters: dict[str, Optional[str]] = {}
        for name in ("source", "doc_type", "author", "since", "until"):
            value = params.get(name)
            if value is not None and not isinstance(value, str):
                return ToolResult(
                    tool_name="knowledge_search",
                    content=f"Invalid {name} filter: expected a string.",
                    success=False,
                )
            filters[name] = value.strip() or None if value else None

        source = filters["source"]
        doc_type = filters["doc_type"]
        author = filters["author"]
        since = filters["since"]
        until = filters["until"]

        try:
            if self._retriever is not None:
                results = self._retriever.retrieve(
                    query,
                    top_k=top_k,
                    source=source or "",
                    doc_type=doc_type or "",
                    author=author or "",
                    since=since or "",
                    until=until or "",
                )
            else:
                results = self._store.retrieve(  # type: ignore[union-attr]
                    query,
                    top_k=top_k,
                    source=source,
                    doc_type=doc_type,
                    author=author,
                    since=since,
                    until=until,
                )
        except Exception as exc:
            return ToolResult(
                tool_name="knowledge_search",
                content=f"Knowledge search failed: {exc}",
                success=False,
            )

        if not results:
            return ToolResult(
                tool_name="knowledge_search",
                content="No relevant results found.",
                success=True,
                metadata={"num_results": 0},
            )

        lines: list[str] = []
        for i, result in enumerate(results, start=1):
            meta = result.metadata
            src_label = result.source or meta.get("source", "")
            title = meta.get("title", "")
            result_author = meta.get("author", "")
            url = meta.get("url", "")

            # Build header line
            header_parts: list[str] = []
            if src_label:
                header_parts.append(f"[{src_label}]")
            if title:
                header_parts.append(title)
            if result_author:
                header_parts.append(f"by {result_author}")
            if url:
                header_parts.append(f"({url})")

            header = " ".join(header_parts) if header_parts else "(unknown source)"
            lines.append(f"**Result {i}:** {header}")
            lines.append(result.content)
            lines.append("")

        formatted = "\n".join(lines).rstrip()

        return ToolResult(
            tool_name="knowledge_search",
            content=formatted,
            success=True,
            metadata={"num_results": len(results)},
        )


__all__ = ["KnowledgeSearchTool"]
