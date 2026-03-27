# Deep Research Phase 1: Connector Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the connector framework, ingestion pipeline, knowledge store, and two connectors (Gmail + Obsidian) that form the foundation for the full Deep Research feature.

**Architecture:** A new `BaseConnector` ABC with `ConnectorRegistry` provides the plugin interface. Connectors yield normalized `Document` objects that flow through a pipeline (normalize → dedup → chunk → index) into an extended SQLite store with FTS5 and source-aware columns. A `knowledge_search` tool exposes filtered BM25 retrieval to agents. A `SyncEngine` orchestrates connectors with checkpoint/resume. CLI `jarvis connect` provides text-based setup.

**Tech Stack:** Python 3.10+, SQLite/FTS5 (via existing Rust backend), httpx (for Gmail API), Click (for CLI), pytest + respx (for tests)

**Spec:** `docs/superpowers/specs/2026-03-25-deep-research-setup-design.md` — Sections 5, 6, 7, 10, Phase 1

---

## File Structure

```
src/openjarvis/
├── connectors/
│   ├── __init__.py              # Auto-imports, ConnectorRegistry re-export
│   ├── _stubs.py                # BaseConnector ABC, Document, Attachment, SyncStatus
│   ├── store.py                 # KnowledgeStore (extended SQLite with source-aware schema)
│   ├── chunker.py               # Type-aware semantic chunker
│   ├── pipeline.py              # Ingestion pipeline: normalize → dedup → chunk → index
│   ├── sync_engine.py           # SyncEngine: orchestrate connectors with checkpoint/resume
│   ├── oauth.py                 # Shared OAuth helper (localhost callback server)
│   ├── gmail.py                 # Gmail connector
│   └── obsidian.py              # Obsidian/Markdown connector
├── tools/
│   └── knowledge_search.py      # knowledge_search tool for agents
├── core/
│   └── registry.py              # (modify) Add ConnectorRegistry
├── cli/
│   ├── __init__.py              # (modify) Add connect command
│   └── connect_cmd.py           # jarvis connect CLI command
tests/
├── conftest.py                  # (modify) Clear ConnectorRegistry between tests
├── connectors/
│   ├── __init__.py
│   ├── test_stubs.py            # BaseConnector, Document, SyncStatus tests
│   ├── test_store.py            # KnowledgeStore tests
│   ├── test_chunker.py          # Semantic chunker tests
│   ├── test_pipeline.py         # Ingestion pipeline tests
│   ├── test_sync_engine.py      # SyncEngine tests
│   ├── test_gmail.py            # Gmail connector tests (mocked API)
│   └── test_obsidian.py         # Obsidian connector tests (temp dirs)
├── tools/
│   └── test_knowledge_search.py # knowledge_search tool tests
├── cli/
│   └── test_connect.py          # CLI connect command tests
```

---

### Task 1: ConnectorRegistry + Base Types

**Files:**
- Modify: `src/openjarvis/core/registry.py`
- Create: `src/openjarvis/connectors/_stubs.py`
- Create: `src/openjarvis/connectors/__init__.py`
- Modify: `tests/conftest.py`
- Create: `tests/connectors/__init__.py`
- Create: `tests/connectors/test_stubs.py`

- [ ] **Step 1: Add ConnectorRegistry to registry.py**

Open `src/openjarvis/core/registry.py`. At the bottom, after the existing registry classes (after `CompressionRegistry`), add:

```python
class ConnectorRegistry(RegistryBase[Any]):
    """Registry for data source connectors (Gmail, Slack, etc.)."""
```

Also add `ConnectorRegistry` to the imports in the file's `__all__` or wherever the other registries are exported. Find the existing pattern — the other registries are bare class definitions at module level.

- [ ] **Step 2: Clear ConnectorRegistry in test conftest**

Open `tests/conftest.py`. Add `ConnectorRegistry` to the import:

```python
from openjarvis.core.registry import (
    AgentRegistry,
    BenchmarkRegistry,
    ChannelRegistry,
    CompressionRegistry,
    ConnectorRegistry,  # ADD THIS
    EngineRegistry,
    MemoryRegistry,
    ModelRegistry,
    RouterPolicyRegistry,
    SpeechRegistry,
    ToolRegistry,
)
```

In the `_clean_registries` fixture, add `ConnectorRegistry.clear()` after `CompressionRegistry.clear()`.

- [ ] **Step 3: Create connectors _stubs.py with base types**

Create `src/openjarvis/connectors/_stubs.py`:

```python
"""Base types for data source connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from openjarvis.tools._stubs import ToolSpec


@dataclass(slots=True)
class Attachment:
    """A file attached to a document (email attachment, shared file, etc.)."""

    filename: str
    mime_type: str
    size_bytes: int
    sha256: str = ""
    content: bytes = field(default=b"", repr=False)


@dataclass(slots=True)
class Document:
    """Universal schema for data from any connector.

    All connectors normalize their output to this format before ingestion.
    """

    doc_id: str
    source: str
    doc_type: str
    content: str
    title: str = ""
    author: str = ""
    participants: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    thread_id: Optional[str] = None
    url: Optional[str] = None
    attachments: List[Attachment] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SyncStatus:
    """Progress of a connector's sync operation."""

    state: str = "idle"
    items_synced: int = 0
    items_total: int = 0
    last_sync: Optional[datetime] = None
    cursor: Optional[str] = None
    error: Optional[str] = None


class BaseConnector(ABC):
    """Abstract base for data source connectors.

    Each connector knows how to authenticate with a service, bulk-sync
    its data as ``Document`` objects, and optionally expose MCP tools
    for real-time agent queries.
    """

    connector_id: str
    display_name: str
    auth_type: str  # "oauth" | "local" | "bridge" | "filesystem"

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the connector has valid credentials."""

    @abstractmethod
    def disconnect(self) -> None:
        """Revoke credentials and clean up."""

    @abstractmethod
    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield documents from the data source.

        If *since* is given, only return items created/modified after that time.
        If *cursor* is given, resume from a previous checkpoint.
        """

    @abstractmethod
    def sync_status(self) -> SyncStatus:
        """Return current sync progress."""

    def auth_url(self) -> str:
        """Generate an OAuth consent URL.  Only relevant for auth_type='oauth'."""
        raise NotImplementedError(f"{self.connector_id} does not use OAuth")

    def handle_callback(self, code: str) -> None:
        """Handle the OAuth callback.  Only relevant for auth_type='oauth'."""
        raise NotImplementedError(f"{self.connector_id} does not use OAuth")

    def mcp_tools(self) -> List[ToolSpec]:
        """Return MCP tool specs for real-time agent queries.  Optional."""
        return []
```

- [ ] **Step 4: Create connectors __init__.py**

Create `src/openjarvis/connectors/__init__.py`:

```python
"""Data source connectors for Deep Research."""

from openjarvis.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)

__all__ = ["Attachment", "BaseConnector", "Document", "SyncStatus"]
```

- [ ] **Step 5: Write tests for base types**

Create `tests/connectors/__init__.py` (empty file).

Create `tests/connectors/test_stubs.py`:

```python
"""Tests for connector base types and registry."""

from __future__ import annotations

from datetime import datetime
from typing import Iterator, List, Optional

from openjarvis.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec


class FakeConnector(BaseConnector):
    connector_id = "fake"
    display_name = "Fake"
    auth_type = "filesystem"

    def __init__(self) -> None:
        self._connected = True

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        yield Document(
            doc_id="fake:1",
            source="fake",
            doc_type="note",
            content="Hello world",
            title="Test",
        )

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=1, items_total=1)


def test_document_creation() -> None:
    doc = Document(
        doc_id="gmail:abc123",
        source="gmail",
        doc_type="email",
        content="Meeting tomorrow at 3pm",
        title="Re: Project sync",
        author="alice@example.com",
        participants=["alice@example.com", "bob@example.com"],
    )
    assert doc.source == "gmail"
    assert doc.doc_type == "email"
    assert doc.thread_id is None
    assert doc.attachments == []


def test_attachment_creation() -> None:
    att = Attachment(
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        sha256="abcdef1234567890",
    )
    assert att.filename == "report.pdf"
    assert att.content == b""


def test_sync_status_defaults() -> None:
    status = SyncStatus()
    assert status.state == "idle"
    assert status.items_synced == 0
    assert status.cursor is None
    assert status.error is None


def test_base_connector_lifecycle() -> None:
    conn = FakeConnector()
    assert conn.is_connected()
    docs = list(conn.sync())
    assert len(docs) == 1
    assert docs[0].doc_id == "fake:1"
    assert conn.sync_status().state == "idle"
    conn.disconnect()
    assert not conn.is_connected()


def test_connector_registry() -> None:
    ConnectorRegistry.register_value("fake", FakeConnector)
    assert ConnectorRegistry.contains("fake")
    cls = ConnectorRegistry.get("fake")
    instance = cls()
    assert instance.connector_id == "fake"


def test_mcp_tools_default_empty() -> None:
    conn = FakeConnector()
    assert conn.mcp_tools() == []
```

