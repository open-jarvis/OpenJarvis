"""SyncEngine — checkpoint/resume orchestration for connector syncs.

Wraps ``IngestionPipeline`` with a lightweight SQLite state database so that
long-running syncs can be interrupted and resumed from the last saved cursor.

Typical usage::

    store = KnowledgeStore(db_path=":memory:")
    pipeline = IngestionPipeline(store)
    engine = SyncEngine(pipeline)

    items = engine.sync(connector)        # first run
    items = engine.sync(connector)        # resumes from saved cursor
    cp = engine.get_checkpoint(connector.connector_id)
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from openjarvis.connectors._stubs import BaseConnector
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.core.config import DEFAULT_CONFIG_DIR

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS sync_state (
    connector_id  TEXT PRIMARY KEY,
    items_synced  INTEGER NOT NULL DEFAULT 0,
    cursor        TEXT,
    last_sync     TEXT,
    error         TEXT
);
"""

_BATCH_SIZE = 100


class SyncEngine:
    """Orchestrate connector syncs with checkpoint/resume tracking.

    Parameters
    ----------
    pipeline:
        The ``IngestionPipeline`` that documents are fed into.
    state_db:
        Path to the SQLite database used for checkpoint state.  If empty,
        defaults to ``DEFAULT_CONFIG_DIR / "sync_state.db"``.
    """

    def __init__(self, pipeline: IngestionPipeline, *, state_db: str = "") -> None:
        self._pipeline = pipeline

        if not state_db:
            db_path = DEFAULT_CONFIG_DIR / "sync_state.db"
        else:
            db_path = Path(state_db)

        # Ensure parent directory exists (skip for :memory:)
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(_CREATE_STATE_TABLE)
        self._conn.commit()

    def __enter__(self) -> "SyncEngine":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync(
        self,
        connector: BaseConnector,
        *,
        cancel_event: Optional[threading.Event] = None,
    ) -> int:
        """Run a full sync for *connector* and return the number of items ingested.

        Resumes from the last saved cursor if one exists.  Documents are
        batched in groups of 100 before being handed to the pipeline; a
        checkpoint is saved after every batch and once more at the end.

        On error the checkpoint is updated with the error message and the
        exception is re-raised so callers can handle it.
        """
        connector_id: str = connector.connector_id

        # Load any previous checkpoint so we can resume.
        checkpoint = self.get_checkpoint(connector_id)
        prior_cursor: Optional[str] = checkpoint["cursor"] if checkpoint else None
        prior_items: int = checkpoint["items_synced"] if checkpoint else 0

        since: Optional[datetime] = None
        if checkpoint and checkpoint.get("last_sync"):
            try:
                since = datetime.fromisoformat(checkpoint["last_sync"])
            except (ValueError, TypeError):
                pass

        # Captured before the first fetch, not at completion, so items
        # created/modified while this sync was running are still covered
        # by the *next* sync's `since` filter instead of being skipped.
        sync_started_at = datetime.now(tz=timezone.utc).isoformat()

        items_ingested = 0
        current_cursor: Optional[str] = prior_cursor

        try:
            doc_iter = connector.sync(since=since, cursor=prior_cursor)

            batch = []
            for doc in doc_iter:
                if cancel_event is not None and cancel_event.is_set():
                    break
                batch.append(doc)

                if len(batch) >= _BATCH_SIZE:
                    items_ingested += self._pipeline.ingest(batch)
                    batch = []
                    # Progress checkpoint: track cursor/items so a later
                    # retry can resume from here, but must NOT advance
                    # last_sync -- this sync hasn't completed yet, and
                    # advancing the watermark on a checkpoint that isn't a
                    # successful completion would permanently skip
                    # whatever wasn't reached if the sync then fails (#782).
                    self._save_checkpoint(
                        connector_id,
                        prior_items + items_ingested,
                        cursor=current_cursor,
                    )

            # Ingest any remaining documents.
            if batch and not (cancel_event is not None and cancel_event.is_set()):
                items_ingested += self._pipeline.ingest(batch)

        except Exception as exc:
            self._save_checkpoint(
                connector_id,
                prior_items + items_ingested,
                cursor=current_cursor,
                error=str(exc),
            )
            raise

        if cancel_event is not None and cancel_event.is_set():
            # Cancellation means the source was not exhausted. Preserve the
            # prior successful watermark exactly as failure checkpoints do;
            # advancing it here could make the next sync skip documents that
            # the cancelled run never reached (#782).
            self._save_checkpoint(
                connector_id,
                prior_items + items_ingested,
                cursor=current_cursor,
                error=None,
            )
            return items_ingested

        # Final checkpoint on successful completion — clear any previous
        # error and advance the watermark to when this sync started.
        self._save_checkpoint(
            connector_id,
            prior_items + items_ingested,
            cursor=current_cursor,
            error=None,
            last_sync=sync_started_at,
        )
        return items_ingested

    def close(self) -> None:
        """Close the checkpoint database connection."""
        self._conn.close()

    def get_checkpoint(self, connector_id: str) -> Optional[Dict[str, Any]]:
        """Return the last checkpoint, or ``None`` if never synced."""
        sql = (
            "SELECT items_synced, cursor, last_sync, error"
            " FROM sync_state WHERE connector_id = ?"
        )
        row = self._conn.execute(sql, (connector_id,)).fetchone()

        if row is None:
            return None

        return {
            "items_synced": row["items_synced"],
            "cursor": row["cursor"],
            "last_sync": row["last_sync"],
            "error": row["error"],
        }

    def reset_checkpoint(self, connector_id: str) -> None:
        """Clear the saved checkpoint for *connector_id*.

        Must be called whenever a connector is reconfigured to point at a
        different underlying data source (e.g. disconnect/reconnect with a
        new Obsidian vault path). Without this, the next sync would resume
        from the old source's cursor/``since`` watermark, inflating
        ``items_synced`` with the old source's count and potentially
        skipping new items whose timestamps predate that watermark.
        """
        self._conn.execute(
            "DELETE FROM sync_state WHERE connector_id = ?", (connector_id,)
        )
        self._conn.commit()

    def restore_checkpoint(
        self,
        connector_id: str,
        checkpoint: Optional[Dict[str, Any]],
    ) -> None:
        """Restore an exact checkpoint snapshot after a failed cleanup."""
        if checkpoint is None:
            self.reset_checkpoint(connector_id)
            return
        self._conn.execute(
            """
            INSERT INTO sync_state
                (connector_id, items_synced, cursor, last_sync, error)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(connector_id) DO UPDATE SET
                items_synced = excluded.items_synced,
                cursor       = excluded.cursor,
                last_sync    = excluded.last_sync,
                error        = excluded.error
            """,
            (
                connector_id,
                checkpoint["items_synced"],
                checkpoint.get("cursor"),
                checkpoint.get("last_sync"),
                checkpoint.get("error"),
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_checkpoint(
        self,
        connector_id: str,
        items_synced: int,
        *,
        cursor: Optional[str] = None,
        error: Optional[str] = None,
        last_sync: Optional[str] = None,
    ) -> None:
        """UPSERT a checkpoint row into the state database.

        ``last_sync`` only advances when the caller explicitly passes a
        value (a successful sync completion). ``COALESCE`` preserves the
        existing watermark on progress/error checkpoints, so a failed or
        still-in-progress sync can never permanently skip unprocessed
        items (#782).
        """
        self._conn.execute(
            """
            INSERT INTO sync_state
                (connector_id, items_synced, cursor, last_sync, error)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(connector_id) DO UPDATE SET
                items_synced = excluded.items_synced,
                cursor       = excluded.cursor,
                last_sync    = COALESCE(excluded.last_sync, sync_state.last_sync),
                error        = excluded.error
            """,
            (connector_id, items_synced, cursor, last_sync, error),
        )
        self._conn.commit()


__all__ = ["SyncEngine"]
