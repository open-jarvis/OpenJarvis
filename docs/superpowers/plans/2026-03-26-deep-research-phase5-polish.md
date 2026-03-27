# Deep Research Phase 5: Incremental Sync + Attachment Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add incremental delta sync (only fetch new/modified items after initial bulk), content-addressed attachment storage with SHA-256 dedup, a sync trigger API endpoint, and text extraction from PDF/Office attachments.

**Architecture:** The SyncEngine is extended to pass `since=last_sync_time` to connectors on subsequent syncs. A new `AttachmentStore` manages content-addressed blob storage at `~/.openjarvis/blobs/` with SHA-256 dedup and a metadata table. The IngestionPipeline is extended to extract text from attachments and index it alongside parent documents. A `POST /v1/connectors/{id}/sync` endpoint triggers syncs via the API.

**Tech Stack:** Python 3.10+, sqlite3, hashlib (SHA-256), pdfplumber (optional, PDF text extraction), pytest

**Spec:** `docs/superpowers/specs/2026-03-25-deep-research-setup-design.md` — Section 6 (Ingestion Pipeline), Phase 5

**Depends on:** Phase 1 (SyncEngine, IngestionPipeline, KnowledgeStore), Phase 2B-i (API router)

---

## File Structure

```
src/openjarvis/connectors/
├── attachment_store.py       # Content-addressed blob store with SHA-256 dedup
├── sync_engine.py            # (modify) Wire incremental sync via since param
├── pipeline.py               # (modify) Process attachments during ingest
├── gmail.py                  # (modify) Wire since param for incremental

src/openjarvis/server/
├── connectors_router.py      # (modify) Add POST /connectors/{id}/sync endpoint

tests/connectors/
├── test_attachment_store.py   # AttachmentStore tests
├── test_incremental_sync.py   # Incremental sync tests
```

---

### Task 1: Incremental Sync (Wire `since` Through SyncEngine)

**Files:**
- Modify: `src/openjarvis/connectors/sync_engine.py`
- Create: `tests/connectors/test_incremental_sync.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_incremental_sync.py`:

```python
"""Tests for incremental sync — only fetches items after last sync time."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import pytest

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.connectors.sync_engine import SyncEngine


class TimestampConnector(BaseConnector):
    """Connector that records what `since` value it receives."""

    connector_id = "ts_test"
    display_name = "Timestamp Test"
    auth_type = "filesystem"

    def __init__(self, docs: list[Document] | None = None) -> None:
        self._docs = docs or []
        self._received_since: Optional[datetime] = None

    def is_connected(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        self._received_since = since
        for doc in self._docs:
            if since and doc.timestamp < since:
                continue
            yield doc

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle")


def _make_doc(
    doc_id: str, ts: datetime, content: str = "test"
) -> Document:
    return Document(
        doc_id=doc_id,
        source="ts_test",
        doc_type="message",
        content=content,
        timestamp=ts,
    )


@pytest.fixture
def setup(tmp_path: Path):
    store = KnowledgeStore(
        db_path=str(tmp_path / "inc.db")
    )
    pipeline = IngestionPipeline(store=store)
    engine = SyncEngine(
        pipeline=pipeline,
        state_db=str(tmp_path / "state.db"),
    )
    return store, pipeline, engine


def test_first_sync_passes_no_since(setup) -> None:
    store, pipeline, engine = setup
    old = _make_doc(
        "ts:1",
        datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    conn = TimestampConnector(docs=[old])
    engine.sync(conn)
    assert conn._received_since is None


def test_second_sync_passes_since(setup) -> None:
    store, pipeline, engine = setup
    old = _make_doc(
        "ts:1",
        datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    conn1 = TimestampConnector(docs=[old])
    engine.sync(conn1)

    # Second sync should receive since= from last sync
    new = _make_doc(
        "ts:2",
        datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    conn2 = TimestampConnector(docs=[old, new])
    conn2.connector_id = "ts_test"
    engine.sync(conn2)
    assert conn2._received_since is not None


def test_incremental_only_adds_new_items(setup) -> None:
    store, pipeline, engine = setup
    old = _make_doc(
        "ts:1",
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        content="Old item",
    )
    conn1 = TimestampConnector(docs=[old])
    engine.sync(conn1)
    assert store.count() >= 1

    count_after_first = store.count()

    # Second sync with same + new doc
    new = _make_doc(
        "ts:2",
        datetime(2024, 6, 1, tzinfo=timezone.utc),
        content="New item",
    )
    conn2 = TimestampConnector(docs=[old, new])
    conn2.connector_id = "ts_test"
    engine.sync(conn2)

    # Should have more chunks now
    assert store.count() > count_after_first
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_incremental_sync.py -v`

Expected: `test_second_sync_passes_since` FAILS (since is never passed)

- [ ] **Step 3: Modify SyncEngine to pass `since`**

In `src/openjarvis/connectors/sync_engine.py`, modify the `sync()` method. After loading the checkpoint, parse `last_sync` into a datetime and pass it as `since=` to the connector:

Find the line that calls `connector.sync(cursor=prior_cursor)` and change it to also pass `since`:

```python
# Parse last_sync from checkpoint into datetime
since: Optional[datetime] = None
if checkpoint and checkpoint.get("last_sync"):
    try:
        since = datetime.fromisoformat(checkpoint["last_sync"])
    except (ValueError, TypeError):
        pass

docs = connector.sync(since=since, cursor=prior_cursor)
```

Add `from datetime import datetime` to imports if not already present.

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_incremental_sync.py -v`

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/sync_engine.py tests/connectors/test_incremental_sync.py
git commit -m "feat: wire incremental sync via since param in SyncEngine"
```

---

### Task 2: Attachment Store (Content-Addressed Blobs)

**Files:**
- Create: `src/openjarvis/connectors/attachment_store.py`
- Create: `tests/connectors/test_attachment_store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_attachment_store.py`:

```python
"""Tests for AttachmentStore — content-addressed blob storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.connectors.attachment_store import AttachmentStore


@pytest.fixture
def store(tmp_path: Path) -> AttachmentStore:
    return AttachmentStore(base_dir=str(tmp_path / "blobs"))


def test_store_returns_sha256(store: AttachmentStore) -> None:
    sha = store.store(
        content=b"Hello, world!",
        filename="hello.txt",
        mime_type="text/plain",
        source_doc_id="gmail:msg1",
    )
    assert len(sha) == 64  # SHA-256 hex digest


def test_store_creates_blob_file(
    store: AttachmentStore, tmp_path: Path
) -> None:
    sha = store.store(
        content=b"PDF content here",
        filename="report.pdf",
        mime_type="application/pdf",
        source_doc_id="gdrive:doc1",
    )
    blob_path = Path(store._base_dir) / sha[:2] / sha
    assert blob_path.exists()
    assert blob_path.read_bytes() == b"PDF content here"


def test_dedup_same_content(store: AttachmentStore) -> None:
    content = b"Identical file content"
    sha1 = store.store(
        content=content,
        filename="file1.txt",
        mime_type="text/plain",
        source_doc_id="gmail:1",
    )
    sha2 = store.store(
        content=content,
        filename="file2.txt",
        mime_type="text/plain",
        source_doc_id="slack:1",
    )
    assert sha1 == sha2  # Same content → same hash


def test_dedup_tracks_multiple_sources(
    store: AttachmentStore,
) -> None:
    content = b"Shared file"
    store.store(
        content=content,
        filename="shared.pdf",
        mime_type="application/pdf",
        source_doc_id="gmail:1",
    )
    store.store(
        content=content,
        filename="shared.pdf",
        mime_type="application/pdf",
        source_doc_id="slack:1",
    )
    meta = store.get_metadata(
        store.store(
            content=content,
            filename="shared.pdf",
            mime_type="application/pdf",
            source_doc_id="gdrive:1",
        )
    )
    assert len(meta["source_doc_ids"]) >= 3


def test_get_metadata(store: AttachmentStore) -> None:
    sha = store.store(
        content=b"test",
        filename="test.txt",
        mime_type="text/plain",
        source_doc_id="gmail:1",
    )
    meta = store.get_metadata(sha)
    assert meta["filename"] == "test.txt"
    assert meta["mime_type"] == "text/plain"
    assert meta["size_bytes"] == 4


def test_get_content(store: AttachmentStore) -> None:
    sha = store.store(
        content=b"retrieve me",
        filename="data.bin",
        mime_type="application/octet-stream",
        source_doc_id="test:1",
    )
    assert store.get_content(sha) == b"retrieve me"


def test_get_content_nonexistent(
    store: AttachmentStore,
) -> None:
    assert store.get_content("nonexistent") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_attachment_store.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement AttachmentStore**

Create `src/openjarvis/connectors/attachment_store.py`:

```python
"""Content-addressed attachment store with SHA-256 dedup.

Blobs stored at: {base_dir}/{sha256[:2]}/{sha256}
Metadata tracked in SQLite alongside the blobs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

_DEFAULT_BASE_DIR = str(DEFAULT_CONFIG_DIR / "blobs")

_META_SCHEMA = """\
CREATE TABLE IF NOT EXISTS attachments (
    sha256          TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    mime_type       TEXT NOT NULL DEFAULT '',
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    source_doc_ids  TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL
);
"""


class AttachmentStore:
    """Content-addressed blob store for email attachments, shared files, etc.

    Each file is stored once by SHA-256 hash. Multiple source documents
    can reference the same blob (dedup across Gmail, Slack, Drive, etc.).
    """

    def __init__(self, base_dir: str = "") -> None:
        self._base_dir = base_dir or _DEFAULT_BASE_DIR
        Path(self._base_dir).mkdir(parents=True, exist_ok=True)
        db_path = str(Path(self._base_dir) / "attachments.db")
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_META_SCHEMA)

    def store(
        self,
        content: bytes,
        *,
        filename: str,
        mime_type: str = "",
        source_doc_id: str = "",
    ) -> str:
        """Store a blob and return its SHA-256 hash.

        If the same content already exists, just adds the source_doc_id
        to the existing metadata (dedup).
        """
        sha = hashlib.sha256(content).hexdigest()

        # Write blob file (idempotent)
        blob_dir = Path(self._base_dir) / sha[:2]
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / sha
        if not blob_path.exists():
            blob_path.write_bytes(content)

        # Upsert metadata
        row = self._conn.execute(
            "SELECT source_doc_ids FROM attachments WHERE sha256 = ?",
            (sha,),
        ).fetchone()

        if row is None:
            from datetime import datetime, timezone

            self._conn.execute(
                """INSERT INTO attachments
                   (sha256, filename, mime_type, size_bytes,
                    source_doc_ids, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    sha,
                    filename,
                    mime_type,
                    len(content),
                    json.dumps([source_doc_id] if source_doc_id else []),
                    datetime.now(tz=timezone.utc).isoformat(),
                ),
            )
        else:
            # Add source_doc_id if not already tracked
            ids = json.loads(row["source_doc_ids"])
            if source_doc_id and source_doc_id not in ids:
                ids.append(source_doc_id)
                self._conn.execute(
                    "UPDATE attachments SET source_doc_ids = ? WHERE sha256 = ?",
                    (json.dumps(ids), sha),
                )

        self._conn.commit()
        return sha

    def get_metadata(self, sha: str) -> Optional[Dict[str, Any]]:
        """Get metadata for an attachment by SHA-256."""
        row = self._conn.execute(
            "SELECT * FROM attachments WHERE sha256 = ?", (sha,)
        ).fetchone()
        if row is None:
            return None
        return {
            "sha256": row["sha256"],
            "filename": row["filename"],
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
            "source_doc_ids": json.loads(row["source_doc_ids"]),
            "created_at": row["created_at"],
        }

    def get_content(self, sha: str) -> Optional[bytes]:
        """Read blob content by SHA-256. Returns None if not found."""
        blob_path = Path(self._base_dir) / sha[:2] / sha
        if not blob_path.exists():
            return None
        return blob_path.read_bytes()

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_attachment_store.py -v`

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/attachment_store.py tests/connectors/test_attachment_store.py
git commit -m "feat: add content-addressed AttachmentStore with SHA-256 dedup"
```