- [ ] **Step 6: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_stubs.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/core/registry.py src/openjarvis/connectors/ tests/conftest.py tests/connectors/
git commit -m "feat: add ConnectorRegistry and base connector types (Document, SyncStatus, BaseConnector)"
```

---

### Task 2: KnowledgeStore (Extended SQLite Schema)

**Files:**
- Create: `src/openjarvis/connectors/store.py`
- Create: `tests/connectors/test_store.py`

- [ ] **Step 1: Write failing tests for KnowledgeStore**

Create `tests/connectors/test_store.py`:

```python
"""Tests for KnowledgeStore — extended SQLite with source-aware columns."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from openjarvis.connectors.store import KnowledgeStore


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(db_path=str(tmp_path / "test_knowledge.db"))


def test_store_and_retrieve_basic(store: KnowledgeStore) -> None:
    doc_id = store.store(
        content="Meeting about Kubernetes migration",
        source="gmail",
        doc_type="email",
        title="Re: K8s migration",
        author="alice@example.com",
        timestamp="2024-03-15T10:00:00",
    )
    assert doc_id
    results = store.retrieve("Kubernetes migration", top_k=5)
    assert len(results) >= 1
    assert "Kubernetes" in results[0].content


def test_retrieve_filter_by_source(store: KnowledgeStore) -> None:
    store.store(content="K8s discussion in Slack", source="slack", doc_type="message")
    store.store(content="K8s email thread", source="gmail", doc_type="email")
    results = store.retrieve("K8s", top_k=10, source="gmail")
    assert all(r.metadata.get("source") == "gmail" for r in results)


def test_retrieve_filter_by_doc_type(store: KnowledgeStore) -> None:
    store.store(content="API design proposal", source="gdrive", doc_type="document")
    store.store(content="API design discussion", source="slack", doc_type="message")
    results = store.retrieve("API design", top_k=10, doc_type="document")
    assert all(r.metadata.get("doc_type") == "document" for r in results)


def test_retrieve_filter_by_author(store: KnowledgeStore) -> None:
    store.store(content="Budget report", source="gmail", doc_type="email", author="alice")
    store.store(content="Budget concerns", source="gmail", doc_type="email", author="bob")
    results = store.retrieve("budget", top_k=10, author="alice")
    assert all(r.metadata.get("author") == "alice" for r in results)


def test_retrieve_filter_by_timestamp(store: KnowledgeStore) -> None:
    store.store(
        content="Old meeting notes",
        source="slack",
        doc_type="message",
        timestamp="2024-01-01T00:00:00",
    )
    store.store(
        content="Recent meeting notes",
        source="slack",
        doc_type="message",
        timestamp="2024-06-01T00:00:00",
    )
    results = store.retrieve(
        "meeting notes", top_k=10, since="2024-03-01T00:00:00"
    )
    assert len(results) == 1
    assert "Recent" in results[0].content


def test_delete_by_doc_id(store: KnowledgeStore) -> None:
    chunk_id = store.store(content="Delete me", source="gmail", doc_type="email")
    assert store.delete(chunk_id)
    results = store.retrieve("Delete me", top_k=5)
    assert len(results) == 0


def test_clear(store: KnowledgeStore) -> None:
    store.store(content="Item 1", source="gmail", doc_type="email")
    store.store(content="Item 2", source="slack", doc_type="message")
    store.clear()
    results = store.retrieve("Item", top_k=10)
    assert len(results) == 0


def test_store_with_metadata(store: KnowledgeStore) -> None:
    store.store(
        content="Labeled email",
        source="gmail",
        doc_type="email",
        metadata={"labels": ["important", "inbox"], "thread_id": "t123"},
    )
    results = store.retrieve("Labeled email", top_k=5)
    assert results[0].metadata.get("labels") == ["important", "inbox"]


def test_store_preserves_url(store: KnowledgeStore) -> None:
    store.store(
        content="Linked document",
        source="gdrive",
        doc_type="document",
        url="https://drive.google.com/d/abc123",
    )
    results = store.retrieve("Linked document", top_k=5)
    assert results[0].metadata.get("url") == "https://drive.google.com/d/abc123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_store.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'openjarvis.connectors.store'`

- [ ] **Step 3: Implement KnowledgeStore**

Create `src/openjarvis/connectors/store.py`:

```python
"""KnowledgeStore — extended SQLite backend with source-aware columns for Deep Research."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.events import EventType, get_event_bus
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    doc_id        TEXT NOT NULL DEFAULT '',
    content       TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT '',
    doc_type      TEXT NOT NULL DEFAULT '',
    title         TEXT DEFAULT '',
    author        TEXT DEFAULT '',
    participants  TEXT DEFAULT '[]',
    timestamp     TEXT NOT NULL DEFAULT '',
    thread_id     TEXT DEFAULT '',
    url           TEXT DEFAULT '',
    metadata      TEXT DEFAULT '{}',
    chunk_index   INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    content, title, author,
    content=documents,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, content, title, author)
    VALUES (new.rowid, new.content, new.title, new.author);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, content, title, author)
    VALUES ('delete', old.rowid, old.content, old.title, old.author);
END;

CREATE INDEX IF NOT EXISTS idx_source ON documents(source);
CREATE INDEX IF NOT EXISTS idx_doc_type ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_author ON documents(author);
CREATE INDEX IF NOT EXISTS idx_timestamp ON documents(timestamp);
CREATE INDEX IF NOT EXISTS idx_thread ON documents(thread_id);
CREATE INDEX IF NOT EXISTS idx_doc_id ON documents(doc_id);
"""


class KnowledgeStore(MemoryBackend):
    """SQLite + FTS5 backend with source-aware columns for Deep Research.

    Extends the base MemoryBackend with filtered retrieval by source,
    doc_type, author, and timestamp.  Uses pure Python sqlite3 so we
    don't depend on the Rust extension for the new schema.
    """

    backend_id: str = "knowledge"

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(DEFAULT_CONFIG_DIR / "knowledge.db")
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def store(
        self,
        content: str,
        *,
        source: str = "",
        doc_type: str = "",
        doc_id: str = "",
        title: str = "",
        author: str = "",
        participants: Optional[List[str]] = None,
        timestamp: str = "",
        thread_id: str = "",
        url: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        chunk_index: int = 0,
    ) -> str:
        chunk_id = uuid.uuid4().hex[:16]
        now = datetime.now().isoformat()
        if not timestamp:
            timestamp = now
        meta = metadata or {}
        # Store source-level fields in metadata too so retrieve() can return them
        meta.setdefault("source", source)
        meta.setdefault("doc_type", doc_type)
        meta.setdefault("author", author)
        meta.setdefault("title", title)
        if url:
            meta.setdefault("url", url)
        if thread_id:
            meta.setdefault("thread_id", thread_id)

        self._conn.execute(
            """INSERT INTO documents
               (id, doc_id, content, source, doc_type, title, author,
                participants, timestamp, thread_id, url, metadata,
                chunk_index, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chunk_id,
                doc_id,
                content,
                source,
                doc_type,
                title,
                author,
                json.dumps(participants or []),
                timestamp,
                thread_id,
                url,
                json.dumps(meta),
                chunk_index,
                now,
            ),
        )
        self._conn.commit()

        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_STORE,
            {"backend": "knowledge", "doc_id": chunk_id, "source": source},
        )
        return chunk_id

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        source: str = "",
        doc_type: str = "",
        author: str = "",
        since: str = "",
        until: str = "",
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        # Build FTS5 query
        # Escape double quotes in user query for FTS5
        safe_query = query.replace('"', '""')
        fts_clause = f'documents_fts MATCH \\"{safe_query}\\"'

        # Build WHERE filters on the main table
        filters: list[str] = []
        params: list[str] = []
        if source:
            filters.append("d.source = ?")
            params.append(source)
        if doc_type:
            filters.append("d.doc_type = ?")
            params.append(doc_type)
        if author:
            filters.append("d.author = ?")
            params.append(author)
        if since:
            filters.append("d.timestamp >= ?")
            params.append(since)
        if until:
            filters.append("d.timestamp <= ?")
            params.append(until)

        where = " AND ".join(filters) if filters else "1=1"

        sql = f"""
            SELECT d.content, d.metadata, bm25(documents_fts) AS score
            FROM documents_fts
            JOIN documents d ON d.rowid = documents_fts.rowid
            WHERE documents_fts MATCH ? AND {where}
            ORDER BY score
            LIMIT ?
        """
        try:
            rows = self._conn.execute(sql, [safe_query, *params, top_k]).fetchall()
        except sqlite3.OperationalError:
            return []

        results = []
        for content, meta_json, score in rows:
            meta = json.loads(meta_json) if meta_json else {}
            results.append(
                RetrievalResult(
                    content=content,
                    score=abs(score),  # bm25() returns negative scores
                    source=meta.get("source", ""),
                    metadata=meta,
                )
            )

        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_RETRIEVE,
            {"backend": "knowledge", "query": query, "num_results": len(results)},
        )
        return results

    def delete(self, doc_id: str) -> bool:
        cursor = self._conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def clear(self) -> None:
        self._conn.execute("DELETE FROM documents")
        self._conn.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_store.py -v`

Expected: All 10 tests PASS. If FTS5 syntax issues arise, adjust the MATCH query escaping — SQLite FTS5 can be picky about special characters.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/store.py tests/connectors/test_store.py
git commit -m "feat: add KnowledgeStore with source-aware SQLite schema and filtered BM25 retrieval"
```

