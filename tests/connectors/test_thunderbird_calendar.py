"""Tests for the Thunderbird calendar connector."""

from __future__ import annotations

import datetime as dt
import sqlite3

from openjarvis.core.registry import ConnectorRegistry


def _to_us(value: dt.datetime) -> int:
    return int(value.timestamp() * 1_000_000)


def _make_profile(tmp_path):
    profile = tmp_path / "abc.default-release"
    cal_dir = profile / "calendar-data"
    cal_dir.mkdir(parents=True)
    (profile / "prefs.js").write_text(
        'user_pref("calendar.registry.cal-1.name", "Privat");\n',
        encoding="utf-8",
    )
    db_path = cal_dir / "cache.sqlite"
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE cal_events (
                title TEXT,
                event_start INTEGER,
                event_end INTEGER,
                cal_id TEXT
            )
            """
        )
        start = dt.datetime.now() + dt.timedelta(days=1)
        end = start + dt.timedelta(hours=1)
        con.execute(
            "INSERT INTO cal_events VALUES (?, ?, ?, ?)",
            ("Dr. Termin", _to_us(start), _to_us(end), "cal-1"),
        )
        con.commit()
    finally:
        con.close()
    return tmp_path


def test_thunderbird_calendar_registered():
    from openjarvis.connectors.thunderbird_calendar import ThunderbirdCalendarConnector

    ConnectorRegistry.register_value(
        "thunderbird_calendar",
        ThunderbirdCalendarConnector,
    )
    assert ConnectorRegistry.contains("thunderbird_calendar")


def test_thunderbird_calendar_sync_yields_events(tmp_path):
    from openjarvis.connectors.thunderbird_calendar import ThunderbirdCalendarConnector

    profile_dir = _make_profile(tmp_path)
    connector = ThunderbirdCalendarConnector(profile_dir=str(profile_dir))

    docs = list(connector.sync())

    assert connector.is_connected() is True
    assert len(docs) == 1
    assert docs[0].source == "thunderbird_calendar"
    assert docs[0].title == "Dr. Termin"
    assert docs[0].metadata["calendar_name"] == "Privat"
    assert "Calendar: Privat" in docs[0].content
