"""Tests for the deep-research-setup CLI command."""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_fake_notes_db(db_path: Path) -> None:
    """Create a minimal Apple Notes SQLite database."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE TEXT,
            ZTITLE1 TEXT,
            ZMODIFICATIONDATE REAL,
            ZIDENTIFIER TEXT,
            ZNOTE INTEGER
        );
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZDATA BLOB,
            ZNOTE INTEGER
        );
    """)
    content = gzip.compress(b"Test note about meetings")
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES "
        "(1, NULL, 'Test Note', 694310400.0, 'n1', 1)"
    )
    conn.execute("INSERT INTO ZICNOTEDATA VALUES (1, ?, 1)", (content,))
    conn.commit()
    conn.close()


def _create_fake_imessage_db(db_path: Path) -> None:
    """Create a minimal iMessage SQLite database."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            chat_identifier TEXT, display_name TEXT
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, text TEXT, handle_id INTEGER,
            date INTEGER, is_from_me INTEGER
        );
    """)
    conn.execute("INSERT INTO handle VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat VALUES (1, '+15551234567', 'Test Chat')")
    conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
    conn.execute(
        "INSERT INTO message VALUES (1, 'Hello from test', 1, 694310400000000000, 0)"
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_detect_local_sources(tmp_path: Path) -> None:
    """Auto-detection finds Apple Notes and iMessage when DBs exist."""
    from openjarvis.cli.deep_research_setup_cmd import detect_local_sources

    notes_db = tmp_path / "NoteStore.sqlite"
    imessage_db = tmp_path / "chat.db"
    _create_fake_notes_db(notes_db)
    _create_fake_imessage_db(imessage_db)

    sources = detect_local_sources(
        notes_db_path=notes_db,
        imessage_db_path=imessage_db,
        obsidian_vault_path=None,
    )
    ids = [s["connector_id"] for s in sources]
    assert "apple_notes" in ids
    assert "imessage" in ids


def test_detect_skips_missing_sources(tmp_path: Path) -> None:
    """Auto-detection skips sources whose files don't exist."""
    from openjarvis.cli.deep_research_setup_cmd import detect_local_sources

    sources = detect_local_sources(
        notes_db_path=tmp_path / "nonexistent.sqlite",
        imessage_db_path=tmp_path / "nonexistent.db",
        obsidian_vault_path=None,
    )
    assert len(sources) == 0


def test_detect_includes_obsidian_when_vault_exists(tmp_path: Path) -> None:
    """Auto-detection includes Obsidian when vault path exists."""
    from openjarvis.cli.deep_research_setup_cmd import detect_local_sources

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Hello")

    sources = detect_local_sources(
        notes_db_path=tmp_path / "nonexistent.sqlite",
        imessage_db_path=tmp_path / "nonexistent.db",
        obsidian_vault_path=vault,
    )
    ids = [s["connector_id"] for s in sources]
    assert "obsidian" in ids


def test_ingest_sources(tmp_path: Path) -> None:
    """ingest_sources connects and ingests documents into KnowledgeStore."""
    from openjarvis.cli.deep_research_setup_cmd import (
        detect_local_sources,
        ingest_sources,
    )
    from openjarvis.connectors.store import KnowledgeStore

    notes_db = tmp_path / "NoteStore.sqlite"
    _create_fake_notes_db(notes_db)

    sources = detect_local_sources(
        notes_db_path=notes_db,
        imessage_db_path=tmp_path / "nonexistent.db",
        obsidian_vault_path=None,
    )

    db_path = tmp_path / "knowledge.db"
    state_db = str(tmp_path / "sync_state.db")
    store = KnowledgeStore(str(db_path))
    total = ingest_sources(sources, store, state_db=state_db)

    assert total > 0
    assert store.count() > 0
    store.close()


def test_detect_token_sources_finds_connected(tmp_path: Path) -> None:
    """detect_token_sources finds sources with valid credential files."""
    from openjarvis.cli.deep_research_setup_cmd import detect_token_sources

    connectors_dir = tmp_path / "connectors"
    connectors_dir.mkdir()
    (connectors_dir / "slack.json").write_text('{"token": "xoxb-test"}')
    (connectors_dir / "notion.json").write_text('{"token": "ntn_test"}')

    sources = detect_token_sources(connectors_dir=connectors_dir)
    ids = [s["connector_id"] for s in sources]
    assert "slack" in ids
    assert "notion" in ids


def test_detect_token_sources_skips_empty(tmp_path: Path) -> None:
    """detect_token_sources skips files with empty or invalid JSON."""
    from openjarvis.cli.deep_research_setup_cmd import detect_token_sources

    connectors_dir = tmp_path / "connectors"
    connectors_dir.mkdir()
    (connectors_dir / "slack.json").write_text("{}")
    (connectors_dir / "notion.json").write_text("invalid json")

    sources = detect_token_sources(connectors_dir=connectors_dir)
    assert len(sources) == 0


def test_detect_token_sources_empty_dir(tmp_path: Path) -> None:
    """detect_token_sources returns empty list when no credential files exist."""
    from openjarvis.cli.deep_research_setup_cmd import detect_token_sources

    connectors_dir = tmp_path / "connectors"
    connectors_dir.mkdir()

    sources = detect_token_sources(connectors_dir=connectors_dir)
    assert len(sources) == 0
