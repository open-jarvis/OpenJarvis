"""Tests for iMessage AppleScript daemon."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _create_fake_chat_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            chat_identifier TEXT, display_name TEXT
        );
        CREATE TABLE chat_message_join (
            chat_id INTEGER, message_id INTEGER
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, text TEXT,
            handle_id INTEGER, date INTEGER, is_from_me INTEGER
        );
    """)
    conn.execute("INSERT INTO handle VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat VALUES (1, '+15551234567', 'Test Chat')")
    conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
    conn.execute(
        "INSERT INTO message VALUES (1, 'Hello agent', 1, 700000000000000000, 0)"
    )
    conn.commit()
    conn.close()


def test_poll_new_messages(tmp_path: Path) -> None:
    from openjarvis.channels.imessage_daemon import poll_new_messages

    db_path = tmp_path / "chat.db"
    _create_fake_chat_db(db_path)
    messages = poll_new_messages(
        db_path=str(db_path),
        last_rowid=0,
        chat_identifier="+15551234567",
    )
    assert len(messages) == 1
    assert messages[0]["text"] == "Hello agent"
    assert messages[0]["rowid"] == 1


def test_poll_skips_old_messages(tmp_path: Path) -> None:
    from openjarvis.channels.imessage_daemon import poll_new_messages

    db_path = tmp_path / "chat.db"
    _create_fake_chat_db(db_path)
    messages = poll_new_messages(
        db_path=str(db_path),
        last_rowid=1,
        chat_identifier="+15551234567",
    )
    assert len(messages) == 0


def test_poll_filters_by_chat(tmp_path: Path) -> None:
    from openjarvis.channels.imessage_daemon import poll_new_messages

    db_path = tmp_path / "chat.db"
    _create_fake_chat_db(db_path)
    messages = poll_new_messages(
        db_path=str(db_path),
        last_rowid=0,
        chat_identifier="+15559999999",
    )
    assert len(messages) == 0


def test_poll_skips_own_messages(tmp_path: Path) -> None:
    from openjarvis.channels.imessage_daemon import poll_new_messages

    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            chat_identifier TEXT, display_name TEXT
        );
        CREATE TABLE chat_message_join (
            chat_id INTEGER, message_id INTEGER
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, text TEXT,
            handle_id INTEGER, date INTEGER, is_from_me INTEGER
        );
    """)
    conn.execute("INSERT INTO handle VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat VALUES (1, '+15551234567', 'Test')")
    conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
    conn.execute(
        "INSERT INTO message VALUES (1, 'My own msg', 1, 700000000000000000, 1)"
    )
    conn.commit()
    conn.close()
    messages = poll_new_messages(
        db_path=str(db_path),
        last_rowid=0,
        chat_identifier="+15551234567",
    )
    assert len(messages) == 0