---

### Task 3: Type-Aware Semantic Chunker

**Files:**
- Create: `src/openjarvis/connectors/chunker.py`
- Create: `tests/connectors/test_chunker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_chunker.py`:

```python
"""Tests for type-aware semantic chunker."""

from __future__ import annotations

from openjarvis.connectors.chunker import SemanticChunker, ChunkResult


def test_short_message_not_split() -> None:
    """Messages under chunk limit should stay as one chunk."""
    chunker = SemanticChunker(max_tokens=512)
    results = chunker.chunk("Hey, are we meeting tomorrow?", doc_type="message")
    assert len(results) == 1
    assert results[0].content == "Hey, are we meeting tomorrow?"


def test_long_document_splits_on_sections() -> None:
    """Documents should split on ## headings first."""
    text = (
        "## Introduction\n\n"
        + "This is the intro paragraph. " * 50
        + "\n\n## Methods\n\n"
        + "This is the methods section. " * 50
    )
    chunker = SemanticChunker(max_tokens=100)
    results = chunker.chunk(text, doc_type="document")
    assert len(results) >= 2
    assert results[0].metadata.get("section") == "Introduction"
    assert results[1].metadata.get("section") == "Methods"


def test_document_splits_on_paragraphs_within_section() -> None:
    """Within a section, split on paragraph boundaries."""
    text = "## Overview\n\n" + "\n\n".join(
        [f"Paragraph {i}. " * 30 for i in range(5)]
    )
    chunker = SemanticChunker(max_tokens=80)
    results = chunker.chunk(text, doc_type="document")
    assert len(results) >= 3
    for r in results:
        assert r.metadata.get("section") == "Overview"


def test_never_splits_mid_sentence() -> None:
    """Chunks should end at sentence boundaries."""
    text = "First sentence here. Second sentence here. Third sentence here. " * 30
    chunker = SemanticChunker(max_tokens=20)
    results = chunker.chunk(text, doc_type="document")
    for r in results:
        stripped = r.content.strip()
        assert stripped.endswith(".") or stripped.endswith("?") or stripped.endswith("!"), (
            f"Chunk does not end at sentence boundary: ...{stripped[-40:]}"
        )


def test_email_thread_splits_on_reply_boundaries() -> None:
    """Email threads should split on reply markers."""
    text = (
        "Hi team, let's discuss.\n\n"
        "On Mon, Jan 1, Alice wrote:\n> Previous message. " * 20
        + "\n\nThat sounds good to me.\n\n"
        "On Tue, Jan 2, Bob wrote:\n> Another reply. " * 20
    )
    chunker = SemanticChunker(max_tokens=50)
    results = chunker.chunk(text, doc_type="email")
    # Should split on "On ... wrote:" boundaries
    assert len(results) >= 2


def test_event_stays_as_single_chunk() -> None:
    """Events should always be one chunk."""
    text = "Team Standup\nAttendees: Alice, Bob, Carol\nLocation: Room 3\nAgenda: Sprint review"
    chunker = SemanticChunker(max_tokens=512)
    results = chunker.chunk(text, doc_type="event")
    assert len(results) == 1


def test_contact_stays_as_single_chunk() -> None:
    """Contacts should always be one chunk."""
    text = "Alice Smith\nalice@example.com\n+1-555-0100\nAcme Corp, VP Engineering"
    chunker = SemanticChunker(max_tokens=512)
    results = chunker.chunk(text, doc_type="contact")
    assert len(results) == 1


def test_metadata_inherited_to_chunks() -> None:
    """Parent metadata should carry to all chunks."""
    text = "## Part 1\n\n" + "Content. " * 100 + "\n\n## Part 2\n\n" + "More content. " * 100
    chunker = SemanticChunker(max_tokens=60)
    parent_meta = {"title": "My Doc", "author": "Alice", "source": "gdrive"}
    results = chunker.chunk(text, doc_type="document", metadata=parent_meta)
    for r in results:
        assert r.metadata["title"] == "My Doc"
        assert r.metadata["author"] == "Alice"


def test_chunk_result_has_index() -> None:
    """Each chunk should have a sequential index."""
    text = "\n\n".join([f"Paragraph {i}. " * 30 for i in range(5)])
    chunker = SemanticChunker(max_tokens=50)
    results = chunker.chunk(text, doc_type="document")
    for i, r in enumerate(results):
        assert r.index == i
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_chunker.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement SemanticChunker**

Create `src/openjarvis/connectors/chunker.py`:

```python
"""Type-aware semantic chunker for Deep Research ingestion.

Splits documents respecting structural boundaries:
- Sections (## headings) → paragraphs → sentences.
- Never splits mid-sentence.
- Chunk size defaults to reranker max context (512 for ColBERT, 256 for MiniLM).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"])")
_SECTION_RE = re.compile(r"(?m)^##\s+(.+)$")
_EMAIL_REPLY_RE = re.compile(r"(?m)^On .+wrote:\s*$")


def _count_tokens(text: str) -> int:
    """Approximate token count via whitespace split."""
    return len(text.split())


def _split_sentences(text: str) -> List[str]:
    """Split text on sentence boundaries."""
    parts = _SENTENCE_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


@dataclass(slots=True)
class ChunkResult:
    """A single chunk produced by the semantic chunker."""

    content: str
    index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class SemanticChunker:
    """Type-aware chunker that respects structural boundaries."""

    def __init__(self, max_tokens: int = 512) -> None:
        self.max_tokens = max_tokens

    def chunk(
        self,
        text: str,
        *,
        doc_type: str = "document",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[ChunkResult]:
        parent_meta = metadata or {}

        # Events and contacts: always single chunk
        if doc_type in ("event", "contact"):
            return [ChunkResult(content=text.strip(), index=0, metadata=dict(parent_meta))]

        # Short text: keep as single chunk
        if _count_tokens(text) <= self.max_tokens:
            return [ChunkResult(content=text.strip(), index=0, metadata=dict(parent_meta))]

        # Route to type-specific splitter
        if doc_type == "email":
            raw_chunks = self._split_email(text)
        elif doc_type == "message":
            raw_chunks = self._split_messages(text)
        else:
            raw_chunks = self._split_document(text)

        # Assign indexes and inherit parent metadata
        results = []
        for i, (content, chunk_meta) in enumerate(raw_chunks):
            merged = {**parent_meta, **chunk_meta}
            results.append(ChunkResult(content=content.strip(), index=i, metadata=merged))
        return results

    def _split_document(self, text: str) -> List[tuple[str, dict]]:
        """Split on section headings, then paragraphs, then sentences."""
        sections = self._extract_sections(text)
        chunks: list[tuple[str, dict]] = []
        for section_title, section_text in sections:
            meta = {"section": section_title} if section_title else {}
            paragraphs = [p.strip() for p in section_text.split("\n\n") if p.strip()]
            buffer = ""
            for para in paragraphs:
                candidate = (buffer + "\n\n" + para).strip() if buffer else para
                if _count_tokens(candidate) <= self.max_tokens:
                    buffer = candidate
                else:
                    if buffer:
                        chunks.append((buffer, dict(meta)))
                    if _count_tokens(para) <= self.max_tokens:
                        buffer = para
                    else:
                        # Paragraph too big — split on sentences
                        for sent_chunk in self._split_by_sentences(para):
                            chunks.append((sent_chunk, dict(meta)))
                        buffer = ""
            if buffer:
                chunks.append((buffer, dict(meta)))
        return chunks

    def _split_email(self, text: str) -> List[tuple[str, dict]]:
        """Split email threads on reply boundaries."""
        parts = _EMAIL_REPLY_RE.split(text)
        chunks: list[tuple[str, dict]] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if _count_tokens(part) <= self.max_tokens:
                chunks.append((part, {}))
            else:
                chunks.extend(self._split_document(part))
        return chunks

    def _split_messages(self, text: str) -> List[tuple[str, dict]]:
        """Split message threads — treat each double-newline block as a message."""
        messages = [m.strip() for m in text.split("\n\n") if m.strip()]
        chunks: list[tuple[str, dict]] = []
        buffer = ""
        for msg in messages:
            candidate = (buffer + "\n\n" + msg).strip() if buffer else msg
            if _count_tokens(candidate) <= self.max_tokens:
                buffer = candidate
            else:
                if buffer:
                    chunks.append((buffer, {}))
                if _count_tokens(msg) <= self.max_tokens:
                    buffer = msg
                else:
                    for sent_chunk in self._split_by_sentences(msg):
                        chunks.append((sent_chunk, {}))
                    buffer = ""
        if buffer:
            chunks.append((buffer, {}))
        return chunks

    def _extract_sections(self, text: str) -> List[tuple[str, str]]:
        """Split text into (section_title, section_content) pairs."""
        matches = list(_SECTION_RE.finditer(text))
        if not matches:
            return [("", text)]
        sections: list[tuple[str, str]] = []
        # Content before first heading
        before = text[: matches[0].start()].strip()
        if before:
            sections.append(("", before))
        for i, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if body:
                sections.append((title, body))
        return sections

    def _split_by_sentences(self, text: str) -> List[str]:
        """Split text into sentence-boundary chunks that fit within max_tokens."""
        sentences = _split_sentences(text)
        if not sentences:
            return [text]
        chunks: list[str] = []
        buffer = ""
        for sent in sentences:
            candidate = (buffer + " " + sent).strip() if buffer else sent
            if _count_tokens(candidate) <= self.max_tokens:
                buffer = candidate
            else:
                if buffer:
                    chunks.append(buffer)
                buffer = sent
        if buffer:
            chunks.append(buffer)
        return chunks
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_chunker.py -v`

Expected: All 10 tests PASS. The sentence-boundary test may need tuning if some chunks end up without terminal punctuation due to the final chunk of a section — adjust the test assertion to allow the last chunk in a sequence to not end with punctuation.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/chunker.py tests/connectors/test_chunker.py
git commit -m "feat: add type-aware semantic chunker with section/paragraph/sentence splitting"
```

---

### Task 4: Ingestion Pipeline

**Files:**
- Create: `src/openjarvis/connectors/pipeline.py`
- Create: `tests/connectors/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_pipeline.py`:

```python
"""Tests for the ingestion pipeline: Document → chunk → store."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from openjarvis.connectors._stubs import Attachment, Document
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.store import KnowledgeStore


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def pipeline(store: KnowledgeStore) -> IngestionPipeline:
    return IngestionPipeline(store=store)