---

### Task 3: Sync Trigger API Endpoint

**Files:**
- Modify: `src/openjarvis/server/connectors_router.py`
- Modify: `tests/server/test_connectors_router.py`

- [ ] **Step 1: Add test for POST /sync**

Add to `tests/server/test_connectors_router.py`:

```python
def test_trigger_sync(app, tmp_path: Path) -> None:
    """POST /v1/connectors/obsidian/sync triggers a sync."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Test note\n\nContent here.")
    # First connect
    app.post(
        "/v1/connectors/obsidian/connect",
        json={"path": str(vault)},
    )
    # Then trigger sync
    resp = app.post("/v1/connectors/obsidian/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chunks_indexed"] >= 1
```

- [ ] **Step 2: Implement POST /sync endpoint**

Add to the router in `src/openjarvis/server/connectors_router.py`:

```python
@router.post("/connectors/{connector_id}/sync")
def trigger_sync(connector_id: str) -> Dict[str, Any]:
    """Trigger an incremental sync for a connector."""
    if not ConnectorRegistry.contains(connector_id):
        raise HTTPException(
            status_code=404,
            detail=f"Connector '{connector_id}' not found",
        )
    inst = _get_or_create(connector_id)
    if not inst.is_connected():
        raise HTTPException(
            status_code=400,
            detail=f"Connector '{connector_id}' is not connected",
        )

    from openjarvis.connectors.pipeline import IngestionPipeline
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.connectors.sync_engine import SyncEngine

    store = KnowledgeStore()
    pipeline = IngestionPipeline(store=store)
    engine = SyncEngine(pipeline=pipeline)
    chunks = engine.sync(inst)

    return {
        "connector_id": connector_id,
        "chunks_indexed": chunks,
        "status": "complete",
    }
```

- [ ] **Step 3: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run --extra server pytest tests/server/test_connectors_router.py -v`

Expected: All tests PASS (existing + new).

- [ ] **Step 4: Commit**

```bash
git add src/openjarvis/server/connectors_router.py tests/server/test_connectors_router.py
git commit -m "feat: add POST /v1/connectors/{id}/sync to trigger incremental sync"
```

---

## Post-Plan Notes

**What this plan produces:**
- Incremental sync via `since=last_sync_time` passed to connectors on subsequent syncs
- Content-addressed `AttachmentStore` with SHA-256 dedup and multi-source tracking
- `POST /v1/connectors/{id}/sync` API endpoint to trigger syncs
- Tests for all of the above

**What's NOT in this plan (future):**
- PDF text extraction from attachments (needs pdfplumber wired into pipeline)
- Office doc extraction (python-docx/openpyxl)
- Wiring attachment extraction into the IngestionPipeline
- Populating `doc.attachments` in Gmail/Drive connectors

These are natural follow-ups once the store exists. The current plan establishes the foundation (dedup blob store + incremental sync + sync trigger API).
