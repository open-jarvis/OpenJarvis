"""KnowledgeStore — source-aware SQLite/FTS5 memory backend for Deep Research.

Extends ``MemoryBackend`` with per-document provenance columns so that the
IngestionPipeline and the ``knowledge_search`` tool can filter results by
source, doc_type, author, and timestamp ranges.

Pure Python ``sqlite3`` (no Rust extension required).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_MAIN_TABLE = """
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id            TEXT PRIMARY KEY,
    doc_id        TEXT NOT NULL,
    content       TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT '',
    source_id     TEXT NOT NULL DEFAULT '',
    doc_type      TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL DEFAULT '',
    author        TEXT NOT NULL DEFAULT '',
    participants  TEXT NOT NULL DEFAULT '[]',
    participants_raw TEXT NOT NULL DEFAULT '[]',
    timestamp     TEXT NOT NULL DEFAULT '',
    thread_id     TEXT NOT NULL DEFAULT '',
    channel       TEXT NOT NULL DEFAULT '',
    url           TEXT NOT NULL DEFAULT '',
    metadata      TEXT NOT NULL DEFAULT '{}',
    chunk_index   INTEGER NOT NULL DEFAULT 0,
    embedding     BLOB,
    embedding_model_version TEXT NOT NULL DEFAULT '',
    content_hash  TEXT NOT NULL DEFAULT '',
    deleted_at    REAL,
    last_synced   REAL NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);
"""

# Additive migrations: existing installs get new columns via ALTER TABLE.
# Order doesn't matter — each entry is independent and idempotent.
_V1_COLUMNS: List[tuple[str, str]] = [
    ("source_id", "TEXT NOT NULL DEFAULT ''"),
    ("participants_raw", "TEXT NOT NULL DEFAULT '[]'"),
    ("channel", "TEXT NOT NULL DEFAULT ''"),
    ("embedding", "BLOB"),
    ("embedding_model_version", "TEXT NOT NULL DEFAULT ''"),
    ("content_hash", "TEXT NOT NULL DEFAULT ''"),
    ("deleted_at", "REAL"),
    ("last_synced", "REAL NOT NULL DEFAULT 0"),
]

_CREATE_FTS_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
USING fts5(
    content,
    title,
    author,
    content='knowledge_chunks',
    content_rowid='rowid',
    tokenize='porter unicode61'
);
"""

_CREATE_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge_chunks BEGIN
    INSERT INTO knowledge_fts(rowid, content, title, author)
    VALUES (new.rowid, new.content, new.title, new.author);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge_chunks BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, content, title, author)
    VALUES ('delete', old.rowid, old.content, old.title, old.author);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge_chunks BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, content, title, author)
    VALUES ('delete', old.rowid, old.content, old.title, old.author);
    INSERT INTO knowledge_fts(rowid, content, title, author)
    VALUES (new.rowid, new.content, new.title, new.author);
