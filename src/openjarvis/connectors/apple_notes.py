"""Apple Notes connector — reads directly from the macOS Notes SQLite database.

No API calls, no OAuth.  The connector opens
``~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite``
in read-only mode and yields one :class:`Document` per note.

Requires **Full Disk Access** granted to the terminal / app in
System Settings → Privacy & Security → Full Disk Access.

Timestamp notes
---------------
The Notes database stores modification timestamps as seconds since the Apple
epoch of 2001-01-01 00:00:00 UTC.  Conversion formula::

    dt = datetime(2001, 1, 1, tzinfo=utc) + timedelta(seconds=ZMODIFICATIONDATE)

Content extraction
------------------
The ``ZDATA`` column in ``ZICNOTEDATA`` contains gzip-compressed HTML.  Plain
text is obtained by decompressing the bytes and stripping HTML tags.
"""

from __future__ import annotations

import gzip
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, List, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "group.com.apple.notes"
    / "NoteStore.sqlite"
)

# Apple epoch: 2001-01-01 00:00:00 UTC
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apple_ts_to_datetime(apple_seconds: float) -> datetime:
    """Convert an Apple seconds timestamp to a UTC :class:`datetime`.

    Parameters
    ----------
    apple_seconds:
        Seconds since 2001-01-01 00:00:00 UTC.

    Returns
    -------
    datetime
        UTC-aware datetime.
    """
    return _APPLE_EPOCH + timedelta(seconds=apple_seconds)


def _extract_text_from_zdata(zdata: bytes) -> str:
    """Decompress gzip bytes and strip HTML tags to return plain text.

    Parameters
    ----------
    zdata:
        Raw bytes from the ``ZDATA`` column (gzip-compressed HTML).

    Returns
    -------
    str
        Plain text with all HTML tags removed.  Returns an empty string if
        decompression fails.
    """
    try:
        html = gzip.decompress(zdata).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""
    return re.sub(r"<[^>]+>", "", html)


# ---------------------------------------------------------------------------
# AppleNotesConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("apple_notes")
class AppleNotesConnector(BaseConnector):
    """Connector that reads notes from the macOS Notes SQLite database.

    Parameters
    ----------
    db_path:
        Path to ``NoteStore.sqlite``.  Defaults to
        ``~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite``.
    """

    connector_id = "apple_notes"
    display_name = "Apple Notes"
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
        """Return ``True`` if NoteStore.sqlite exists at the configured path."""
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
        """Read notes from NoteStore.sqlite and yield one :class:`Document` each.

        Parameters
        ----------
        since:
            If provided, skip notes whose modification time is before this
            datetime.
        cursor:
            Not used for this local connector (included for API
            compatibility).

        Yields
        ------
        Document
            One document per note, with gzip-decompressed plain-text content.
        """
        db_path = str(self._db_path)

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            return

        try:
            rows = conn.execute(
                "SELECT n.ZIDENTIFIER, n.ZTITLE, n.ZMODIFICATIONDATE, d.ZDATA "
                "FROM ZICCLOUDSYNCINGOBJECT n "
                "JOIN ZICNOTEDATA d ON d.ZNOTE = n.Z_PK "
                "ORDER BY n.ZMODIFICATIONDATE ASC"
            ).fetchall()

            self._items_total = len(rows)
            synced = 0

            for row in rows:
                identifier: str = row[0] or ""
                title: str = row[1] or ""
                mod_date: float = row[2] or 0.0
                zdata: bytes = row[3] or b""

                timestamp = _apple_ts_to_datetime(mod_date)

                # Apply since filter
                if since is not None:
                    since_utc = since
                    if since_utc.tzinfo is None:
                        since_utc = since_utc.replace(tzinfo=timezone.utc)
                    if timestamp < since_utc:
                        continue

                content = _extract_text_from_zdata(zdata)

                doc = Document(
                    doc_id=f"apple_notes:{identifier}",
                    source="apple_notes",
                    doc_type="note",
                    content=content,
                    title=title,
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
        """Expose two MCP tool specs for real-time Apple Notes queries."""
        return [
            ToolSpec(
                name="notes_search",
                description=(
                    "Search Apple Notes by keyword. "
                    "Returns matching notes with title and content snippet."
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
                            "description": "Maximum number of notes to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="knowledge",
            ),
            ToolSpec(
                name="notes_get_note",
                description=(
                    "Retrieve the full text content of an Apple Note by its "
                    "unique identifier."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "note_id": {
                            "type": "string",
                            "description": (
                                "Apple Notes unique identifier (ZIDENTIFIER)"
                            ),
                        },
                    },
                    "required": ["note_id"],
                },
                category="knowledge",
            ),
        ]
