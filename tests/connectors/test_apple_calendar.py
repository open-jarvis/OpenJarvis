"""Integration tests for the read-only Apple Calendar connector and tools."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

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


def _insert_event(
    conn, *, rowid, summary, start, end, tz="UTC", uuid=None, last_modified=None
):
    conn.execute(
        """INSERT INTO CalendarItem VALUES
        (?, ?, '', ?, ?, 0, ?, NULL, 0, ?, ?, 1, 0)""",
        (
            rowid,
            summary,
            _to_apple_ts(start),
            _to_apple_ts(end),
            tz,
            _to_apple_ts(last_modified if last_modified is not None else start),
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

    # No `since`: this test is about occurrence expansion, not about the
    # incremental watermark.  Passing one here only passed while the
    # connector kept upcoming events regardless of it.
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


def test_snapshot_keeps_an_upcoming_event_older_than_the_since_filter(tmp_path):
    """An untouched future event must still reach a caller passing ``since``.

    The morning digest asks every connector for ``since = now - 24h``.  Filtering
    calendar rows on ``last_modified`` dropped any event created earlier than
    that, which is most of them, so the calendar section came back empty while
    the connector itself clearly held the event.
    """
    db = tmp_path / "calendar.sqlite"
    conn = _make_calendar_db(db)
    now = datetime.now(tz=timezone.utc)
    _insert_event(
        conn,
        rowid=1,
        summary="Dentist",
        start=now + timedelta(days=3),
        end=now + timedelta(days=3, hours=1),
        last_modified=now - timedelta(days=30),
    )
    conn.commit()
    conn.close()

    connector = AppleCalendarConnector(db_path=str(db))
    recent = list(
        connector.sync(since=now - timedelta(hours=24), include_upcoming=True)
    )
    assert len(recent) == 1
    assert "Dentist" in str(recent[0].content)
    assert len(recent) == len(list(connector.sync()))


def test_snapshot_still_filters_out_a_stale_past_event(tmp_path):
    """``since`` must keep working for events that have already happened."""
    db = tmp_path / "calendar.sqlite"
    conn = _make_calendar_db(db)
    now = datetime.now(tz=timezone.utc)
    _insert_event(
        conn,
        rowid=1,
        summary="Yesterday standup",
        start=now - timedelta(hours=20),
        end=now - timedelta(hours=19),
        last_modified=now - timedelta(days=30),
    )
    conn.commit()
    conn.close()

    connector = AppleCalendarConnector(db_path=str(db))
    assert (
        list(connector.sync(since=now - timedelta(hours=24), include_upcoming=True))
        == []
    )
    assert len(list(connector.sync())) == 1


@pytest.mark.skipif(
    not hasattr(time, "tzset"), reason="requires process-local TZ support"
)
@pytest.mark.parametrize("local_zone", ["America/Los_Angeles", "Asia/Tokyo"])
def test_since_keeps_current_events_using_calendar_time_semantics(
    tmp_path, monkeypatch, local_zone
):
    import openjarvis.connectors.apple_calendar as calendar_module

    frozen = datetime(2026, 11, 17, 18, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

    monkeypatch.setattr(calendar_module, "datetime", FrozenDateTime)
    # Use a process-local zone and restore it even if assertions fail.
    old_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", local_zone)
    time.tzset()
    try:
        db = tmp_path / "calendar.sqlite"
        conn = _make_calendar_db(db)
        old_edit = frozen - timedelta(days=30)
        wall_now = frozen.astimezone().replace(tzinfo=timezone.utc)
        events = [
            (
                "Ongoing",
                frozen - timedelta(minutes=30),
                frozen + timedelta(minutes=30),
                "UTC",
                False,
            ),
            (
                "Floating future",
                wall_now + timedelta(hours=1),
                wall_now + timedelta(hours=2),
                "_float",
                False,
            ),
            (
                "Floating past",
                wall_now - timedelta(hours=2),
                wall_now - timedelta(hours=1),
                "_float",
                False,
            ),
            (
                "All day today",
                wall_now.replace(hour=0),
                (wall_now + timedelta(days=1)).replace(hour=0),
                "UTC",
                True,
            ),
            (
                "All day yesterday",
                (wall_now - timedelta(days=1)).replace(hour=0),
                wall_now.replace(hour=0),
                "UTC",
                True,
            ),
            (
                "Finished",
                frozen - timedelta(hours=2),
                frozen - timedelta(hours=1),
                "UTC",
                False,
            ),
        ]
        for i, (title, start, end, zone, all_day) in enumerate(events, 1):
            _insert_event(
                conn,
                rowid=i,
                summary=title,
                start=start,
                end=end,
                tz=zone,
                last_modified=old_edit,
            )
            if all_day:
                conn.execute(
                    "UPDATE CalendarItem SET all_day = 1 WHERE ROWID = ?", (i,)
                )
        conn.commit()
        conn.close()
        connector = AppleCalendarConnector(db_path=str(db), days_behind=2)
        titles = {
            doc.title
            for doc in connector.sync(
                since=frozen - timedelta(days=1), include_upcoming=True
            )
        }
        assert titles == {"Ongoing", "Floating future", "All day today"}
    finally:
        if old_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", old_tz)
        time.tzset()


def test_incremental_sync_is_empty_when_nothing_changed(tmp_path):
    """The default must honour the shared ``since`` contract.

    BaseConnector.sync documents that ``since`` returns only items created
    or modified after that time, and SyncEngine passes the last successful
    checkpoint as that watermark.  Keeping upcoming events by default
    broke that for every caller: an untouched event came back on every
    run, so an unchanged second sync re-processed it forever.
    """
    db = tmp_path / "calendar.sqlite"
    conn = _make_calendar_db(db)
    now = datetime.now(tz=timezone.utc)
    _insert_event(
        conn,
        rowid=1,
        summary="Quarterly review",
        start=now + timedelta(days=3),
        end=now + timedelta(days=3, hours=1),
        last_modified=now - timedelta(days=30),
    )
    conn.commit()
    conn.close()

    connector = AppleCalendarConnector(db_path=str(db))

    first = list(connector.sync())
    assert len(first) == 1

    checkpoint = datetime.now(tz=timezone.utc)
    assert list(connector.sync(since=checkpoint)) == []


def test_digest_collection_keeps_an_old_created_upcoming_event(tmp_path):
    """The briefing must still get tomorrow's meeting.

    The connector no longer bends ``since`` on its own, so this asserts
    that the digest asks for the snapshot explicitly -- the behaviour the
    briefing actually depends on, at the layer that now owns it.
    """
    from openjarvis.core.registry import ConnectorRegistry
    from openjarvis.tools.digest_collect import DigestCollectTool

    db = tmp_path / "calendar.sqlite"
    conn = _make_calendar_db(db)
    now = datetime.now(tz=timezone.utc)
    _insert_event(
        conn,
        rowid=1,
        summary="Dentist",
        start=now + timedelta(days=3),
        end=now + timedelta(days=3, hours=1),
        last_modified=now - timedelta(days=30),
    )
    conn.commit()
    conn.close()

    def factory():
        return AppleCalendarConnector(db_path=str(db))

    import unittest.mock as mock

    with (
        mock.patch.object(ConnectorRegistry, "contains", return_value=True),
        mock.patch.object(ConnectorRegistry, "get", return_value=factory),
    ):
        result = DigestCollectTool().execute(sources=["apple_calendar"])

    assert "Dentist" in result.content