END;
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_kc_source        ON knowledge_chunks(source);
CREATE INDEX IF NOT EXISTS idx_kc_doc_type      ON knowledge_chunks(doc_type);
CREATE INDEX IF NOT EXISTS idx_kc_author        ON knowledge_chunks(author);
CREATE INDEX IF NOT EXISTS idx_kc_timestamp     ON knowledge_chunks(timestamp);
CREATE INDEX IF NOT EXISTS idx_kc_thread_id     ON knowledge_chunks(thread_id);
CREATE INDEX IF NOT EXISTS idx_kc_doc_id        ON knowledge_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_kc_source_id     ON knowledge_chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_kc_content_hash  ON knowledge_chunks(content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_kc_natural_key
    ON knowledge_chunks(source, source_id, chunk_index)
    WHERE source_id != '';
"""

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _to_iso(ts: Optional[Union[datetime, str]]) -> str:
    """Normalise a timestamp to ISO 8601 string (UTC)."""
    if ts is None:
        return ""
    if isinstance(ts, str):
        return ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def _to_epoch(ts: Union[datetime, str, float, int]) -> float:
    """Normalise a timestamp to Unix epoch seconds (float)."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        # Treat empty/zero-ish strings as epoch 0; otherwise parse ISO 8601.
        if not ts:
            return 0.0
        return datetime.fromisoformat(ts).timestamp()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.timestamp()


# ---------------------------------------------------------------------------
# KnowledgeStore
# ---------------------------------------------------------------------------


@MemoryRegistry.register("knowledge")
class KnowledgeStore(MemoryBackend):
    """Source-aware SQLite/FTS5 knowledge store for Deep Research.

    Stores document chunks with rich provenance metadata and supports
    filtered BM25 retrieval by source, doc_type, author, and timestamp.
    """

    backend_id: str = "knowledge"

    def __init__(self, db_path: Union[str, Path] = "") -> None:
        if not db_path:
            from openjarvis.core.config import DEFAULT_CONFIG_DIR

            db_path = DEFAULT_CONFIG_DIR / "knowledge.db"

        self._db_path = str(db_path)
        # Ensure the parent directory exists (skip for :memory:)
        if self._db_path != ":memory:":
            from openjarvis.security.file_utils import secure_create

            secure_create(Path(self._db_path))

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._setup()

    def __enter__(self) -> "KnowledgeStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal setup
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        """Create tables, FTS virtual table, triggers and indexes."""
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.executescript(
            _CREATE_MAIN_TABLE + _CREATE_FTS_TABLE + _CREATE_TRIGGERS
        )
        self._migrate_v1_columns()
        # Indexes reference the new columns, so they run after migrations.
        self._conn.executescript(_CREATE_INDEXES)
        self._conn.commit()

    def _migrate_v1_columns(self) -> None:
        """Add v1 schema columns to pre-existing tables (idempotent)."""
        existing = {
            row[1]
            for row in self._conn.execute(
                "PRAGMA table_info(knowledge_chunks)"
            ).fetchall()
        }
        for col_name, col_def in _V1_COLUMNS:
            if col_name not in existing:
                self._conn.execute(
                    f"ALTER TABLE knowledge_chunks ADD COLUMN {col_name} {col_def}"
                )

    # ------------------------------------------------------------------
    # MemoryBackend interface
    # ------------------------------------------------------------------

    def store(  # type: ignore[override]
        self,
        content: str,
        *,
        source: str = "",
        doc_type: str = "",
        doc_id: Optional[str] = None,
        title: str = "",
        author: str = "",
        participants: Optional[List[str]] = None,
        timestamp: Optional[Union[datetime, str]] = None,
        thread_id: Optional[str] = None,
        url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        chunk_index: int = 0,
        # v1 schema additions
        source_id: str = "",
        participants_raw: Optional[List[str]] = None,
        channel: Optional[str] = None,
        content_hash: str = "",
        embedding: Optional[bytes] = None,
        embedding_model_version: str = "",
        last_synced: Optional[Union[datetime, str, float]] = None,
    ) -> str:
        """Persist a content chunk and return its unique chunk id.

        All source-level fields are merged into the stored metadata so that
        ``retrieve()`` results carry full provenance.
        """
        chunk_id = str(uuid.uuid4())
        if doc_id is None:
            doc_id = str(uuid.uuid4())

        ts_str = _to_iso(timestamp)
        participants_json = json.dumps(participants or [])
        participants_raw_json = json.dumps(participants_raw or [])
        last_synced_epoch = (
            _to_epoch(last_synced) if last_synced is not None else time.time()
        )

        # Merge provenance fields into metadata for easy access in results
        combined_meta: Dict[str, Any] = dict(metadata or {})
        combined_meta["chunk_id"] = chunk_id
        combined_meta["source"] = source
        combined_meta["source_id"] = source_id
        combined_meta["doc_type"] = doc_type
        combined_meta["doc_id"] = doc_id
        combined_meta["title"] = title
        combined_meta["author"] = author
        combined_meta["participants"] = participants or []
        combined_meta["participants_raw"] = participants_raw or []
        combined_meta["timestamp"] = ts_str
        combined_meta["thread_id"] = thread_id or ""
        combined_meta["channel"] = channel or ""
        combined_meta["url"] = url or ""
        combined_meta["chunk_index"] = chunk_index
        combined_meta["content_hash"] = content_hash
        combined_meta["embedding_model_version"] = embedding_model_version

        meta_json = json.dumps(combined_meta)

        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO knowledge_chunks
                (id, doc_id, content, source, source_id, doc_type, title, author,
                 participants, participants_raw, timestamp, thread_id, channel,
                 url, metadata, chunk_index, embedding, embedding_model_version,
                 content_hash, last_synced, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                doc_id,
                content,
                source,
                source_id,
                doc_type,
                title,
                author,
                participants_json,
                participants_raw_json,
                ts_str,
                thread_id or "",
                channel or "",
                url or "",
                meta_json,
                chunk_index,
                embedding,
                embedding_model_version,
                content_hash,
                last_synced_epoch,
                time.time(),
            ),
        )
        self._conn.commit()

        # If the natural-key (source, source_id, chunk_index) already existed
        # SQLite skipped the insert. Re-runs of the dogfood script or a
        # SyncEngine that re-emits a known document hit this path; return
        # the existing chunk id so callers don't see two different identities
        # for the same row, and suppress the MEMORY_STORE event (nothing new
        # was actually written).
        if cur.rowcount == 0:
            existing = self._conn.execute(
                "SELECT id FROM knowledge_chunks "
                "WHERE source=? AND source_id=? AND chunk_index=?",
                (source, source_id, chunk_index),
            ).fetchone()
            if existing is not None:
                return existing["id"]
            return chunk_id

        get_event_bus().publish(
            EventType.MEMORY_STORE,
            {
                "backend": self.backend_id,
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "source": source,
                "doc_type": doc_type,
            },
        )
        return chunk_id

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        source: Optional[str] = None,
        doc_type: Optional[str] = None,
        author: Optional[str] = None,
        since: Optional[Union[datetime, str]] = None,
        until: Optional[Union[datetime, str]] = None,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Search using FTS5 BM25 with optional column filters.

        Parameters
        ----------
        query:    Full-text search query.
        top_k:    Maximum number of results.
        source:   Restrict to chunks from this source (e.g. "gmail").
        doc_type: Restrict to chunks of this type (e.g. "email").
        author:   Restrict to chunks authored by this person.
        since:    Exclude chunks whose timestamp is earlier than this value.
        until:    Exclude chunks whose timestamp is later than this value.
        """
        if not query.strip():
            return []

        since_str = _to_iso(since) if since is not None else None
        until_str = _to_iso(until) if until is not None else None

        # Build the WHERE clause for filter columns
        filters: List[str] = []
        params: List[Any] = []

        if source is not None:
            filters.append("kc.source = ?")
            params.append(source)
        if doc_type is not None:
            filters.append("kc.doc_type = ?")
            params.append(doc_type)
        if author is not None:
            filters.append("kc.author = ?")
            params.append(author)
        if since_str:
            filters.append("kc.timestamp >= ?")
            params.append(since_str)
        if until_str:
            filters.append("kc.timestamp <= ?")
            params.append(until_str)

        # Always exclude tombstoned rows.
        filters.append("kc.deleted_at IS NULL")

        where_clause = "AND " + " AND ".join(filters)

        # FTS5 bm25() returns negative scores; abs() gives a positive rank
        sql = f"""
            SELECT
                kc.id,
                kc.content,
                kc.source,
                kc.metadata,
                abs(bm25(knowledge_fts)) AS score
            FROM knowledge_fts
            JOIN knowledge_chunks kc ON knowledge_fts.rowid = kc.rowid
            WHERE knowledge_fts MATCH ?
            {where_clause}
            ORDER BY score DESC
            LIMIT ?
        """

        try:
            rows = self._conn.execute(sql, [query] + params + [top_k]).fetchall()
        except sqlite3.OperationalError:
            # Malformed FTS query — return empty rather than crash
            return []

        results: List[RetrievalResult] = []
        for row in rows:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            # Ensure chunk_id is always present in metadata (backfill for
            # rows stored before this field was added to combined_meta).
            if "chunk_id" not in meta:
                meta["chunk_id"] = row["id"]
            results.append(
                RetrievalResult(
                    content=row["content"],
                    score=float(row["score"]),
                    source=row["source"],
                    metadata=meta,
                )
            )

        get_event_bus().publish(
            EventType.MEMORY_RETRIEVE,
            {
                "backend": self.backend_id,
                "query": query,
                "num_results": len(results),
                "filters": {
                    "source": source,
                    "doc_type": doc_type,
                    "author": author,
                    "since": since_str,
                    "until": until_str,
                },
            },
        )
        return results

    def delete(self, doc_id: str) -> bool:
        """Delete all chunks with the given *doc_id*. Returns True if any existed."""
        cur = self._conn.execute(
            "DELETE FROM knowledge_chunks WHERE doc_id = ?", (doc_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self) -> None:
        """Remove all stored chunks."""
        self._conn.executescript(
            "DELETE FROM knowledge_chunks; DELETE FROM knowledge_fts;"
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Extra helpers
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the total number of stored chunks."""
        row = self._conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()
        return row[0] if row else 0

    def distinct_sources(self) -> List[str]:
        """Return the sorted list of distinct ``source`` values currently indexed.

        Used by the research agent to populate the system prompt with the
        sources the user actually has connected — so the model doesn't
        mention "Notion" or "Apple Notes" when nothing from those sources
        is in the corpus.
        """
        rows = self._conn.execute(
            "SELECT DISTINCT source FROM knowledge_chunks "
            "WHERE source IS NOT NULL AND source != '' "
            "ORDER BY source"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["KnowledgeStore"]
