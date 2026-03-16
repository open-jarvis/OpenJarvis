"""SQLite/FTS5 memory backend — zero-dependency default."""

from __future__ import annotations

import json
import sqlite3
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
        self._rust_impl = _rust.SQLiteMemory(self._db_path)
        self._conn = None  # type: ignore[assignment]

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
                tokenize='porter unicode61'
            );
        """)

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist *content* and return a unique document id."""
        meta_json = json.dumps(metadata) if metadata else None
        doc_id = self._rust_impl.store(content, source, meta_json)
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
        """Search via FTS5 MATCH with BM25 ranking — always via Rust backend."""
        if not query.strip():
            return []

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

    def delete(self, doc_id: str) -> bool:
        """Delete a document by id — always via Rust backend."""
        return self._rust_impl.delete(doc_id)

    def clear(self) -> None:
        """Remove all stored documents — always via Rust backend."""
        self._rust_impl.clear()

    def count(self) -> int:
        """Return the number of stored documents — always via Rust backend."""
        return self._rust_impl.count()

    def close(self) -> None:
        """Close the database connection."""
        pass


__all__ = ["SQLiteMemory"]
