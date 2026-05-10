"""Thunderbird calendar connector using Lightning's local SQLite cache."""

from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
from pathlib import Path
from typing import Iterator, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry


def _default_profile_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Thunderbird" / "Profiles"
    return Path.home() / "AppData" / "Roaming" / "Thunderbird" / "Profiles"


def _us_to_datetime(microseconds: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(microseconds / 1_000_000)


def _datetime_to_us(value: dt.datetime) -> int:
    return int(value.timestamp() * 1_000_000)


@ConnectorRegistry.register("thunderbird_calendar")
class ThunderbirdCalendarConnector(BaseConnector):
    """Read upcoming events from Thunderbird's read-only calendar cache."""

    connector_id = "thunderbird_calendar"
    display_name = "Thunderbird Calendar"
    auth_type = "filesystem"

    def __init__(
        self,
        *,
        profile_dir: str = "",
        days_ahead: int = 14,
        max_events: int = 50,
    ) -> None:
        self._profile_dir = Path(profile_dir) if profile_dir else _default_profile_dir()
        self._days_ahead = days_ahead
        self._max_events = max_events
        self._items_synced = 0
        self._items_total = 0
        self._last_sync: Optional[dt.datetime] = None

    def _profiles(self) -> list[Path]:
        if not self._profile_dir.exists():
            return []
        profiles = [p for p in self._profile_dir.iterdir() if p.is_dir()]
        default_release = [p for p in profiles if "default-release" in p.name]
        rest = [p for p in profiles if p not in default_release]
        return default_release + rest

    def _database_paths(self) -> list[Path]:
        paths: list[Path] = []
        for profile in self._profiles():
            cal_dir = profile / "calendar-data"
            for name in ("cache.sqlite", "local.sqlite"):
                candidate = cal_dir / name
                if candidate.exists():
                    paths.append(candidate)
            if paths:
                break
        return paths

    def _calendar_names(self) -> dict[str, str]:
        names: dict[str, str] = {}
        for profile in self._profiles():
            prefs_js = profile / "prefs.js"
            if not prefs_js.exists():
                continue
            text = prefs_js.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(
                r'calendar\.registry\.([A-Za-z0-9-]+)\.name", "([^"]+)"',
                text,
            ):
                names[match.group(1)] = match.group(2)
            if names:
                break
        return names

    def is_connected(self) -> bool:
        return bool(self._database_paths())

    def disconnect(self) -> None:
        return None

    def sync(
        self,
        *,
        since: Optional[dt.datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        start = since or dt.datetime.now()
        end = dt.datetime.now() + dt.timedelta(days=self._days_ahead)
        start_us = _datetime_to_us(start)
        end_us = _datetime_to_us(end)
        names = self._calendar_names()

        rows: list[tuple[Path, int, str, int, int, str]] = []
        for db_path in self._database_paths():
            con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
            try:
                cur = con.cursor()
                cur.execute(
                    """
                    SELECT rowid, title, event_start, event_end, cal_id
                    FROM cal_events
                    WHERE event_start >= ? AND event_start <= ?
                    ORDER BY event_start
                    LIMIT ?
                    """,
                    (start_us, end_us, self._max_events),
                )
                for rowid, title, event_start, event_end, cal_id in cur.fetchall():
                    rows.append(
                        (
                            db_path,
                            int(rowid),
                            title or "(ohne Titel)",
                            int(event_start),
                            int(event_end),
                            cal_id or "",
                        )
                    )
            finally:
                con.close()

        rows.sort(key=lambda row: row[3])
        self._items_total = len(rows)

        for db_path, rowid, title, event_start, event_end, cal_id in rows[
            : self._max_events
        ]:
            start_dt = _us_to_datetime(event_start)
            end_dt = _us_to_datetime(event_end)
            cal_name = names.get(cal_id, cal_id or "?")
            is_all_day = end_dt - start_dt >= dt.timedelta(hours=20)
            self._items_synced += 1
            self._last_sync = dt.datetime.now()
            yield Document(
                doc_id=f"thunderbird_calendar:{db_path.name}:{rowid}",
                source="thunderbird_calendar",
                doc_type="calendar_event",
                content=(
                    f"When: {start_dt.isoformat()} - {end_dt.isoformat()}\n"
                    f"Calendar: {cal_name}"
                ),
                title=title,
                timestamp=start_dt,
                metadata={
                    "calendar_id": cal_id,
                    "calendar_name": cal_name,
                    "end": end_dt.isoformat(),
                    "all_day": is_all_day,
                    "database": str(db_path),
                },
            )

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            items_total=self._items_total,
            last_sync=self._last_sync,
        )