def test_ingest_single_document(pipeline: IngestionPipeline, store: KnowledgeStore) -> None:
    doc = Document(
        doc_id="gmail:abc",
        source="gmail",
        doc_type="email",
        content="Meeting tomorrow at 3pm to discuss the roadmap.",
        title="Re: Roadmap",
        author="alice@example.com",
        participants=["alice@example.com", "bob@example.com"],
        timestamp=datetime(2024, 3, 15, 10, 0),
    )
    count = pipeline.ingest([doc])
    assert count == 1
    results = store.retrieve("roadmap meeting", top_k=5)
    assert len(results) >= 1
    assert "roadmap" in results[0].content.lower()


def test_ingest_deduplicates_by_doc_id(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    doc = Document(
        doc_id="gmail:dup1",
        source="gmail",
        doc_type="email",
        content="Duplicate email content.",
    )
    pipeline.ingest([doc])
    pipeline.ingest([doc])  # Ingest same doc_id again
    results = store.retrieve("Duplicate email", top_k=10)
    assert len(results) == 1


def test_ingest_long_document_creates_multiple_chunks(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    long_content = "\n\n".join([f"Paragraph {i}. " * 60 for i in range(10)])
    doc = Document(
        doc_id="gdrive:longdoc",
        source="gdrive",
        doc_type="document",
        content=long_content,
        title="Long Report",
        author="carol",
    )
    count = pipeline.ingest([doc])
    assert count > 1
    results = store.retrieve("Paragraph", top_k=20)
    assert len(results) > 1
    # All chunks should inherit parent metadata
    for r in results:
        assert r.metadata.get("source") == "gdrive"
        assert r.metadata.get("author") == "carol"


def test_ingest_event_single_chunk(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    doc = Document(
        doc_id="calendar:evt1",
        source="calendar",
        doc_type="event",
        content="Sprint Review\nAttendees: Alice, Bob\nRoom 3",
        title="Sprint Review",
    )
    count = pipeline.ingest([doc])
    assert count == 1


def test_ingest_multiple_sources(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    docs = [
        Document(doc_id="gmail:1", source="gmail", doc_type="email", content="Email about budget"),
        Document(doc_id="slack:1", source="slack", doc_type="message", content="Slack msg about budget"),
    ]
    count = pipeline.ingest(docs)
    assert count == 2
    # Can filter by source
    gmail_results = store.retrieve("budget", top_k=10, source="gmail")
    assert len(gmail_results) == 1
    slack_results = store.retrieve("budget", top_k=10, source="slack")
    assert len(slack_results) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_pipeline.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement IngestionPipeline**

Create `src/openjarvis/connectors/pipeline.py`:

```python
"""Ingestion pipeline: normalize → deduplicate → chunk → index."""

from __future__ import annotations

import logging
from typing import Iterable

from openjarvis.connectors._stubs import Document
from openjarvis.connectors.chunker import SemanticChunker
from openjarvis.connectors.store import KnowledgeStore

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Processes Documents from connectors into the KnowledgeStore.

    Handles deduplication (by doc_id), chunking (type-aware),
    and indexing (dual-write to SQLite/FTS5).
    """

    def __init__(
        self,
        store: KnowledgeStore,
        *,
        max_tokens: int = 512,
    ) -> None:
        self._store = store
        self._chunker = SemanticChunker(max_tokens=max_tokens)
        self._seen_doc_ids: set[str] = set()
        self._load_existing_doc_ids()

    def _load_existing_doc_ids(self) -> None:
        """Load already-ingested doc_ids from the store to support dedup."""
        try:
            rows = self._store._conn.execute(
                "SELECT DISTINCT doc_id FROM documents"
            ).fetchall()
            self._seen_doc_ids = {r[0] for r in rows}
        except Exception:
            self._seen_doc_ids = set()

    def ingest(self, documents: Iterable[Document]) -> int:
        """Ingest documents into the knowledge store.

        Returns the number of chunks stored.
        """
        total_chunks = 0
        for doc in documents:
            if doc.doc_id in self._seen_doc_ids:
                logger.debug("Skipping duplicate doc_id=%s", doc.doc_id)
                continue
            self._seen_doc_ids.add(doc.doc_id)

            parent_meta = {
                "title": doc.title,
                "author": doc.author,
                "source": doc.source,
                "doc_type": doc.doc_type,
            }
            if doc.url:
                parent_meta["url"] = doc.url
            if doc.thread_id:
                parent_meta["thread_id"] = doc.thread_id
            if doc.metadata:
                parent_meta.update(doc.metadata)

            chunks = self._chunker.chunk(
                doc.content,
                doc_type=doc.doc_type,
                metadata=parent_meta,
            )

            for chunk in chunks:
                self._store.store(
                    content=chunk.content,
                    source=doc.source,
                    doc_type=doc.doc_type,
                    doc_id=doc.doc_id,
                    title=doc.title,
                    author=doc.author,
                    participants=doc.participants,
                    timestamp=doc.timestamp.isoformat()
                    if hasattr(doc.timestamp, "isoformat")
                    else str(doc.timestamp),
                    thread_id=doc.thread_id or "",
                    url=doc.url or "",
                    metadata=chunk.metadata,
                    chunk_index=chunk.index,
                )
                total_chunks += 1

        return total_chunks
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_pipeline.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/pipeline.py tests/connectors/test_pipeline.py
git commit -m "feat: add ingestion pipeline with dedup, type-aware chunking, and indexed storage"
```

---

### Task 5: SyncEngine (Checkpoint/Resume + Orchestration)

**Files:**
- Create: `src/openjarvis/connectors/sync_engine.py`
- Create: `tests/connectors/test_sync_engine.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_sync_engine.py`:

```python
"""Tests for SyncEngine — orchestrates connectors with checkpoint/resume."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional
from unittest.mock import MagicMock

import pytest

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.connectors.sync_engine import SyncEngine


class StubConnector(BaseConnector):
    connector_id = "stub"
    display_name = "Stub"
    auth_type = "filesystem"

    def __init__(self, docs: list[Document] | None = None) -> None:
        self._docs = docs or []
        self._connected = True
        self._synced = 0

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        start = int(cursor) if cursor else 0
        for i, doc in enumerate(self._docs[start:], start=start):
            self._synced = i + 1
            yield doc

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._synced,
            items_total=len(self._docs),
        )


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(db_path=str(tmp_path / "sync_test.db"))


@pytest.fixture
def engine(store: KnowledgeStore, tmp_path: Path) -> SyncEngine:
    pipeline = IngestionPipeline(store=store)
    return SyncEngine(pipeline=pipeline, state_db=str(tmp_path / "sync_state.db"))


def _make_docs(n: int, source: str = "stub") -> list[Document]:
    return [
        Document(
            doc_id=f"{source}:{i}",
            source=source,
            doc_type="message",
            content=f"Message number {i}",
        )
        for i in range(n)
    ]


def test_sync_connector(engine: SyncEngine, store: KnowledgeStore) -> None:
    conn = StubConnector(docs=_make_docs(5))
    engine.sync(conn)
    results = store.retrieve("Message", top_k=10)
    assert len(results) == 5


def test_sync_saves_checkpoint(engine: SyncEngine) -> None:
    conn = StubConnector(docs=_make_docs(3))
    engine.sync(conn)
    cp = engine.get_checkpoint("stub")
    assert cp is not None
    assert cp["items_synced"] == 3


def test_sync_status_for_unsynced(engine: SyncEngine) -> None:
    status = engine.get_checkpoint("nonexistent")
    assert status is None


def test_sync_multiple_connectors(engine: SyncEngine, store: KnowledgeStore) -> None:
    conn_a = StubConnector(docs=_make_docs(3, source="a"))
    conn_a.connector_id = "a"
    conn_b = StubConnector(docs=_make_docs(2, source="b"))
    conn_b.connector_id = "b"
    engine.sync(conn_a)
    engine.sync(conn_b)
    a_results = store.retrieve("Message", top_k=10, source="a")
    b_results = store.retrieve("Message", top_k=10, source="b")
    assert len(a_results) == 3
    assert len(b_results) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_sync_engine.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement SyncEngine**

Create `src/openjarvis/connectors/sync_engine.py`:

```python
"""SyncEngine — orchestrates connector sync with checkpoint/resume."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from openjarvis.connectors._stubs import BaseConnector
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

_STATE_SCHEMA = """\
CREATE TABLE IF NOT EXISTS sync_state (
    connector_id  TEXT PRIMARY KEY,
    items_synced  INTEGER NOT NULL DEFAULT 0,
    cursor        TEXT,
    last_sync     TEXT,
    error         TEXT
);
"""


class SyncEngine:
    """Orchestrates data source sync with checkpointing.

    Tracks per-connector progress in a small SQLite state database,
    separate from the knowledge store.  Supports resume after interruption.
    """

    def __init__(
        self,
        pipeline: IngestionPipeline,
        *,
        state_db: str = "",
    ) -> None:
        self._pipeline = pipeline
        if not state_db:
            state_db = str(DEFAULT_CONFIG_DIR / "sync_state.db")
        Path(state_db).parent.mkdir(parents=True, exist_ok=True)
        self._state_conn = sqlite3.connect(state_db)
        self._state_conn.executescript(_STATE_SCHEMA)

    def sync(self, connector: BaseConnector) -> int:
        """Run sync for a single connector.  Returns items ingested."""
        cid = connector.connector_id
        checkpoint = self.get_checkpoint(cid)
        cursor = checkpoint["cursor"] if checkpoint else None

        logger.info("Starting sync for %s (cursor=%s)", cid, cursor)
        items = 0
        try:
            docs = connector.sync(cursor=cursor)
            batch: list = []
            for doc in docs:
                batch.append(doc)
                items += 1
                # Flush in batches of 100
                if len(batch) >= 100:
                    self._pipeline.ingest(batch)
                    self._save_checkpoint(cid, items, cursor=str(items))
                    batch = []
            # Flush remaining
            if batch:
                self._pipeline.ingest(batch)

            self._save_checkpoint(cid, items, cursor=str(items))
            logger.info("Sync complete for %s: %d items", cid, items)
        except Exception as exc:
            logger.error("Sync error for %s: %s", cid, exc)
            self._save_checkpoint(cid, items, cursor=str(items), error=str(exc))
            raise

        return items

    def get_checkpoint(self, connector_id: str) -> Optional[Dict[str, Any]]:
        """Get the last checkpoint for a connector, or None if never synced."""
        row = self._state_conn.execute(
            "SELECT items_synced, cursor, last_sync, error FROM sync_state WHERE connector_id = ?",
            (connector_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "items_synced": row[0],
            "cursor": row[1],
            "last_sync": row[2],
            "error": row[3],
        }

    def _save_checkpoint(
        self,
        connector_id: str,
        items_synced: int,
        *,
        cursor: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        now = datetime.now().isoformat()
        self._state_conn.execute(
            """INSERT INTO sync_state (connector_id, items_synced, cursor, last_sync, error)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(connector_id)
               DO UPDATE SET items_synced=?, cursor=?, last_sync=?, error=?""",
            (
                connector_id,
                items_synced,
                cursor,
                now,
                error,
                items_synced,
                cursor,
                now,
                error,
            ),
        )
        self._state_conn.commit()

    def close(self) -> None:
        self._state_conn.close()
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_sync_engine.py -v`

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/sync_engine.py tests/connectors/test_sync_engine.py
git commit -m "feat: add SyncEngine with checkpoint/resume for connector orchestration"
```

---

### Task 6: Obsidian/Markdown Connector

**Files:**
- Create: `src/openjarvis/connectors/obsidian.py`
- Create: `tests/connectors/test_obsidian.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_obsidian.py`:

```python
"""Tests for the Obsidian/Markdown connector."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pytest

from openjarvis.connectors.obsidian import ObsidianConnector
from openjarvis.core.registry import ConnectorRegistry


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "my-vault"
    vault_dir.mkdir()
    (vault_dir / "note1.md").write_text(
        "---\ntitle: Meeting Notes\ntags: [work, meetings]\n---\n\n# Meeting Notes\n\nDiscussed Q3 roadmap."
    )
    (vault_dir / "note2.md").write_text("# Ideas\n\nBrainstorm for new feature.")
    (vault_dir / "subdir").mkdir()
    (vault_dir / "subdir" / "deep.md").write_text("# Deep Note\n\nNested vault content.")
    (vault_dir / ".obsidian").mkdir()  # Should be skipped
    (vault_dir / ".obsidian" / "config.json").write_text("{}")
    (vault_dir / "image.png").write_bytes(b"\x89PNG")  # Should be skipped
    return vault_dir


@pytest.fixture
def connector(vault: Path) -> ObsidianConnector:
    return ObsidianConnector(vault_path=str(vault))


def test_is_connected(connector: ObsidianConnector) -> None:
    assert connector.is_connected()


def test_not_connected_bad_path() -> None:
    conn = ObsidianConnector(vault_path="/nonexistent/path")
    assert not conn.is_connected()


def test_sync_yields_markdown_files(connector: ObsidianConnector) -> None:
    docs = list(connector.sync())
    assert len(docs) == 3  # note1, note2, deep
    sources = {d.doc_id for d in docs}
    assert any("note1" in s for s in sources)
    assert any("deep" in s for s in sources)


def test_sync_skips_hidden_dirs(connector: ObsidianConnector) -> None:
    docs = list(connector.sync())
    paths = [d.doc_id for d in docs]
    assert not any(".obsidian" in p for p in paths)


def test_sync_skips_binary_files(connector: ObsidianConnector) -> None:
    docs = list(connector.sync())
    types = [d.title for d in docs]
    assert not any("image" in t for t in types)


def test_sync_parses_frontmatter(connector: ObsidianConnector) -> None:
    docs = list(connector.sync())
    note1 = next(d for d in docs if "note1" in d.doc_id)
    assert note1.title == "Meeting Notes"
    assert note1.metadata.get("tags") == ["work", "meetings"]


def test_sync_sets_doc_type_note(connector: ObsidianConnector) -> None:
    docs = list(connector.sync())
    assert all(d.doc_type == "note" for d in docs)
    assert all(d.source == "obsidian" for d in docs)


def test_disconnect(connector: ObsidianConnector) -> None:
    connector.disconnect()
    assert not connector.is_connected()


def test_registry() -> None:
    import openjarvis.connectors.obsidian  # noqa: F401
    assert ConnectorRegistry.contains("obsidian")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_obsidian.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ObsidianConnector**

Create `src/openjarvis/connectors/obsidian.py`:

```python
"""Obsidian/Markdown vault connector — reads .md files from a local directory."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SKIP_DIRS = {".obsidian", ".trash", ".git", "__pycache__", "node_modules", ".venv"}
_MD_EXTENSIONS = {".md", ".markdown", ".txt"}


def _parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    """Extract YAML frontmatter and return (metadata, body)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end() :]
    meta: Dict[str, Any] = {}
    for line in raw.strip().split("\n"):
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # Simple YAML list: [a, b, c]
        if val.startswith("[") and val.endswith("]"):
            meta[key] = [v.strip() for v in val[1:-1].split(",")]
        else:
            meta[key] = val
    return meta, body


@ConnectorRegistry.register("obsidian")
class ObsidianConnector(BaseConnector):
    """Connector for Obsidian vaults and plain markdown directories."""

    connector_id = "obsidian"
    display_name = "Obsidian / Markdown"
    auth_type = "filesystem"

    def __init__(self, vault_path: str = "") -> None:
        self._vault_path = vault_path
        self._connected = bool(vault_path) and Path(vault_path).is_dir()
        self._synced = 0
        self._total = 0

    def is_connected(self) -> bool:
        return self._connected and Path(self._vault_path).is_dir()

    def disconnect(self) -> None:
        self._connected = False
        self._vault_path = ""

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        if not self.is_connected():
            return
        vault = Path(self._vault_path)
        md_files = sorted(self._walk_md_files(vault))
        self._total = len(md_files)
        self._synced = 0

        for filepath in md_files:
            try:
                text = filepath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            meta, body = _parse_frontmatter(text)
            title = meta.pop("title", filepath.stem)
            rel_path = str(filepath.relative_to(vault))
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime)

            if since and mtime < since:
                self._synced += 1
                continue

            self._synced += 1
            yield Document(
                doc_id=f"obsidian:{rel_path}",
                source="obsidian",
                doc_type="note",
                content=body.strip(),
                title=title,
                author="",
                timestamp=mtime,
                url=f"obsidian://open?vault={vault.name}&file={rel_path}",
                metadata=meta,
            )

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._synced,
            items_total=self._total,
        )

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="obsidian_search_notes",
                description="Search Obsidian vault notes by keyword.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
                category="connector",
            ),
        ]

    def _walk_md_files(self, root: Path) -> List[Path]:
        """Walk the vault, skipping hidden/config dirs and non-markdown files."""
        results: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune hidden/config directories
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for fname in filenames:
                if Path(fname).suffix.lower() in _MD_EXTENSIONS:
                    results.append(Path(dirpath) / fname)
        return results
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_obsidian.py -v`

Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/obsidian.py tests/connectors/test_obsidian.py
git commit -m "feat: add Obsidian/Markdown vault connector with frontmatter parsing"
```

---

### Task 7: Gmail Connector (Mocked OAuth + API)

**Files:**
- Create: `src/openjarvis/connectors/oauth.py`
- Create: `src/openjarvis/connectors/gmail.py`
- Create: `tests/connectors/test_gmail.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_gmail.py`:

```python
"""Tests for the Gmail connector (mocked API calls)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.connectors.gmail import GmailConnector
from openjarvis.core.registry import ConnectorRegistry


@pytest.fixture
def connector(tmp_path) -> GmailConnector:
    return GmailConnector(
        credentials_path=str(tmp_path / "gmail_creds.json"),
    )


def test_not_connected_without_credentials(connector: GmailConnector) -> None:
    assert not connector.is_connected()


def test_auth_type_is_oauth(connector: GmailConnector) -> None:
    assert connector.auth_type == "oauth"


def test_auth_url_returns_string(connector: GmailConnector) -> None:
    url = connector.auth_url()
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "gmail.readonly" in url


@patch("openjarvis.connectors.gmail._gmail_api_list_messages")
@patch("openjarvis.connectors.gmail._gmail_api_get_message")
def test_sync_yields_documents(mock_get, mock_list, connector, tmp_path) -> None:
    # Simulate having valid credentials
    creds_path = tmp_path / "gmail_creds.json"
    creds_path.write_text('{"token": "fake", "refresh_token": "fake"}')
    connector._credentials_path = str(creds_path)

    mock_list.return_value = {
        "messages": [{"id": "msg1"}, {"id": "msg2"}],
        "nextPageToken": None,
    }
    mock_get.side_effect = [
        {
            "id": "msg1",
            "threadId": "t1",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Subject", "value": "Q3 Planning"},
                    {"name": "Date", "value": "Mon, 15 Mar 2024 10:00:00 +0000"},
                    {"name": "To", "value": "bob@example.com"},
                ],
                "body": {"data": "SGVsbG8gd29ybGQ="},  # "Hello world" base64
            },
        },
        {
            "id": "msg2",
            "threadId": "t2",
            "labelIds": ["SENT"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "bob@example.com"},
                    {"name": "Subject", "value": "Re: Budget"},
                    {"name": "Date", "value": "Tue, 16 Mar 2024 11:00:00 +0000"},
                    {"name": "To", "value": "alice@example.com"},
                ],
                "body": {"data": "QnVkZ2V0IHJlcGx5"},  # "Budget reply" base64
            },
        },
    ]

    docs = list(connector.sync())
    assert len(docs) == 2
    assert docs[0].doc_id == "gmail:msg1"
    assert docs[0].source == "gmail"
    assert docs[0].doc_type == "email"
    assert docs[0].author == "alice@example.com"
    assert docs[0].title == "Q3 Planning"
    assert docs[0].thread_id == "t1"
    assert "Hello world" in docs[0].content


def test_disconnect(connector: GmailConnector, tmp_path) -> None:
    creds_path = tmp_path / "gmail_creds.json"
    creds_path.write_text('{"token": "fake"}')
    connector._credentials_path = str(creds_path)
    connector.disconnect()
    assert not connector.is_connected()


def test_mcp_tools(connector: GmailConnector) -> None:
    tools = connector.mcp_tools()
    names = [t.name for t in tools]
    assert "gmail_search_emails" in names
    assert "gmail_get_thread" in names


def test_registry() -> None:
    import openjarvis.connectors.gmail  # noqa: F401
    assert ConnectorRegistry.contains("gmail")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_gmail.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create OAuth helper**

Create `src/openjarvis/connectors/oauth.py`:

```python
"""Shared OAuth helper for connector authentication.

Handles the OAuth2 authorization code flow:
1. Generate consent URL with scopes
2. Start a temporary localhost server to receive the callback
3. Exchange the authorization code for tokens
4. Save tokens to credentials file
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


def build_google_auth_url(
    client_id: str,
    redirect_uri: str = "http://localhost:8789/callback",
    scopes: Optional[list[str]] = None,
) -> str:
    """Build a Google OAuth2 consent URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes or []),
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def load_tokens(path: str) -> Optional[Dict[str, Any]]:
    """Load OAuth tokens from a JSON file."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        if data.get("token") or data.get("access_token"):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_tokens(path: str, tokens: Dict[str, Any]) -> None:
    """Save OAuth tokens to a JSON file with restrictive permissions."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(tokens, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def delete_tokens(path: str) -> None:
    """Delete a credentials file."""
    p = Path(path)
    if p.exists():
        p.unlink()
```

- [ ] **Step 4: Implement GmailConnector**

Create `src/openjarvis/connectors/gmail.py`:

```python
"""Gmail connector — OAuth + Gmail API for bulk email sync."""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import (
    build_google_auth_url,
    delete_tokens,
    load_tokens,
    save_tokens,
)
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
# Placeholder — in production, use OpenJarvis's registered OAuth app
_CLIENT_ID = "openjarvis-gmail.apps.googleusercontent.com"
_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _gmail_api_list_messages(
    token: str, *, page_token: Optional[str] = None, query: str = ""
) -> Dict[str, Any]:
    """Call Gmail messages.list API."""
    params: dict[str, Any] = {"maxResults": 100}
    if page_token:
        params["pageToken"] = page_token
    if query:
        params["q"] = query
    resp = httpx.get(
        f"{_GMAIL_API}/messages",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _gmail_api_get_message(token: str, msg_id: str) -> Dict[str, Any]:
    """Call Gmail messages.get API."""
    resp = httpx.get(
        f"{_GMAIL_API}/messages/{msg_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"format": "full"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _extract_header(headers: List[Dict[str, str]], name: str) -> str:
    """Extract a header value from Gmail API payload headers."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_body(payload: Dict[str, Any]) -> str:
    """Decode the email body from Gmail API payload."""
    # Try top-level body
    body_data = payload.get("body", {}).get("data", "")
    if body_data:
        return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
    # Try multipart parts
    for part in payload.get("parts", []):
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    # Fallback: try first part with data
    for part in payload.get("parts", []):
        data = part.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    return ""


def _parse_date(date_str: str) -> datetime:
    """Parse an email Date header."""
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now()


@ConnectorRegistry.register("gmail")
class GmailConnector(BaseConnector):
    """Gmail connector — syncs email via the Gmail API."""

    connector_id = "gmail"
    display_name = "Gmail"
    auth_type = "oauth"

    def __init__(self, credentials_path: str = "") -> None:
        if not credentials_path:
            credentials_path = str(DEFAULT_CONFIG_DIR / "connectors" / "gmail.json")
        self._credentials_path = credentials_path
        self._synced = 0
        self._total = 0

    def is_connected(self) -> bool:
        tokens = load_tokens(self._credentials_path)
        return tokens is not None

    def disconnect(self) -> None:
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        return build_google_auth_url(client_id=_CLIENT_ID, scopes=_SCOPES)

    def handle_callback(self, code: str) -> None:
        # In production: exchange code for tokens via Google's token endpoint
        save_tokens(self._credentials_path, {"token": code, "refresh_token": code})

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        tokens = load_tokens(self._credentials_path)
        if not tokens:
            return
        token = tokens.get("token", "")

        page_token = cursor
        while True:
            data = _gmail_api_list_messages(token, page_token=page_token)
            messages = data.get("messages", [])
            self._total += len(messages)

            for msg_ref in messages:
                msg = _gmail_api_get_message(token, msg_ref["id"])
                payload = msg.get("payload", {})
                headers = payload.get("headers", [])

                from_addr = _extract_header(headers, "From")
                subject = _extract_header(headers, "Subject")
                date_str = _extract_header(headers, "Date")
                to_addr = _extract_header(headers, "To")
                body = _decode_body(payload)
                timestamp = _parse_date(date_str)

                if since and timestamp < since:
                    continue

                self._synced += 1
                yield Document(
                    doc_id=f"gmail:{msg['id']}",
                    source="gmail",
                    doc_type="email",
                    content=body,
                    title=subject,
                    author=from_addr,
                    participants=[a.strip() for a in to_addr.split(",") if a.strip()],
                    timestamp=timestamp,
                    thread_id=msg.get("threadId", ""),
                    url=f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}",
                    metadata={
                        "labels": msg.get("labelIds", []),
                    },
                )

            page_token = data.get("nextPageToken")
            if not page_token:
                break

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._synced,
            items_total=self._total,
        )

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="gmail_search_emails",
                description="Search Gmail messages by query string.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Gmail search query (e.g., 'from:alice subject:budget')"},
                        "max_results": {"type": "integer", "description": "Max results to return", "default": 10},
                    },
                    "required": ["query"],
                },
                category="connector",
            ),
            ToolSpec(
                name="gmail_get_thread",
                description="Get all messages in a Gmail thread by thread ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string", "description": "Gmail thread ID"},
                    },
                    "required": ["thread_id"],
                },
                category="connector",
            ),
            ToolSpec(
                name="gmail_list_unread",
                description="List recent unread emails.",
                parameters={
                    "type": "object",
                    "properties": {
                        "max_results": {"type": "integer", "description": "Max results", "default": 10},
                    },
                },
                category="connector",
            ),
        ]
