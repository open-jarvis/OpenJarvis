"""SQLite/FTS5 memory backend — zero-dependency default.

When the optional Rust extension (``openjarvis_rust``) is available the
implementation delegates to the compiled ``SQLiteMemory`` class for maximum
performance.  When the extension is absent the backend falls back to a
pure-Python implementation that uses the standard-library ``sqlite3`` module
with FTS5 full-text search, so the application works correctly either way.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult

logger = logging.getLogger(__name__)


def _check_fts5(conn: sqlite3.Connection) -> bool:
    """Return True if the SQLite build includes FTS5."""
    try:
        opts = conn.execute("PRAGMA compile_options").fetchall()
        return any("FTS5" in o[0].upper() for o in opts)
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------------------
# Pure-Python fallback implementation
# ---------------------------------------------------------------------------


class _PythonSQLiteMemory:
    """Pure-Python SQLite/FTS5 memory backend used when Rust is unavailable."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._use_fts5 = _check_fts5(self._conn)
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id         TEXT PRIMARY KEY,
                content    TEXT NOT NULL,
                source     TEXT NOT NULL DEFAULT '',
                metadata   TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );
        """)
        if self._use_fts5:
            self._conn.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
                USING fts5(
                    id UNINDEXED,
                    content,
                    source,
                    tokenize='porter unicode61'
                );
            """)
        self._conn.commit()

    def store(self, content: str, source: str, meta_json: Optional[str]) -> str:
        doc_id = str(uuid.uuid4())
        now = time.time()
        meta = meta_json or "{}"
        self._conn.execute(
            "INSERT INTO documents (id, content, source, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (doc_id, content, source, meta, now),
        )
        if self._use_fts5:
            self._conn.execute(
                "INSERT INTO documents_fts (id, content, source) VALUES (?, ?, ?)",
                (doc_id, content, source),
            )
        self._conn.commit()
        return doc_id

    def retrieve(self, query: str, top_k: int) -> str:
        """Return a JSON string of retrieval results."""
        results: List[Dict[str, Any]] = []
        if self._use_fts5:
            rows = self._conn.execute(
                """
                SELECT d.id, d.content, d.source, d.metadata,
                       bm25(documents_fts) AS score
                FROM documents_fts f
                JOIN documents d ON d.id = f.id
                WHERE documents_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (query, top_k),
            ).fetchall()
            for row in rows:
                meta = row["metadata"]
                results.append(
                    {
                        "content": row["content"],
                        "score": abs(float(row["score"])),
                        "source": row["source"],
                        "metadata": meta,
                    }
                )
        else:
            # Fallback: simple LIKE search when FTS5 is unavailable
            like = f"%{query}%"
            rows = self._conn.execute(
                "SELECT id, content, source, metadata FROM documents "
                "WHERE content LIKE ? LIMIT ?",
                (like, top_k),
            ).fetchall()
            for i, row in enumerate(rows):
                results.append(
                    {
                        "content": row["content"],
                        "score": float(len(rows) - i) / len(rows),
                        "source": row["source"],
                        "metadata": row["metadata"],
                    }
                )
        return json.dumps(results)

    def delete(self, doc_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM documents WHERE id = ?", (doc_id,)
        )
        if self._use_fts5:
            self._conn.execute(
                "DELETE FROM documents_fts WHERE id = ?", (doc_id,)
            )
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self) -> None:
        self._conn.execute("DELETE FROM documents")
        if self._use_fts5:
            self._conn.execute("DELETE FROM documents_fts")
        self._conn.commit()

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Registered backend
# ---------------------------------------------------------------------------


@MemoryRegistry.register("sqlite")
class SQLiteMemory(MemoryBackend):
    """Full-text search memory backend using SQLite FTS5.

    Delegates to the compiled Rust extension when available for maximum
    performance.  Falls back to a pure-Python implementation automatically
    so the application works correctly even without the Rust extension.
    """

    backend_id: str = "sqlite"

    def __init__(self, db_path: str | Path = "") -> None:
        if not db_path:
            from openjarvis.core.config import DEFAULT_CONFIG_DIR

            db_path = str(DEFAULT_CONFIG_DIR / "memory.db")

        self._db_path = str(db_path)

        from openjarvis._rust_bridge import RUST_AVAILABLE, get_rust_module

        if RUST_AVAILABLE:
            _rust = get_rust_module()
            if _rust is not None:
                self._rust_impl = _rust.SQLiteMemory(self._db_path)
                self._python_impl: Optional[_PythonSQLiteMemory] = None
                return

        # Rust extension unavailable — use pure-Python fallback
        logger.info(
            "Rust extension not available; SQLiteMemory using pure-Python fallback"
        )
        self._rust_impl = None
        self._python_impl = _PythonSQLiteMemory(self._db_path)

    @property
    def _impl(self) -> Any:
        """Return whichever backend implementation is active."""
        return self._rust_impl if self._rust_impl is not None else self._python_impl

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist *content* and return a unique document id."""
        meta_json = json.dumps(metadata) if metadata else None
        doc_id = self._impl.store(content, source, meta_json)
        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_STORE,
            {
                "backend": self.backend_id,
                "doc_id": doc_id,
                "source": source,
            },
        )
        return doc_id

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Search via FTS5 MATCH with BM25 ranking."""
        if not query.strip():
            return []

        from openjarvis._rust_bridge import retrieval_results_from_json

        results = retrieval_results_from_json(
            self._impl.retrieve(query, top_k),
        )
        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_RETRIEVE,
            {
                "backend": self.backend_id,
                "query": query,
                "num_results": len(results),
            },
        )
        return results

    def delete(self, doc_id: str) -> bool:
        """Delete a document by id."""
        return self._impl.delete(doc_id)

    def clear(self) -> None:
        """Remove all stored documents."""
        self._impl.clear()

    def count(self) -> int:
        """Return the number of stored documents."""
        return self._impl.count()

    def close(self) -> None:
        """Close the database connection."""
        if self._python_impl is not None:
            self._python_impl.close()


__all__ = ["SQLiteMemory"]
