"""SQLite/FTS5 memory backend — zero-dependency default."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult


def _check_fts5(conn: sqlite3.Connection) -> bool:
    """Return True if the SQLite build includes FTS5."""
    try:
        opts = conn.execute("PRAGMA compile_options").fetchall()
        return any("FTS5" in o[0].upper() for o in opts)
    except sqlite3.Error:
        return False


@MemoryRegistry.register("sqlite")
class SQLiteMemory(MemoryBackend):
    """Full-text search memory backend using SQLite FTS5.

    Uses the built-in ``sqlite3`` module — no extra dependencies.
    """

    backend_id: str = "sqlite"

    def __init__(self, db_path: str | Path = "") -> None:
        if not db_path:
            from openjarvis.core.config import DEFAULT_CONFIG_DIR
            db_path = str(DEFAULT_CONFIG_DIR / "memory.db")

        self._db_path = str(db_path)

        from openjarvis._rust_bridge import get_rust_module
        _rust = get_rust_module()
        if _rust is not None:
            self._rust_impl = _rust.SQLiteMemory(self._db_path)
            self._conn = None  # type: ignore[assignment]
            return

        self._rust_impl = None
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row

        if not _check_fts5(self._conn):
            raise RuntimeError(
                "SQLite FTS5 extension is not available. "
                "Upgrade your Python or install a SQLite build "
                "with FTS5 enabled."
            )

        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id       TEXT PRIMARY KEY,
                content  TEXT NOT NULL,
                source   TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
            USING fts5(
                content,
                source,
                content=documents,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS documents_ai
            AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, content, source)
                VALUES (new.rowid, new.content, new.source);
            END;

            CREATE TRIGGER IF NOT EXISTS documents_ad
            AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(
                    documents_fts, rowid, content, source
                )
                VALUES ('delete', old.rowid, old.content, old.source);
            END;

            CREATE TRIGGER IF NOT EXISTS documents_au
            AFTER UPDATE ON documents BEGIN
                INSERT INTO documents_fts(
                    documents_fts, rowid, content, source
                )
                VALUES ('delete', old.rowid, old.content, old.source);
                INSERT INTO documents_fts(rowid, content, source)
                VALUES (new.rowid, new.content, new.source);
            END;
        """)

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist *content* and return a unique document id."""
        if self._rust_impl is not None:
            meta_json = json.dumps(metadata) if metadata else None
            doc_id = self._rust_impl.store(content, source, meta_json)
            bus = get_event_bus()
            bus.publish(EventType.MEMORY_STORE, {
                "backend": self.backend_id,
                "doc_id": doc_id,
                "source": source,
            })
            return doc_id

        import time

        doc_id = uuid.uuid4().hex
        meta_json = json.dumps(metadata or {})
        self._conn.execute(
            "INSERT INTO documents (id, content, source, metadata, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (doc_id, content, source, meta_json, time.time()),
        )
        self._conn.commit()

        bus = get_event_bus()
        bus.publish(EventType.MEMORY_STORE, {
            "backend": self.backend_id,
            "doc_id": doc_id,
            "source": source,
        })
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

        if self._rust_impl is not None:
            from openjarvis._rust_bridge import retrieval_results_from_json
            results = retrieval_results_from_json(
                self._rust_impl.retrieve(query, top_k),
            )
            bus = get_event_bus()
            bus.publish(EventType.MEMORY_RETRIEVE, {
                "backend": self.backend_id,
                "query": query,
                "num_results": len(results),
            })
            return results

        # Escape FTS5 special characters
        safe_query = self._escape_fts_query(query)
        if not safe_query:
            return []

        try:
            rows = self._conn.execute(
                "SELECT d.id, d.content, d.source, d.metadata,"
                "       rank AS score"
                "  FROM documents_fts f"
                "  JOIN documents d ON d.rowid = f.rowid"
                " WHERE documents_fts MATCH ?"
                " ORDER BY rank"
                " LIMIT ?",
                (safe_query, top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        results = []
        for row in rows:
            # FTS5 rank is negative (more negative = better match)
            # Convert to positive score for consistency
            score = -float(row["score"]) if row["score"] else 0.0
            results.append(RetrievalResult(
                content=row["content"],
                score=score,
                source=row["source"],
                metadata=json.loads(row["metadata"]),
            ))

        bus = get_event_bus()
        bus.publish(EventType.MEMORY_RETRIEVE, {
            "backend": self.backend_id,
            "query": query,
            "num_results": len(results),
        })
        return results

    def delete(self, doc_id: str) -> bool:
        """Delete a document by id. Return True if it existed."""
        if self._rust_impl is not None:
            return self._rust_impl.delete(doc_id)
        cursor = self._conn.execute(
            "DELETE FROM documents WHERE id = ?", (doc_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def clear(self) -> None:
        """Remove all stored documents."""
        if self._rust_impl is not None:
            self._rust_impl.clear()
            return
        self._conn.execute("DELETE FROM documents")
        self._conn.commit()

    def count(self) -> int:
        """Return the number of stored documents."""
        if self._rust_impl is not None:
            return self._rust_impl.count()
        row = self._conn.execute(
            "SELECT COUNT(*) FROM documents"
        ).fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()

    @staticmethod
    def _escape_fts_query(query: str) -> str:
        """Escape an FTS5 query to avoid syntax errors.

        Wraps each word in double quotes to treat them as literal
        terms and joins with implicit AND.
        """
        words = query.split()
        if not words:
            return ""
        # Quote each term to avoid FTS5 syntax issues
        return " ".join(f'"{w}"' for w in words)


__all__ = ["SQLiteMemory"]
