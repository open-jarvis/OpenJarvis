"""Integration tests for the read-only Apple Calendar connector and tools."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from openjarvis.connectors.apple_calendar import (
    AppleCalendarConnector,
    _to_apple_ts,
)
from openjarvis.core.registry import ToolRegistry


def _make_calendar_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE Calendar (ROWID INTEGER PRIMARY KEY, title TEXT, color TEXT);
        CREATE TABLE CalendarItem (
            ROWID INTEGER PRIMARY KEY, summary TEXT, description TEXT,
            start_date REAL, end_date REAL, all_day INTEGER, start_tz TEXT,
            location_id INTEGER, has_attendees INTEGER, last_modified REAL,
            UUID TEXT, calendar_id INTEGER, hidden INTEGER
        );
        CREATE TABLE Location (ROWID INTEGER PRIMARY KEY, title TEXT, address TEXT);
        CREATE TABLE OccurrenceCache (
            event_id INTEGER, calendar_id INTEGER,
            occurrence_start_date REAL, occurrence_end_date REAL
        );
        INSERT INTO Calendar VALUES (1, 'Work', '#123456');
        """
    )
    return conn


def _insert_event(conn, *, rowid, summary, start, end, tz="UTC", uuid=None):
    conn.execute(
        """INSERT INTO CalendarItem VALUES
        (?, ?, '', ?, ?, 0, ?, NULL, 0, ?, ?, 1, 0)""",
        (
            rowid,
            summary,
            _to_apple_ts(start),
            _to_apple_ts(end),
            tz,
            _to_apple_ts(start),
            uuid or f"event-{rowid}",
        ),
    )


def test_missing_database_is_an_empty_sync(tmp_path):
    connector = AppleCalendarConnector(db_path=str(tmp_path / "missing.sqlite"))
    assert list(connector.sync()) == []


def test_timezone_is_converted_before_display(tmp_path):
    db = tmp_path / "calendar.sqlite"
    conn = _make_calendar_db(db)
    now = datetime.now(timezone.utc)
    start = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    _insert_event(
        conn,
        rowid=1,
        summary="Pacific meeting",
        start=start,
        end=start + timedelta(hours=1),
        tz="America/Los_Angeles",
    )
    conn.commit()
    conn.close()

    document = list(AppleCalendarConnector(db_path=str(db)).sync())[0]
    local_start = start.astimezone(ZoneInfo("America/Los_Angeles"))
    assert local_start.strftime("%-I:%M %p") in document.content
    assert document.metadata["start"] == local_start.isoformat()


def test_recurring_master_outside_window_yields_distinct_occurrences(tmp_path):
    db = tmp_path / "calendar.sqlite"
    conn = _make_calendar_db(db)
    now = datetime.now(timezone.utc)
    master = now - timedelta(days=90)
    _insert_event(
        conn,
        rowid=1,
        summary="Weekly standup",
        start=master,
        end=master + timedelta(hours=1),
        uuid="weekly",
    )
    for offset in (1, 3):
        start = now + timedelta(days=offset)
        conn.execute(
            "INSERT INTO OccurrenceCache VALUES (1, 1, ?, ?)",
            (_to_apple_ts(start), _to_apple_ts(start + timedelta(hours=1))),
        )
    conn.commit()
    conn.close()

    documents = list(AppleCalendarConnector(db_path=str(db)).sync())
    assert [document.title for document in documents] == [
        "Weekly standup",
        "Weekly standup",
    ]
    assert len({document.doc_id for document in documents}) == 2


def test_recurring_master_is_not_duplicated_by_same_start_occurrence(tmp_path):
    db = tmp_path / "calendar.sqlite"
    conn = _make_calendar_db(db)
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=1)
    _insert_event(
        conn,
        rowid=1,
        summary="Weekly standup",
        start=start,
        end=start + timedelta(hours=1),
        uuid="weekly",
    )
    conn.execute(
        "INSERT INTO OccurrenceCache VALUES (1, 1, ?, ?)",
        (_to_apple_ts(start), _to_apple_ts(start + timedelta(hours=1))),
    )
    conn.commit()
    conn.close()

    documents = list(AppleCalendarConnector(db_path=str(db)).sync())

    assert [document.title for document in documents] == ["Weekly standup"]
    assert documents[0].doc_id.startswith("apple_calendar:weekly:")


def test_calendar_tools_are_registered_and_executable(tmp_path, monkeypatch):
    import openjarvis.connectors.apple_calendar as calendar_module
    from openjarvis.tools.apple_calendar import (
        CalendarSearchTool,
        CalendarUpcomingTool,
    )

    # The suite's autouse fixture intentionally clears registries after test
    # modules are collected, so restore the two classes explicitly here.  The
    # fresh-process import-order behavior is covered in test_tool_registration.
    if not ToolRegistry.contains("calendar_upcoming"):
        ToolRegistry.register_value("calendar_upcoming", CalendarUpcomingTool)
    if not ToolRegistry.contains("calendar_search"):
        ToolRegistry.register_value("calendar_search", CalendarSearchTool)

    db = tmp_path / "calendar.sqlite"
    conn = _make_calendar_db(db)
    now = datetime.now(timezone.utc)
    _insert_event(
        conn,
        rowid=1,
        summary="Planning session",
        start=now + timedelta(hours=1),
        end=now + timedelta(hours=2),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(calendar_module, "_CAL_DB", db)

    upcoming = ToolRegistry.get("calendar_upcoming")().execute(days_ahead=1)
    search = ToolRegistry.get("calendar_search")().execute(query="Planning")
    assert upcoming.success and "Planning session" in upcoming.content
    assert search.success and "Planning session" in search.content
