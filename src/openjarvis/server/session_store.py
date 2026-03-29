"""SQLite-backed session store for channel conversations."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_HISTORY_TURNS = 20


class SessionStore:
    """Manages per-sender, per-channel conversation sessions.

    Each session tracks conversation history, notification preferences,
    and pending long responses for the ``/more`` command.
    """

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "sessions.db")
        from openjarvis.security.file_utils import secure_create

        secure_create(Path(db_path))
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._create_tables()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        self._db.executescript(
            """\
            CREATE TABLE IF NOT EXISTS channel_sessions (
                sender_id                    TEXT    NOT NULL,
                channel_type                 TEXT    NOT NULL,
                conversation_history         TEXT    NOT NULL DEFAULT '[]',
                preferred_notification_channel TEXT,
                pending_response             TEXT,
                created_at                   TIMESTAMP DEFAULT (datetime('now')),
                updated_at                   TIMESTAMP DEFAULT (datetime('now')),
                PRIMARY KEY (sender_id, channel_type)
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
                ON channel_sessions (updated_at);
            """
        )
        self._db.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_create(self, sender_id: str, channel_type: str) -> Dict[str, Any]:
        row = self._db.execute(
            "SELECT * FROM channel_sessions WHERE sender_id = ? AND channel_type = ?",
            (sender_id, channel_type),
        ).fetchone()
        if row is None:
            self._db.execute(
                "INSERT INTO channel_sessions (sender_id, channel_type) VALUES (?, ?)",
                (sender_id, channel_type),
            )
            self._db.commit()
            return {
                "sender_id": sender_id,
                "channel_type": channel_type,
                "conversation_history": [],
                "preferred_notification_channel": None,
                "pending_response": None,
            }
        return {
            "sender_id": row["sender_id"],
            "channel_type": row["channel_type"],
            "conversation_history": json.loads(row["conversation_history"]),
            "preferred_notification_channel": row["preferred_notification_channel"],
            "pending_response": row["pending_response"],
        }

    def append_message(
        self,
        sender_id: str,
        channel_type: str,
        role: str,
        content: str,
    ) -> None:
        row = self._db.execute(
            "SELECT conversation_history FROM channel_sessions "
            "WHERE sender_id = ? AND channel_type = ?",
            (sender_id, channel_type),
        ).fetchone()
        if row is None:
            return
        history: List[Dict[str, str]] = json.loads(row["conversation_history"])
        history.append({"role": role, "content": content})
        if len(history) > _MAX_HISTORY_TURNS:
            history = history[-_MAX_HISTORY_TURNS:]
        self._db.execute(
            "UPDATE channel_sessions "
            "SET conversation_history = ?, "
            "updated_at = datetime('now') "
            "WHERE sender_id = ? AND channel_type = ?",
            (json.dumps(history), sender_id, channel_type),
        )
        self._db.commit()

    def set_notification_preference(
        self,
        sender_id: str,
        channel_type: str,
        preferred: str,
    ) -> None:
        self._db.execute(
            "UPDATE channel_sessions "
            "SET preferred_notification_channel = ?, "
            "updated_at = datetime('now') "
            "WHERE sender_id = ? AND channel_type = ?",
            (preferred, sender_id, channel_type),
        )
        self._db.commit()

    def set_pending_response(
        self,
        sender_id: str,
        channel_type: str,
        response: str,
    ) -> None:
        self._db.execute(
            "UPDATE channel_sessions "
            "SET pending_response = ?, "
            "updated_at = datetime('now') "
            "WHERE sender_id = ? AND channel_type = ?",
            (response, sender_id, channel_type),
        )
        self._db.commit()

    def clear_pending_response(self, sender_id: str, channel_type: str) -> None:
        self.set_pending_response(sender_id, channel_type, None)

    def expire_sessions(self, max_age_hours: int = 24) -> int:
        cur = self._db.execute(
            "UPDATE channel_sessions "
            "SET conversation_history = '[]', "
            "pending_response = NULL "
            "WHERE updated_at < datetime('now', ? || ' hours')",
            (f"-{max_age_hours}",),
        )
        self._db.commit()
        return cur.rowcount

    def get_last_active_channel(self, sender_id: str) -> Optional[str]:
        row = self._db.execute(
            "SELECT channel_type FROM channel_sessions "
            "WHERE sender_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (sender_id,),
        ).fetchone()
        return row["channel_type"] if row else None

    def get_notification_targets(self) -> List[Dict[str, str]]:
        """Return all senders with a notification channel."""
        rows = self._db.execute(
            "SELECT sender_id, channel_type, "
            "preferred_notification_channel "
            "FROM channel_sessions "
            "WHERE preferred_notification_channel IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._db.close()
