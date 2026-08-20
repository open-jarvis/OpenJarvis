"""ScanChunksTool — semantic grep via LM-powered chunk scanning.

Pulls chunks from the KnowledgeStore by filter, batches them, and asks the
LM to extract information relevant to a question.  Catches semantic matches
that keyword-based BM25 search misses.
"""

from __future__ import annotations

from typing import Any, List, Optional

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import Message, Role, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool, ToolSpec

_DEFAULT_MAX_CHUNKS = 200
_DEFAULT_BATCH_SIZE = 20


@ToolRegistry.register("scan_chunks")
class ScanChunksTool(BaseTool):
    """Semantic grep — feeds chunks to the LM to find information BM25 misses."""

    tool_id = "scan_chunks"

    def __init__(
        self,
        store: Optional[KnowledgeStore] = None,
        engine: Optional[InferenceEngine] = None,
        model: str = "",
    ) -> None:
        self._store = store
        self._engine = engine
        self._model = model

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="scan_chunks",
            description=(
                "Semantic search — feeds chunks from the knowledge store to an LM "
                "that reads the actual text looking for relevant information. "
                "Use when keyword search (knowledge_search) misses semantic matches "
                "(e.g. searching for 'VCs' when text says 'fundraising round'). "
                "Slower but catches what BM25 misses. "
                "Filters: source, doc_type, since, until."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "What to look for in the chunks.",
                    },
                    "source": {
                        "type": "string",
                        "description": "Filter by source (e.g. 'granola', 'gmail').",
                    },
                    "doc_type": {
                        "type": "string",
                        "description": "Filter by doc type (e.g. 'document', 'email').",
                    },
                    "since": {
                        "type": "string",
                        "description": "Only chunks after this ISO timestamp.",
                    },
                    "until": {
                        "type": "string",
                        "description": "Only chunks before this ISO timestamp.",
                    },
                    "max_chunks": {
                        "type": "integer",
                        "description": (
                            f"Max chunks to scan (default {_DEFAULT_MAX_CHUNKS})."
                        ),
                    },
                },
                "required": ["question"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._store is None or self._engine is None:
            return ToolResult(
                tool_name="scan_chunks",
                content="Scan tool not configured (missing store or engine).",
                success=False,
            )

        question: str = params.get("question", "")
        if not question:
            return ToolResult(
                tool_name="scan_chunks",
                content="No question provided.",
                success=False,
            )

        source: str = params.get("source", "")
        doc_type: str = params.get("doc_type", "")
        since: str = params.get("since", "")
        until: str = params.get("until", "")
        max_chunks: int = int(params.get("max_chunks", _DEFAULT_MAX_CHUNKS))
        batch_size: int = _DEFAULT_BATCH_SIZE

        where_clauses: List[str] = []
        sql_params: List[Any] = []

        if source:
            where_clauses.append("source = ?")
            sql_params.append(source)
        if doc_type:
            where_clauses.append("doc_type = ?")
            sql_params.append(doc_type)
        if since:
            where_clauses.append("timestamp >= ?")
            sql_params.append(since)
        if until:
            where_clauses.append("timestamp <= ?")
            sql_params.append(until)

        where = ""
        if where_clauses:
            where = "WHERE " + " AND ".join(where_clauses)

        sql = (
            "SELECT content, source, title, author"
            f" FROM knowledge_chunks {where} LIMIT ?"
        )
        sql_params.append(max_chunks)

        rows = self._store._conn.execute(sql, sql_params).fetchall()

        if not rows:
            return ToolResult(
                tool_name="scan_chunks",
                content="No chunks found matching filters.",
                success=True,
                metadata={"chunks_scanned": 0},
            )

        findings: List[str] = []
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            batch_text = "\n\n---\n\n".join(
                f"[{row['source']}] {row['title']} by {row['author']}:"
                f"\n{row['content']}"
                for row in batch
            )

            messages = [
                Message(
                    role=Role.USER,
                    content=(
                        f"/no_think\n"
                        f"Extract any information relevant to this"
                        f" question: {question}\n\n"
                        f"If nothing is relevant, reply with"
                        f" exactly: NOTHING_RELEVANT\n\n"
                        f"Chunks:\n{batch_text}"
                    ),
                ),
            ]

            result = self._engine.generate(messages, model=self._model, max_tokens=1024)
            content = result.get("content", "").strip()
            if content and "NOTHING_RELEVANT" not in content:
                findings.append(content)

        if not findings:
            return ToolResult(
                tool_name="scan_chunks",
                content=f"Scanned {len(rows)} chunks — no relevant information found.",
                success=True,
                metadata={"chunks_scanned": len(rows)},
            )

        return ToolResult(
            tool_name="scan_chunks",
            content="\n\n".join(findings),
            success=True,
            metadata={
                "chunks_scanned": len(rows),
                "batches_with_findings": len(findings),
            },
        )


__all__ = ["ScanChunksTool"]