```

- [ ] **Step 5: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_gmail.py -v`

Expected: All 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/connectors/oauth.py src/openjarvis/connectors/gmail.py tests/connectors/test_gmail.py
git commit -m "feat: add Gmail connector with OAuth and mocked API sync"
```

---

### Task 8: knowledge_search Tool

**Files:**
- Create: `src/openjarvis/tools/knowledge_search.py`
- Create: `tests/tools/test_knowledge_search.py`

- [ ] **Step 1: Write failing tests**

Create `tests/tools/test_knowledge_search.py`:

```python
"""Tests for the knowledge_search tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.knowledge_search import KnowledgeSearchTool


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    s = KnowledgeStore(db_path=str(tmp_path / "ks_test.db"))
    s.store(content="Kubernetes migration proposal", source="gdrive", doc_type="document", author="sarah")
    s.store(content="Budget discussion for Q3", source="gmail", doc_type="email", author="mike")
    s.store(content="Sprint standup notes", source="slack", doc_type="message", author="alice")
    return s


@pytest.fixture
def tool(store: KnowledgeStore) -> KnowledgeSearchTool:
    return KnowledgeSearchTool(store=store)


def test_basic_search(tool: KnowledgeSearchTool) -> None:
    result = tool.execute(query="Kubernetes migration")
    assert result.success
    assert "Kubernetes" in result.content


def test_filter_by_source(tool: KnowledgeSearchTool) -> None:
    result = tool.execute(query="discussion", source="gmail")
    assert result.success
    assert "Budget" in result.content


def test_filter_by_author(tool: KnowledgeSearchTool) -> None:
    result = tool.execute(query="proposal", author="sarah")
    assert result.success
    assert "Kubernetes" in result.content


def test_no_results(tool: KnowledgeSearchTool) -> None:
    result = tool.execute(query="xyznonexistent")
    assert result.success
    assert "No relevant results" in result.content


def test_empty_query(tool: KnowledgeSearchTool) -> None:
    result = tool.execute(query="")
    assert not result.success


def test_no_store() -> None:
    tool = KnowledgeSearchTool(store=None)
    result = tool.execute(query="anything")
    assert not result.success


def test_spec_has_filter_params(tool: KnowledgeSearchTool) -> None:
    spec = tool.spec
    props = spec.parameters.get("properties", {})
    assert "query" in props
    assert "source" in props
    assert "doc_type" in props
    assert "author" in props
    assert "since" in props
    assert "top_k" in props


def test_registry() -> None:
    import openjarvis.tools.knowledge_search  # noqa: F401
    assert ToolRegistry.contains("knowledge_search")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/tools/test_knowledge_search.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement KnowledgeSearchTool**

Create `src/openjarvis/tools/knowledge_search.py`:

```python
"""knowledge_search — filtered BM25 retrieval over the personal knowledge base."""

from __future__ import annotations

from typing import Any, Optional

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("knowledge_search")
class KnowledgeSearchTool(BaseTool):
    """Search the personal knowledge base with optional filters.

    Supports filtering by source (gmail, slack, gdrive, etc.),
    doc_type (email, message, document, etc.), author, and time range.
    """

    tool_id = "knowledge_search"

    def __init__(self, store: Optional[KnowledgeStore] = None) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="knowledge_search",
            description=(
                "Search your personal knowledge base (emails, messages, documents, "
                "calendar events, contacts, notes) with optional filters. Returns "
                "relevant results with source attribution and deep links."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant information.",
                    },
                    "source": {
                        "type": "string",
                        "description": 'Filter by source: "gmail", "slack", "gdrive", "obsidian", etc.',
                    },
                    "doc_type": {
                        "type": "string",
                        "description": 'Filter by type: "email", "message", "document", "event", "contact", "note".',
                    },
                    "author": {
                        "type": "string",
                        "description": "Filter by author/sender name or email.",
                    },
                    "since": {
                        "type": "string",
                        "description": "Only return results after this ISO 8601 timestamp.",
                    },
                    "until": {
                        "type": "string",
                        "description": "Only return results before this ISO 8601 timestamp.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default: 10).",
                    },
                },
                "required": ["query"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._store is None:
            return ToolResult(
                tool_name="knowledge_search",
                content="No knowledge store configured. Run 'jarvis connect' to set up data sources.",
                success=False,
            )

        query = params.get("query", "")
        if not query:
            return ToolResult(
                tool_name="knowledge_search",
                content="No query provided.",
                success=False,
            )

        top_k = params.get("top_k", 10)
        try:
            results = self._store.retrieve(
                query,
                top_k=top_k,
                source=params.get("source", ""),
                doc_type=params.get("doc_type", ""),
                author=params.get("author", ""),
                since=params.get("since", ""),
                until=params.get("until", ""),
            )
        except Exception as exc:
            return ToolResult(
                tool_name="knowledge_search",
                content=f"Search error: {exc}",
                success=False,
            )

        if not results:
            return ToolResult(
                tool_name="knowledge_search",
                content="No relevant results found.",
                success=True,
                metadata={"num_results": 0},
            )

        # Format results with source attribution
        lines = []
        for i, r in enumerate(results, 1):
            meta = r.metadata
            source_tag = meta.get("source", "unknown")
            author = meta.get("author", "")
            title = meta.get("title", "")
            url = meta.get("url", "")
            header_parts = [f"[{source_tag}]"]
            if title:
                header_parts.append(title)
            if author:
                header_parts.append(f"by {author}")
            if url:
                header_parts.append(f"({url})")
            header = " ".join(header_parts)
            lines.append(f"**Result {i}:** {header}\n{r.content}\n")

        return ToolResult(
            tool_name="knowledge_search",
            content="\n".join(lines),
            success=True,
            metadata={"num_results": len(results)},
        )
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/tools/test_knowledge_search.py -v`

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/tools/knowledge_search.py tests/tools/test_knowledge_search.py
git commit -m "feat: add knowledge_search tool with filtered BM25 retrieval and source attribution"
```

---

### Task 9: CLI `jarvis connect` Command

**Files:**
- Create: `src/openjarvis/cli/connect_cmd.py`
- Modify: `src/openjarvis/cli/__init__.py`
- Create: `tests/cli/test_connect.py`

- [ ] **Step 1: Write failing tests**

Create `tests/cli/test_connect.py`:

```python
"""Tests for the jarvis connect CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from openjarvis.cli.connect_cmd import connect


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_connect_list_no_connectors(runner: CliRunner) -> None:
    result = runner.invoke(connect, ["--list"])
    assert result.exit_code == 0
    assert "No connectors" in result.output or "connected" in result.output.lower()


