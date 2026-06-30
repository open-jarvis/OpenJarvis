"""Apple Calendar connector — reads directly from the macOS Calendar SQLite database.

No API calls, no OAuth, no app-specific password.  Opens
``~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb``
in read-only mode and yields one :class:`Document` per upcoming event.

Requires **Full Disk Access** granted to the terminal / app in
System Settings → Privacy & Security → Full Disk Access.

Timestamp notes
---------------
The Calendar database stores timestamps as seconds since the Apple epoch
of 2001-01-01 00:00:00 UTC (same convention as Apple Contacts).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CAL_DB = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "group.com.apple.calendar"
    / "Calendar.sqlitedb"
)

# Apple epoch: 2001-01-01 00:00:00 UTC
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Default lookahead window for digest
_DEFAULT_DAYS_AHEAD = 7
_DEFAULT_DAYS_BEHIND = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apple_ts(seconds: float) -> datetime:
    return _APPLE_EPOCH + timedelta(seconds=seconds)


def _to_apple_ts(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - _APPLE_EPOCH).total_seconds()


def _open_db(path: Path) -> sqlite3.Connection | None:
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_EVENTS_QUERY = """\
SELECT
    ci.ROWID,
    ci.summary,
    ci.description,
    ci.start_date,
    ci.end_date,
    ci.all_day,
    ci.start_tz,
    ci.location_id,
    ci.has_attendees,
    ci.last_modified,
    ci.UUID,
    c.title  AS calendar_title,
    c.color  AS calendar_color
FROM CalendarItem ci
JOIN Calendar c ON ci.calendar_id = c.ROWID
WHERE ci.start_date BETWEEN ? AND ?
  AND ci.summary IS NOT NULL
  AND ci.hidden = 0
ORDER BY ci.start_date ASC
"""

_LOCATION_QUERY = """\
SELECT title, address FROM Location WHERE ROWID = ?
"""

_SEARCH_QUERY = """\
SELECT
    ci.ROWID,
    ci.summary,
    ci.description,
    ci.start_date,
    ci.end_date,
    ci.all_day,
    ci.start_tz,
    ci.UUID,
    c.title AS calendar_title
FROM CalendarItem ci
JOIN Calendar c ON ci.calendar_id = c.ROWID
WHERE ci.summary LIKE ?
  AND ci.hidden = 0
ORDER BY ci.start_date DESC
LIMIT ?
"""


# ---------------------------------------------------------------------------
# AppleCalendarConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("apple_calendar")
class AppleCalendarConnector(BaseConnector):
    """Connector that reads events from the macOS Calendar SQLite database.

    Parameters
    ----------
    db_path:
        Path to ``Calendar.sqlitedb``.  Defaults to the system location.
    days_ahead:
        How many days into the future to fetch (default: 7).
    days_behind:
        How many days into the past to fetch (default: 1).
    """

    connector_id = "apple_calendar"
    display_name = "Apple Calendar"
    auth_type = "local"

    def __init__(
        self,
        db_path: str = "",
        days_ahead: int = _DEFAULT_DAYS_AHEAD,
        days_behind: int = _DEFAULT_DAYS_BEHIND,
    ) -> None:
        self._db_path = Path(db_path) if db_path else _CAL_DB
        self._days_ahead = days_ahead
        self._days_behind = days_behind
        self._items_synced = 0
        self._items_total = 0
        self._last_sync: Optional[datetime] = None

    def is_connected(self) -> bool:
        return self._db_path.exists()

    def disconnect(self) -> None:
        pass

    def _fetch_location(self, conn: sqlite3.Connection, loc_id: int | None) -> str:
        if not loc_id:
            return ""
        row = conn.execute(_LOCATION_QUERY, (loc_id,)).fetchone()
        if not row:
            return ""
        parts = [p for p in (row[0], row[1]) if p]
        return ", ".join(parts)

    def _build_content(self, row: tuple, location: str) -> str:
        (
            _rowid, summary, description, start_ts, end_ts, all_day,
            start_tz, _loc_id, has_attendees, _last_mod, _uuid, cal_title, _color,
        ) = row

        start_dt = _apple_ts(start_ts)
        end_dt = _apple_ts(end_ts) if end_ts else None

        if all_day:
            date_str = start_dt.strftime("%A, %B %-d %Y (all day)")
        else:
            date_str = start_dt.strftime("%A, %B %-d %Y at %-I:%M %p")
            if end_dt:
                date_str += end_dt.strftime(" – %-I:%M %p")
            if start_tz and start_tz != "_float":
                date_str += f" ({start_tz})"

        lines = [summary, f"Date: {date_str}", f"Calendar: {cal_title}"]
        if location:
            lines.append(f"Location: {location}")
        if description and description.strip():
            lines.append(f"Notes: {description.strip()}")
        if has_attendees:
            lines.append("Attendees: yes")

        return "\n".join(lines)

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        conn = _open_db(self._db_path)
        if conn is None:
            return

        now = datetime.now(tz=timezone.utc)
        window_start = now - timedelta(days=self._days_behind)
        window_end = now + timedelta(days=self._days_ahead)

        start_ts = _to_apple_ts(window_start)
        end_ts = _to_apple_ts(window_end)

        try:
            rows = conn.execute(_EVENTS_QUERY, (start_ts, end_ts)).fetchall()
            self._items_total = len(rows)
            synced = 0

            for row in rows:
                (
                    rowid, summary, description, start_date, end_date, all_day,
                    start_tz, loc_id, has_attendees, last_mod, uuid,
                    cal_title, color,
                ) = row

                timestamp = _apple_ts(last_mod) if last_mod else _apple_ts(start_date)
                if since is not None:
                    since_utc = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
                    if timestamp < since_utc:
                        continue

                location = self._fetch_location(conn, loc_id)
                content = self._build_content(row, location)
                start_dt = _apple_ts(start_date)

                meta: Dict[str, Any] = {
                    "summary": summary,
                    "calendar": cal_title,
                    "start": start_dt.isoformat(),
                    "all_day": bool(all_day),
                    "location": location,
                    "has_attendees": bool(has_attendees),
                }

                yield Document(
                    doc_id=f"apple_calendar:{uuid or rowid}",
                    source="apple_calendar",
                    doc_type="calendar_event",
                    content=content,
                    title=summary,
                    author=cal_title,
                    timestamp=timestamp,
                    metadata=meta,
                )
                synced += 1

            self._items_synced = synced

        finally:
            conn.close()

        self._last_sync = datetime.now(tz=timezone.utc)

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            items_total=self._items_total,
            last_sync=self._last_sync,
        )

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="calendar_upcoming",
                description=(
                    "Return upcoming Apple Calendar events. "
                    "Reads directly from the local macOS Calendar database."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "days_ahead": {
                            "type": "integer",
                            "description": "Number of days ahead to look (default: 7)",
                            "default": 7,
                        },
                    },
                },
                category="knowledge",
            ),
            ToolSpec(
                name="calendar_search",
                description="Search Apple Calendar events by title keyword.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keyword to search in event titles",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="knowledge",
            ),
        ]
