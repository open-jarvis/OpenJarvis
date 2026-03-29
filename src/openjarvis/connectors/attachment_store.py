"""AttachmentStore — content-addressed blob storage for Deep Research attachments.

Stores binary attachments at ``{base_dir}/{sha256[:2]}/{sha256}`` and tracks
metadata in a SQLite database at ``{base_dir}/attachments.db``.

Deduplication is automatic: re-storing the same bytes accumulates source_doc_ids
but does not write a second copy of the file.

Pure Python ``sqlite3`` (no Rust extension required).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS attachments (
    sha256          TEXT PRIMARY KEY,
    filename        TEXT NOT NULL DEFAULT '',
    mime_type       TEXT NOT NULL DEFAULT '',
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    source_doc_ids  TEXT NOT NULL DEFAULT '[]',
    created_at      REAL NOT NULL
);
"""

# ---------------------------------------------------------------------------
# AttachmentStore
# ---------------------------------------------------------------------------


class AttachmentStore:
    """Content-addressed blob store with SQLite metadata index.

    Files are written to ``{base_dir}/{sha256[:2]}/{sha256}`` so that the
    directory fan-out stays bounded even for millions of blobs.  The SQLite
    metadata table tracks filename, MIME type, size, and the list of
    source document IDs that reference each blob.
    """

    def __init__(self, base_dir: str = "") -> None:
        if not base_dir:
            from openjarvis.core.config import DEFAULT_CONFIG_DIR

            base_dir = str(DEFAULT_CONFIG_DIR / "blobs")

        self._base_dir = Path(base_dir)
        from openjarvis.security.file_utils import secure_mkdir

        secure_mkdir(self._base_dir)

        db_path = self._base_dir / "attachments.db"
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._setup()

    # ------------------------------------------------------------------
    # Internal setup
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(f"{_CREATE_TABLE}")
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        content: bytes,
        *,
        filename: str,
        mime_type: str = "",
        source_doc_id: str = "",
    ) -> str:
        """Store *content* and return its SHA-256 hex digest.

        The call is idempotent with respect to the blob file — if the same
        bytes are stored again only the metadata (source_doc_ids) is updated.
        """
        sha = hashlib.sha256(content).hexdigest()

        # Write blob file (idempotent)
        blob_dir = self._base_dir / sha[:2]
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / sha
        if not blob_path.exists():
            blob_path.write_bytes(content)
            import os

            os.chmod(blob_path, 0o600)

        # Upsert metadata row
        existing = self._conn.execute(
            "SELECT source_doc_ids FROM attachments WHERE sha256 = ?", (sha,)
        ).fetchone()

        if existing is None:
            source_ids: List[str] = []
            if source_doc_id:
                source_ids.append(source_doc_id)
            self._conn.execute(
                """
                INSERT INTO attachments
                    (sha256, filename, mime_type, size_bytes,
                     source_doc_ids, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sha,
                    filename,
                    mime_type,
                    len(content),
                    json.dumps(source_ids),
                    time.time(),
                ),
            )
        else:
            source_ids = json.loads(existing["source_doc_ids"])
            if source_doc_id and source_doc_id not in source_ids:
                source_ids.append(source_doc_id)
            self._conn.execute(
                "UPDATE attachments SET source_doc_ids = ? WHERE sha256 = ?",
                (json.dumps(source_ids), sha),
            )

        self._conn.commit()
        return sha

    def get_metadata(self, sha: str) -> Optional[Dict]:
        """Return the metadata dict for *sha*, or ``None`` if not found.

        Returned keys: ``sha256``, ``filename``, ``mime_type``,
        ``size_bytes``, ``source_doc_ids`` (list), ``created_at``.
        """
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
        """Return the raw bytes for *sha*, or ``None`` if the blob is missing."""
        blob_path = self._base_dir / sha[:2] / sha
        if not blob_path.exists():
            return None
        return blob_path.read_bytes()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["AttachmentStore"]