def test_connect_list_with_connector(runner: CliRunner, tmp_path: Path) -> None:
    # Create a fake credential file so Gmail appears connected
    creds = tmp_path / "gmail.json"
    creds.write_text('{"token": "fake"}')
    with patch("openjarvis.connectors.gmail.DEFAULT_CONFIG_DIR", tmp_path / "config"):
        result = runner.invoke(connect, ["--list"])
    assert result.exit_code == 0


def test_connect_help(runner: CliRunner) -> None:
    result = runner.invoke(connect, ["--help"])
    assert result.exit_code == 0
    assert "connect" in result.output.lower()


def test_connect_specific_source(runner: CliRunner) -> None:
    result = runner.invoke(connect, ["obsidian", "--path", "/nonexistent"])
    # Should fail gracefully — path doesn't exist
    assert result.exit_code == 0 or "not found" in result.output.lower() or "does not exist" in result.output.lower()


def test_connect_disconnect(runner: CliRunner) -> None:
    result = runner.invoke(connect, ["--disconnect", "gmail"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/cli/test_connect.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement connect command**

Create `src/openjarvis/cli/connect_cmd.py`:

```python
"""CLI command: jarvis connect — manage data source connections."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group(invoke_without_command=True)
@click.argument("source", required=False)
@click.option("--list", "list_sources", is_flag=True, help="List connected sources and sync status.")
@click.option("--sync", "trigger_sync", is_flag=True, help="Trigger incremental sync for all sources.")
@click.option("--disconnect", "disconnect_source", default="", help="Disconnect a source.")
@click.option("--path", default="", help="Path for filesystem connectors (e.g., Obsidian vault).")
@click.pass_context
def connect(
    ctx: click.Context,
    source: str | None,
    list_sources: bool,
    trigger_sync: bool,
    disconnect_source: str,
    path: str,
) -> None:
    """Connect data sources for Deep Research.

    \b
    Examples:
      jarvis connect                    # Interactive source picker
      jarvis connect gmail              # Connect Gmail
      jarvis connect obsidian --path ~/vault
      jarvis connect --list             # Show connected sources
      jarvis connect --disconnect gmail # Disconnect Gmail
    """
    # Import connectors to trigger registration
    import openjarvis.connectors.gmail  # noqa: F401
    import openjarvis.connectors.obsidian  # noqa: F401
    from openjarvis.core.registry import ConnectorRegistry

    if list_sources:
        _list_sources(ConnectorRegistry)
        return

    if disconnect_source:
        _disconnect_source(ConnectorRegistry, disconnect_source)
        return

    if trigger_sync:
        console.print("[yellow]Sync not yet implemented in CLI — use the desktop app.[/yellow]")
        return

    if source:
        _connect_source(ConnectorRegistry, source, path=path)
        return

    # No args — show help
    if not ctx.invoked_subcommand:
        console.print(ctx.get_help())


def _list_sources(registry: type) -> None:
    """List all available connectors and their status."""
    table = Table(title="Data Sources")
    table.add_column("Source", style="cyan")
    table.add_column("Type", style="dim")
    table.add_column("Status", style="green")

    for key in sorted(registry.keys()):
        cls = registry.get(key)
        try:
            instance = cls()
            connected = instance.is_connected()
            status = "[green]Connected[/green]" if connected else "[dim]Not connected[/dim]"
        except Exception:
            status = "[dim]Not configured[/dim]"
        auth = getattr(cls, "auth_type", "unknown")
        table.add_row(key, auth, status)

    if not registry.keys():
        console.print("[dim]No connectors registered.[/dim]")
        return

    console.print(table)


def _disconnect_source(registry: type, source: str) -> None:
    """Disconnect a specific source."""
    if not registry.contains(source):
        console.print(f"[red]Unknown source: {source}[/red]")
        return
    cls = registry.get(source)
    try:
        instance = cls()
        instance.disconnect()
        console.print(f"[green]Disconnected {source}.[/green]")
    except Exception as exc:
        console.print(f"[red]Error disconnecting {source}: {exc}[/red]")


def _connect_source(registry: type, source: str, *, path: str = "") -> None:
    """Connect a specific source."""
    if not registry.contains(source):
        console.print(f"[red]Unknown source: {source}[/red]")
        console.print(f"Available: {', '.join(sorted(registry.keys()))}")
        return

    cls = registry.get(source)
    auth_type = getattr(cls, "auth_type", "unknown")

    if auth_type == "filesystem":
        if not path:
            console.print(f"[red]{source} requires --path argument.[/red]")
            return
        from pathlib import Path as P

        if not P(path).is_dir():
            console.print(f"[red]Path does not exist: {path}[/red]")
            return
        instance = cls(vault_path=path)
        if instance.is_connected():
            console.print(f"[green]Connected to {source} at {path}[/green]")
        else:
            console.print(f"[red]Could not connect to {source} at {path}[/red]")

    elif auth_type == "oauth":
        instance = cls()
        if instance.is_connected():
            console.print(f"[green]{source} is already connected.[/green]")
            return
        url = instance.auth_url()
        console.print(f"Open this URL in your browser to authorize {source}:")
        console.print(f"[link={url}]{url}[/link]")
        console.print("[dim]After authorizing, paste the code here.[/dim]")

    else:
        console.print(f"[yellow]Auth type '{auth_type}' not yet supported in CLI.[/yellow]")
```

- [ ] **Step 4: Register connect command in CLI __init__.py**

Open `src/openjarvis/cli/__init__.py`. Find where other commands are added (look for `cli.add_command` calls). Add:

```python
from openjarvis.cli.connect_cmd import connect

cli.add_command(connect, "connect")
```

Place this alongside the existing `cli.add_command` calls.

- [ ] **Step 5: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/cli/test_connect.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/cli/connect_cmd.py src/openjarvis/cli/__init__.py tests/cli/test_connect.py
git commit -m "feat: add 'jarvis connect' CLI command for managing data source connections"
```

---

### Task 10: Integration Test + Wire Up Connectors __init__.py

**Files:**
- Modify: `src/openjarvis/connectors/__init__.py`
- Create: `tests/connectors/test_integration.py`

- [ ] **Step 1: Update connectors __init__.py to auto-register**

Open `src/openjarvis/connectors/__init__.py` and replace with:

```python
"""Data source connectors for Deep Research."""

from openjarvis.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)

__all__ = ["Attachment", "BaseConnector", "Document", "SyncStatus"]

# Auto-register built-in connectors
import openjarvis.connectors.obsidian  # noqa: F401

try:
    import openjarvis.connectors.gmail  # noqa: F401
except ImportError:
    pass  # httpx may not be installed
```

- [ ] **Step 2: Write integration test**

Create `tests/connectors/test_integration.py`:

```python
"""Integration test — full pipeline from connector to retrieval."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.connectors.obsidian import ObsidianConnector
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.connectors.sync_engine import SyncEngine
from openjarvis.tools.knowledge_search import KnowledgeSearchTool


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "test-vault"
    vault_dir.mkdir()
    (vault_dir / "project-notes.md").write_text(
        "# Project Alpha\n\nWe decided to migrate to Kubernetes in March.\n\n"
        "## Cost Analysis\n\nEstimated 40% increase in cloud spend during transition.\n\n"
        "## Timeline\n\nSix-week migration window starting April 1st."
    )
    (vault_dir / "meeting.md").write_text(
        "# Sprint Review\n\nDiscussed budget concerns with Mike and Sarah.\n"
        "Action item: Sarah to prepare cost comparison document."
    )
    return vault_dir


def test_full_pipeline_obsidian_to_search(vault: Path, tmp_path: Path) -> None:
    """End-to-end: Obsidian vault → SyncEngine → KnowledgeStore → knowledge_search."""
    # 1. Setup
    store = KnowledgeStore(db_path=str(tmp_path / "integration.db"))
    pipeline = IngestionPipeline(store=store)
    engine = SyncEngine(pipeline=pipeline, state_db=str(tmp_path / "state.db"))
    connector = ObsidianConnector(vault_path=str(vault))

    # 2. Sync
    engine.sync(connector)

    # 3. Verify checkpoint
    cp = engine.get_checkpoint("obsidian")
    assert cp is not None
    assert cp["items_synced"] == 2

    # 4. Search via knowledge_search tool
    tool = KnowledgeSearchTool(store=store)

    # Search for Kubernetes content
    result = tool.execute(query="Kubernetes migration")
    assert result.success
    assert "Kubernetes" in result.content

    # Search for budget discussion
    result = tool.execute(query="budget concerns")
    assert result.success
    assert "budget" in result.content.lower()

    # Search with source filter
    result = tool.execute(query="migration", source="obsidian")
    assert result.success

    # No results for nonexistent source
    result = tool.execute(query="migration", source="gmail")
    assert "No relevant results" in result.content
```

- [ ] **Step 3: Run the full integration test**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_integration.py -v`

Expected: PASS — the full pipeline works end-to-end.

- [ ] **Step 4: Run ALL connector and tool tests together**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/ tests/tools/test_knowledge_search.py tests/cli/test_connect.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Run linter**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run ruff check src/openjarvis/connectors/ src/openjarvis/tools/knowledge_search.py src/openjarvis/cli/connect_cmd.py tests/connectors/ tests/tools/test_knowledge_search.py tests/cli/test_connect.py`

Expected: No errors. If there are import ordering or unused import warnings, fix them.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/connectors/__init__.py tests/connectors/test_integration.py
git commit -m "feat: add integration test and auto-registration for built-in connectors"
```

---

## Post-Plan Notes

**What this plan produces:** A working connector framework with two connectors (Gmail + Obsidian), a knowledge store with filtered BM25 retrieval, a `knowledge_search` tool for agents, a SyncEngine with checkpointing, and a `jarvis connect` CLI. This is the foundation that Phases 2-5 build on.

**What comes next (separate plans):**
- **Phase 2:** Desktop setup wizard UI + Slack, Google Drive, Calendar, Contacts, iMessage connectors
- **Phase 3:** ColBERTv2 disk persistence + DeepResearchAgent + research report UI
- **Phase 4:** ChannelAgent + iMessage/WhatsApp/Slack plugins
- **Phase 5:** Incremental sync, attachment store, settings page polish
