"""EmbeddingStore --- disk-persistent ColBERT token-level embeddings.

Stores per-chunk ColBERTv2 token embeddings as individual ``.pt`` files on
disk with a SQLite index for O(1) chunk_id lookups.  Designed to be used by
``ColBERTReranker`` so that document embeddings computed at ingest time can
be reused across queries instead of re-encoding on every search.

All ``torch`` usage is lazily imported and guarded behind ``try/except`` so
that the store degrades gracefully when PyTorch is not installed --- every
public method returns ``None`` or ``False`` instead of raising.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import torch  # type: ignore[import]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL for the lightweight SQLite index
# ---------------------------------------------------------------------------

_CREATE_INDEX_TABLE = """
CREATE TABLE IF NOT EXISTS embedding_index (
    chunk_id  TEXT PRIMARY KEY,
    filename  TEXT NOT NULL
);
"""


class EmbeddingStore:
    """Stores ColBERT token-level embeddings on disk.

    Each ``chunk_id`` maps to a tensor of shape ``(num_tokens, 128)`` saved
    as a standard PyTorch ``.pt`` file.  A small SQLite database provides an
    O(1) index from *chunk_id* to the tensor filename.

    Parameters
    ----------
    store_dir:
        Root directory for the embedding store.  Defaults to
        ``~/.openjarvis/embeddings/``.  The directory is created if it does
        not already exist.
    """

    def __init__(self, store_dir: str = "") -> None:
        if not store_dir:
            from openjarvis.core.config import DEFAULT_CONFIG_DIR

            store_dir = str(DEFAULT_CONFIG_DIR / "embeddings")

        self._store_dir = Path(store_dir)
        self._tensor_dir = self._store_dir / "tensors"
        self._tensor_dir.mkdir(parents=True, exist_ok=True)

        db_path = self._store_dir / "index.db"
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_CREATE_INDEX_TABLE)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, chunk_id: str, embedding: "torch.Tensor") -> None:
        """Save a chunk's embedding tensor to disk.

        Parameters
        ----------
        chunk_id:
            Unique identifier for the chunk (matches the KnowledgeStore PK).
        embedding:
            Tensor of shape ``(num_tokens, 128)`` from ColBERT encoding.
        """
        try:
            import torch as _torch  # noqa: F401
        except ImportError:
            logger.debug("EmbeddingStore.store: torch not available, skipping.")
            return

        filename = f"{chunk_id}.pt"
        tensor_path = self._tensor_dir / filename

        _torch.save(embedding, str(tensor_path))

        self._conn.execute(
            "INSERT OR REPLACE INTO embedding_index (chunk_id, filename) VALUES (?, ?)",
            (chunk_id, filename),
        )
        self._conn.commit()

    def get(self, chunk_id: str) -> Optional["torch.Tensor"]:
        """Load a chunk's embedding from disk.

        Returns ``None`` if the chunk has no stored embedding or if
        ``torch`` is not installed.
        """
        try:
            import torch as _torch  # noqa: F401
        except ImportError:
            return None

        row = self._conn.execute(
            "SELECT filename FROM embedding_index WHERE chunk_id = ?",
            (chunk_id,),
        ).fetchone()

        if row is None:
            return None

        tensor_path = self._tensor_dir / row[0]
        if not tensor_path.exists():
            # Stale index entry --- clean it up
            self._conn.execute(
                "DELETE FROM embedding_index WHERE chunk_id = ?", (chunk_id,)
            )
            self._conn.commit()
            return None

        try:
            return _torch.load(str(tensor_path), weights_only=True)
        except Exception as exc:
            logger.warning(
                "EmbeddingStore.get: failed to load tensor for %s (%s)", chunk_id, exc
            )
            return None

    def has(self, chunk_id: str) -> bool:
        """Check if embeddings exist for a chunk."""
        row = self._conn.execute(
            "SELECT 1 FROM embedding_index WHERE chunk_id = ?",
            (chunk_id,),
        ).fetchone()
        return row is not None

    def count(self) -> int:
        """Return the number of stored embeddings."""
        row = self._conn.execute("SELECT COUNT(*) FROM embedding_index").fetchone()
        return row[0] if row else 0

    def delete(self, chunk_id: str) -> bool:
        """Delete the embedding for a chunk.

        Returns ``True`` if the embedding existed and was removed.
        """
        row = self._conn.execute(
            "SELECT filename FROM embedding_index WHERE chunk_id = ?",
            (chunk_id,),
        ).fetchone()

        if row is None:
            return False

        tensor_path = self._tensor_dir / row[0]
        if tensor_path.exists():
            tensor_path.unlink()

        self._conn.execute(
            "DELETE FROM embedding_index WHERE chunk_id = ?", (chunk_id,)
        )
        self._conn.commit()
        return True

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["EmbeddingStore"]
