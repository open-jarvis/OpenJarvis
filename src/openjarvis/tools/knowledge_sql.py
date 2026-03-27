"""KnowledgeSQLTool — read-only SQL queries against the KnowledgeStore.

Allows agents to run SELECT queries for aggregation, counting, ranking,
and filtering operations that BM25 search cannot handle.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_MAX_ROWS = 50

_SCHEMA_DESCRIPTION = (
    "Table: knowledge_chunks\n"
    "Columns: id, content, source, doc_type, doc_id, title, author, "
    "participants, timestamp, thread_id, url, metadata, chunk_index"
)


@ToolRegistry.register("knowledge_sql")
class KnowledgeSQLTool(BaseTool):
    """Run read-only SQL against the knowledge store for aggregation queries."""

    tool_id = "knowledge_sql"

    def __init__(self, store: Optional[KnowledgeStore] = None) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="knowledge_sql",
            description=(
                "Run a read-only SQL SELECT query against the knowledge_chunks table. "
                "Use for counting, ranking, aggregation, and filtering. "
                f"{_SCHEMA_DESCRIPTION}"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "SQL SELECT query. Only SELECT statements allowed. "
                            "Example: SELECT author, COUNT(*) as n "
                            "FROM knowledge_chunks "
                            "WHERE source='imessage' GROUP BY author "
                            "ORDER BY n DESC LIMIT 10"
                        ),
                    },
                },
                "required": ["query"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._store is None:
            return ToolResult(
                tool_name="knowledge_sql",
                content="No knowledge store configured.",
                success=False,
            )

        query: str = params.get("query", "").strip()
        if not query:
            return ToolResult(
                tool_name="knowledge_sql",
                content="No query provided.",
                success=False,
            )

        normalized = query.lstrip().upper()
        if not normalized.startswith("SELECT"):
            return ToolResult(
                tool_name="knowledge_sql",
                content="Only SELECT queries are allowed (read-only).",
                success=False,
            )

        _FORBIDDEN = ("DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "ATTACH")
        for forbidden in _FORBIDDEN:
            if forbidden in normalized:
                return ToolResult(
                    tool_name="knowledge_sql",
                    content=(
                        f"Query contains forbidden keyword: {forbidden}."
                        " Only SELECT queries allowed."
                    ),
                    success=False,
                )

        try:
            rows = self._store._conn.execute(query).fetchmany(_MAX_ROWS)
        except sqlite3.OperationalError as exc:
            return ToolResult(
                tool_name="knowledge_sql",
                content=f"SQL error: {exc}",
                success=False,
            )

        if not rows:
            return ToolResult(
                tool_name="knowledge_sql",
                content="Query returned no results.",
                success=True,
                metadata={"num_rows": 0},
            )

        columns = rows[0].keys()
        lines = [" | ".join(columns)]
        lines.append(" | ".join("---" for _ in columns))
        for row in rows:
            lines.append(" | ".join(str(row[c]) for c in columns))

        return ToolResult(
            tool_name="knowledge_sql",
            content="\n".join(lines),
            success=True,
            metadata={"num_rows": len(rows)},
        )


__all__ = ["KnowledgeSQLTool"]
