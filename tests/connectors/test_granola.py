"""Tests for GranolaConnector — Granola meeting notes sync connector.

All Granola API calls are mocked; no network access is required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry

# ---------------------------------------------------------------------------
# Fake API payloads
# ---------------------------------------------------------------------------

_LIST_RESPONSE = {
    "notes": [
        {
            "id": "not_abc12345678901",
            "title": "Sprint Planning",
            "owner": {"name": "Alice", "email": "alice@co.com"},
            "created_at": "2024-03-15T10:00:00Z",
            "updated_at": "2024-03-15T11:00:00Z",
        },
        {
            "id": "not_def12345678901",
            "title": "Design Review",
            "owner": {"name": "Bob", "email": "bob@co.com"},
            "created_at": "2024-03-16T14:00:00Z",
            "updated_at": "2024-03-16T15:00:00Z",
        },
    ],
    "hasMore": False,
    "cursor": None,
}

_NOTE_1 = {
    "id": "not_abc12345678901",
    "title": "Sprint Planning",
    "owner": {"name": "Alice", "email": "alice@co.com"},
    "created_at": "2024-03-15T10:00:00Z",
    "updated_at": "2024-03-15T11:00:00Z",
    "attendees": [
        {"name": "Alice", "email": "alice@co.com"},
        {"name": "Carol", "email": "carol@co.com"},
    ],
    "summary": {"markdown": "Discussed sprint goals and capacity."},
    "transcript": [
        {
            "speaker": "microphone",
            "text": "Let's start with the sprint goals.",
            "start": 0,
            "end": 5,
        },
        {
            "speaker": "speaker",
            "text": "I think we should focus on auth.",
            "start": 5,
            "end": 10,
        },
    ],
    "calendar_event": {
        "event_title": "Sprint Planning",
        "scheduled_start": "2024-03-15T10:00:00Z",
    },
}

_NOTE_2 = {
    "id": "not_def12345678901",
    "title": "Design Review",
    "owner": {"name": "Bob", "email": "bob@co.com"},
    "created_at": "2024-03-16T14:00:00Z",
    "updated_at": "2024-03-16T15:00:00Z",
    "attendees": [{"name": "Bob", "email": "bob@co.com"}],
    "summary": {"markdown": "Reviewed new dashboard mockups."},
    "transcript": [],
    "calendar_event": None,
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def connector(tmp_path: Path):
    """GranolaConnector pointing at a tmp credentials path (no file yet)."""
    from openjarvis.connectors.granola import GranolaConnector  # noqa: PLC0415

    creds_path = str(tmp_path / "granola.json")
    return GranolaConnector(credentials_path=creds_path)


# ---------------------------------------------------------------------------
# Test 1 — not connected without a key or credentials file
# ---------------------------------------------------------------------------


def test_not_connected_without_key(connector) -> None:
    """is_connected() returns False when no API key and no credentials file."""
    assert connector.is_connected() is False


# ---------------------------------------------------------------------------
# Test 2 — connected when api_key is provided directly
# ---------------------------------------------------------------------------


def test_connected_with_key() -> None:
    """is_connected() returns True when an api_key is passed directly."""
    from openjarvis.connectors.granola import GranolaConnector  # noqa: PLC0415

    conn = GranolaConnector(api_key="grl_fake_key")
    assert conn.is_connected() is True


# ---------------------------------------------------------------------------
# Test 3 — auth_url references granola.ai
# ---------------------------------------------------------------------------


def test_auth_url(connector) -> None:
    """auth_url() returns a URL pointing users to the Granola settings page."""
    url = connector.auth_url()
    assert "granola.ai" in url


# ---------------------------------------------------------------------------
# Test 4 — sync yields documents with correct fields (mocked API)
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.granola._granola_api_list_notes")
@patch("openjarvis.connectors.granola._granola_api_get_note")
def test_sync_yields_documents(
    mock_get,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """sync() yields one Document per note with correct metadata."""
    # Write fake credentials so is_connected() returns True
    creds_path = Path(connector._credentials_path)
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text(
        json.dumps({"token": "grl_fake_key"}), encoding="utf-8"
    )

    mock_list.return_value = _LIST_RESPONSE
    mock_get.side_effect = [_NOTE_1, _NOTE_2]

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 2

    # --- Note 1 ---
    doc1 = next(d for d in docs if d.doc_id == "granola:not_abc12345678901")
    assert doc1.source == "granola"
    assert doc1.doc_type == "document"
    assert doc1.title == "Sprint Planning"
    assert doc1.author == "alice@co.com"
    assert "alice@co.com" in doc1.participants
    assert "carol@co.com" in doc1.participants
    assert "Discussed sprint goals and capacity." in doc1.content
    assert "Let's start with the sprint goals." in doc1.content
    assert "I think we should focus on auth." in doc1.content

    # --- Note 2 ---
    doc2 = next(d for d in docs if d.doc_id == "granola:not_def12345678901")
    assert doc2.title == "Design Review"
    assert doc2.author == "bob@co.com"
    assert "Reviewed new dashboard mockups." in doc2.content

    # Verify the API was called correctly
    mock_list.assert_called_once()
    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# Test 5 — _format_note_content produces correct summary + transcript
# ---------------------------------------------------------------------------


def test_format_note_content() -> None:
    """_format_note_content combines summary and transcript into correct markdown."""
    from openjarvis.connectors.granola import _format_note_content  # noqa: PLC0415

    result = _format_note_content(_NOTE_1)

    assert "## Summary" in result
    assert "Discussed sprint goals and capacity." in result
    assert "## Transcript" in result
    assert "**microphone:**" in result
    assert "Let's start with the sprint goals." in result
    assert "**speaker:**" in result
    assert "I think we should focus on auth." in result


# ---------------------------------------------------------------------------
# Test 6 — disconnect removes the credentials file
# ---------------------------------------------------------------------------


def test_disconnect(connector, tmp_path: Path) -> None:
    """disconnect() deletes the credentials file."""
    creds_path = Path(connector._credentials_path)
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text(
        json.dumps({"token": "grl_fake_key"}), encoding="utf-8"
    )
    assert connector.is_connected() is True

    connector.disconnect()

    assert not creds_path.exists()
    assert connector.is_connected() is False


# ---------------------------------------------------------------------------
# Test 7 — mcp_tools returns the two expected tool specs
# ---------------------------------------------------------------------------


def test_mcp_tools(connector) -> None:
    """mcp_tools() returns exactly 2 tools with the required names."""
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert len(tools) == 2
    assert "granola_search_notes" in names
    assert "granola_get_note" in names


# ---------------------------------------------------------------------------
# Test 8 — ConnectorRegistry contains "granola" after import
# ---------------------------------------------------------------------------


def test_registry() -> None:
    """GranolaConnector can be registered and retrieved via ConnectorRegistry."""
    from openjarvis.connectors.granola import GranolaConnector  # noqa: PLC0415

    ConnectorRegistry.register_value("granola", GranolaConnector)
    assert ConnectorRegistry.contains("granola")
    cls = ConnectorRegistry.get("granola")
    assert cls.connector_id == "granola"
