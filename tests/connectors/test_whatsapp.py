"""Tests for the WhatsApp chat export connector."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openjarvis.connectors.whatsapp import WhatsAppConnector
from openjarvis.core.registry import ConnectorRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHAT_ALICE = """\
1/15/24, 10:30 AM - Alice: Hey, how are you?
1/15/24, 10:31 AM - Bob: Good thanks! Working on the project.
1/15/24, 10:32 AM - Alice: Great, let's discuss later.
"""

_CHAT_WORK = """\
3/20/24, 9:00 AM - Carol: Morning everyone!
3/20/24, 9:01 AM - Dave: Good morning, ready for the standup?
3/20/24, 9:02 AM - Carol: Yes, joining in 2 minutes.
3/20/24, 9:05 AM - Eve: Running a bit late, sorry.
"""

_CHAT_OLD = """\
6/10/23, 3:00 PM - Frank: This is an old message.
6/10/23, 3:01 PM - Grace: Indeed, from last year.
"""


def _write_chat(directory: Path, filename: str, content: str) -> Path:
    """Write a WhatsApp export .txt file and return its path."""
    p = directory / filename
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Test 1: Parse a single export file → one Document with correct fields
# ---------------------------------------------------------------------------


def test_parse_single_export_file(tmp_path: Path) -> None:
    """A single .txt file is parsed into one Document with correct metadata."""
    _write_chat(tmp_path, "WhatsApp Chat with Alice.txt", _CHAT_ALICE)

    conn = WhatsAppConnector(export_path=str(tmp_path))
    docs = list(conn.sync())

    assert len(docs) == 1
    doc = docs[0]
    assert doc.source == "whatsapp"
    assert doc.doc_type == "message"
    assert doc.title == "WhatsApp Chat with Alice"
    # Both participants should be detected
    assert "Alice" in doc.participants
    assert "Bob" in doc.participants
    # Content should contain the messages
    assert "how are you" in doc.content
    assert "Working on the project" in doc.content


# ---------------------------------------------------------------------------
# Test 2: Multiple export files → one Document per file
# ---------------------------------------------------------------------------


def test_multiple_export_files(tmp_path: Path) -> None:
    """Multiple .txt files each produce one Document."""
    _write_chat(tmp_path, "WhatsApp Chat with Alice.txt", _CHAT_ALICE)
    _write_chat(tmp_path, "Work Group.txt", _CHAT_WORK)

    conn = WhatsAppConnector(export_path=str(tmp_path))
    docs = list(conn.sync())

    assert len(docs) == 2
    titles = {d.title for d in docs}
    assert "WhatsApp Chat with Alice" in titles
    assert "Work Group" in titles

    # Work group chat has 4 participants
    work_doc = next(d for d in docs if d.title == "Work Group")
    assert set(work_doc.participants) == {"Carol", "Dave", "Eve"}


# ---------------------------------------------------------------------------
# Test 3: since filtering — skip chats whose latest message is before cutoff
# ---------------------------------------------------------------------------


def test_since_filtering_skips_old_chats(tmp_path: Path) -> None:
    """Chats where the most recent message is before `since` are skipped."""
    _write_chat(tmp_path, "WhatsApp Chat with Alice.txt", _CHAT_ALICE)  # Jan 2024
    _write_chat(tmp_path, "Old Chat.txt", _CHAT_OLD)  # Jun 2023

    # Only include chats with messages after Feb 2024
    cutoff = datetime(2024, 2, 1, tzinfo=timezone.utc)

    conn = WhatsAppConnector(export_path=str(tmp_path))
    docs = list(conn.sync(since=cutoff))

    # Old chat (Jun 2023) should be excluded; Alice chat (Jan 2024) also before Feb 2024
    # Both are before Feb 2024 cutoff
    assert len(docs) == 0


def test_since_filtering_includes_recent_chats(tmp_path: Path) -> None:
    """Chats with messages on or after `since` are included."""
    _write_chat(tmp_path, "Work Group.txt", _CHAT_WORK)  # Mar 2024
    _write_chat(tmp_path, "Old Chat.txt", _CHAT_OLD)  # Jun 2023

    # Cutoff between old and work chat
    cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)

    conn = WhatsAppConnector(export_path=str(tmp_path))
    docs = list(conn.sync(since=cutoff))

    assert len(docs) == 1
    assert docs[0].title == "Work Group"


# ---------------------------------------------------------------------------
# Test 4: is_connected returns False for missing / empty directory
# ---------------------------------------------------------------------------


def test_is_connected_missing_directory() -> None:
    """is_connected() returns False when export_path does not exist."""
    conn = WhatsAppConnector(export_path="/nonexistent/path/to/exports")
    assert not conn.is_connected()


def test_is_connected_empty_directory(tmp_path: Path) -> None:
    """is_connected() returns False when export directory has no .txt files."""
    conn = WhatsAppConnector(export_path=str(tmp_path))
    assert not conn.is_connected()


def test_is_connected_with_txt_files(tmp_path: Path) -> None:
    """is_connected() returns True when at least one .txt file exists."""
    _write_chat(tmp_path, "Chat.txt", _CHAT_ALICE)
    conn = WhatsAppConnector(export_path=str(tmp_path))
    assert conn.is_connected()


# ---------------------------------------------------------------------------
# Test 5: sync with no export_path → empty
# ---------------------------------------------------------------------------


def test_sync_no_export_path() -> None:
    """sync() yields nothing when no export_path is set."""
    conn = WhatsAppConnector()
    docs = list(conn.sync())
    assert docs == []


# ---------------------------------------------------------------------------
# Test 6: sync_status reflects items synced
# ---------------------------------------------------------------------------


def test_sync_status_after_sync(tmp_path: Path) -> None:
    """sync_status() reports items_synced and items_total correctly."""
    _write_chat(tmp_path, "Alice.txt", _CHAT_ALICE)
    _write_chat(tmp_path, "Work.txt", _CHAT_WORK)

    conn = WhatsAppConnector(export_path=str(tmp_path))
    docs = list(conn.sync())

    status = conn.sync_status()
    assert status.items_total == 2
    assert status.items_synced == len(docs)
    assert status.last_sync is not None


# ---------------------------------------------------------------------------
# Test 7: ConnectorRegistry contains "whatsapp"
# ---------------------------------------------------------------------------


def test_registry_registration() -> None:
    """WhatsAppConnector is registered under 'whatsapp' in ConnectorRegistry."""
    from openjarvis.connectors.whatsapp import WhatsAppConnector  # noqa: PLC0415

    ConnectorRegistry.register_value("whatsapp", WhatsAppConnector)
    assert ConnectorRegistry.contains("whatsapp")
    cls = ConnectorRegistry.get("whatsapp")
    assert cls.connector_id == "whatsapp"
    assert cls.display_name == "WhatsApp"
    assert cls.auth_type == "filesystem"
