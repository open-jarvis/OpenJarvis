"""iMessage connector — reads directly from the macOS Messages SQLite database.

No API calls, no OAuth.  The connector opens ``~/Library/Messages/chat.db``
in read-only mode and yields one :class:`Document` per message that has
non-NULL text.

Requires **Full Disk Access** granted to the terminal / app in
System Settings → Privacy & Security → Full Disk Access.

Timestamp notes
---------------
The iMessage database stores timestamps as nanoseconds since the Apple
epoch of 2001-01-01 00:00:00 UTC.  Conversion formula::

    dt = datetime(2001, 1, 1, tzinfo=utc) + timedelta(seconds=apple_ns / 1_000_000_000)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

# Apple epoch: 2001-01-01 00:00:00 UTC
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------


def _apple_ts_to_datetime(apple_ns: int) -> datetime:
    """Convert an Apple nanosecond timestamp to a UTC :class:`datetime`.

    Parameters
    ----------
    apple_ns:
        Nanoseconds since 2001-01-01 00:00:00 UTC.

    Returns
    -------
    datetime
        UTC-aware datetime.
    """
    seconds = apple_ns / 1_000_000_000
    return _APPLE_EPOCH + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# IMessageConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("imessage")
class IMessageConnector(BaseConnector):
    """Connector that reads messages from the macOS Messages SQLite database.

    Parameters
    ----------
    db_path:
        Path to ``chat.db``.  Defaults to
        ``~/Library/Messages/chat.db``.
    """

    connector_id = "imessage"
    display_name = "iMessage"
    auth_type = "local"

    def __init__(self, db_path: str = "") -> None:
        self._db_path: Path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._connected: bool = False
        self._items_synced: int = 0
        self._items_total: int = 0
        self._last_sync: Optional[datetime] = None

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return ``True`` if the chat.db file exists at the configured path."""
        return self._db_path.exists()

    def disconnect(self) -> None:
        """Mark the connector as disconnected."""
        self._connected = False

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,  # noqa: ARG002
    ) -> Iterator[Document]:
        """Read messages from chat.db and yield one :class:`Document` each.

        Parameters
        ----------
        since:
            If provided, skip messages whose timestamp is before this
            datetime.
        cursor:
            Not used for this local connector (included for API
            compatibility).

        Yields
        ------
        Document
            One document per message with non-NULL text.
        """
        db_path = str(self._db_path)

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            return

        try:
            # ------------------------------------------------------------------
            # 1. Build handle_id → identifier map
            # ------------------------------------------------------------------
            handle_map: Dict[int, str] = {}
            for row in conn.execute("SELECT ROWID, id FROM handle"):
                handle_map[row[0]] = row[1]

            # ------------------------------------------------------------------
            # 2. Build message_id → chat_id map
            # ------------------------------------------------------------------
            msg_to_chat: Dict[int, int] = {}
            for row in conn.execute(
                "SELECT message_id, chat_id FROM chat_message_join"
            ):
                msg_to_chat[row[0]] = row[1]

            # ------------------------------------------------------------------
            # 3. Build chat_id → {identifier, display_name} map
            # ------------------------------------------------------------------
            chat_map: Dict[int, Tuple[str, str]] = {}
            for row in conn.execute(
                "SELECT ROWID, chat_identifier, display_name FROM chat"
            ):
                chat_id: int = row[0]
                chat_identifier: str = row[1] or ""
                display_name: str = row[2] or chat_identifier
                chat_map[chat_id] = (chat_identifier, display_name)

            # ------------------------------------------------------------------
            # 4. Query messages with non-NULL text
            # ------------------------------------------------------------------
            rows = conn.execute(
                "SELECT ROWID, text, handle_id, date, is_from_me "
                "FROM message "
                "WHERE text IS NOT NULL "
                "ORDER BY date ASC"
            ).fetchall()

            self._items_total = len(rows)
            synced = 0

            for row in rows:
                rowid: int = row[0]
                text: str = row[1]
                handle_id: int = row[2] or 0
                apple_ts: int = row[3] or 0
                is_from_me: int = row[4] or 0

                # Convert timestamp
                timestamp = _apple_ts_to_datetime(apple_ts)

                # Apply since filter
                if since is not None:
                    since_utc = since
                    if since_utc.tzinfo is None:
                        since_utc = since_utc.replace(tzinfo=timezone.utc)
                    if timestamp < since_utc:
                        continue

                # Determine author
                if is_from_me:
                    author = "me"
                else:
                    author = handle_map.get(handle_id, "unknown")

                # Determine chat name / title
                chat_id = msg_to_chat.get(rowid)
                if chat_id is not None and chat_id in chat_map:
                    _chat_identifier, chat_name = chat_map[chat_id]
                else:
                    # Fall back to the handle identifier
                    chat_name = handle_map.get(handle_id, "")

                doc = Document(
                    doc_id=f"imessage:{rowid}",
                    source="imessage",
                    doc_type="message",
                    content=text,
                    title=chat_name,
                    author=author,
                    timestamp=timestamp,
                )
                synced += 1
                yield doc

            self._items_synced = synced
            self._last_sync = datetime.now(tz=timezone.utc)

        finally:
            conn.close()

    def sync_status(self) -> SyncStatus:
        """Return sync progress from the most recent :meth:`sync` call."""
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            items_total=self._items_total,
            last_sync=self._last_sync,
        )

    # ------------------------------------------------------------------
    # MCP tools
    # ------------------------------------------------------------------

    def mcp_tools(self) -> List[ToolSpec]:
        """Expose two MCP tool specs for real-time iMessage queries."""
        return [
            ToolSpec(
                name="imessage_search_messages",
                description=(
                    "Search iMessage messages by keyword or contact. "
                    "Returns matching messages with sender and timestamp."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query string",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of messages to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="knowledge",
            ),
            ToolSpec(
                name="imessage_get_conversation",
                description=(
                    "Retrieve the full message history for a specific iMessage "
                    "conversation by contact phone number or email address."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "contact": {
                            "type": "string",
                            "description": (
                                "Phone number or email address of the contact "
                                "(e.g. '+15550100' or 'alice@icloud.com')"
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of messages to return",
                            "default": 50,
                        },
                    },
                    "required": ["contact"],
                },
                category="knowledge",
            ),
        ]
