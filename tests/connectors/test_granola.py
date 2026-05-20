"""Tests for GranolaConnector — Granola meeting notes sync connector.

All Granola API calls are mocked; no network access is required.
"""

from __future__ import annotations

import json
import logging
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

_NOTE_1_WEB_URL = "https://notes.granola.ai/d/e98b5d85-ff57-46ac-a0ce-849fc68d086f"

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
    "web_url": _NOTE_1_WEB_URL,
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
    # Some notes have no associated web_url (e.g. quick notes without a
    # calendar event). The connector must tolerate the absence.
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
    creds_path.write_text(json.dumps({"token": "grl_fake_key"}), encoding="utf-8")

    mock_list.return_value = _LIST_RESPONSE
    mock_get.side_effect = [_NOTE_1, _NOTE_2]

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 2

    # --- Note 1 (has calendar_event + attendees) ---
    doc1 = next(d for d in docs if d.doc_id == "granola:not_abc12345678901")
    assert doc1.source == "granola"
    assert doc1.doc_type == "document"
    assert doc1.title == "Sprint Planning"
    assert doc1.author == "alice@co.com"
    # Participants are lowercased emails (cross-source matching).
    assert doc1.participants == ["alice@co.com", "carol@co.com"]
    # participants_raw keeps the human-readable names.
    assert doc1.participants_raw == ["Alice", "Carol"]
    # channel is derived from calendar_event.event_title when present.
    assert doc1.channel == "Sprint Planning"
    # thread_id namespaces transcript chunks under one note.
    assert doc1.thread_id == "not_abc12345678901"
    # The connector persists the API-provided web_url verbatim. The web URL
    # uses a different UUID than the API note_id so this is the *only* way
    # to get a working deep-link to the note.
    assert doc1.url == _NOTE_1_WEB_URL
    assert "Discussed sprint goals and capacity." in doc1.content
    assert "Let's start with the sprint goals." in doc1.content
    assert "I think we should focus on auth." in doc1.content

    # --- Note 2 (no calendar_event → channel falls back to "meeting") ---
    doc2 = next(d for d in docs if d.doc_id == "granola:not_def12345678901")
    assert doc2.title == "Design Review"
    assert doc2.author == "bob@co.com"
    assert doc2.participants == ["bob@co.com"]
    assert doc2.participants_raw == ["Bob"]
    assert doc2.channel == "meeting"
    assert doc2.thread_id == "not_def12345678901"
    # Note 2's fixture has no web_url; the connector tolerates the absence.
    assert doc2.url is None
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
    creds_path.write_text(json.dumps({"token": "grl_fake_key"}), encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Test 9 — sync logs the per-page and total note counts at INFO
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.granola._granola_api_list_notes")
@patch("openjarvis.connectors.granola._granola_api_get_note")
def test_sync_logs_note_count(
    mock_get,
    mock_list,
    connector,
    caplog,
) -> None:
    """sync() emits 'Found N notes' and 'Sync complete' INFO lines.

    Matches the Slack connector's per-sync logging shape so operators can
    grep server logs for sync activity.
    """
    creds_path = Path(connector._credentials_path)
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text(json.dumps({"token": "grl_fake"}), encoding="utf-8")

    mock_list.return_value = _LIST_RESPONSE
    mock_get.side_effect = [_NOTE_1, _NOTE_2]

    with caplog.at_level(logging.INFO, logger="openjarvis.connectors.granola"):
        list(connector.sync())

    text = caplog.text
    assert "Granola: Found 2 notes on this page" in text
    assert "Granola: Sync complete, 2 notes total" in text


# ---------------------------------------------------------------------------
# Test 10 — end-to-end: connector → pipeline → KnowledgeStore → HybridSearch
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.granola._granola_api_list_notes")
@patch("openjarvis.connectors.granola._granola_api_get_note")
def test_end_to_end_ingest_and_search(
    mock_get,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """Synced Granola notes are searchable via HybridSearch with v1 fields.

    Lexical-only path (no embedder) so this stays a pure unit test — no
    Ollama daemon needed. Confirms the v1 contract end-to-end: source,
    namespaced thread_id, channel, participants, and that the research-loop
    URL builder reconstructs the Granola web deep-link from the doc_id.
    """
    from openjarvis.connectors.hybrid_search import HybridSearch  # noqa: PLC0415
    from openjarvis.connectors.pipeline import IngestionPipeline  # noqa: PLC0415
    from openjarvis.connectors.store import KnowledgeStore  # noqa: PLC0415

    creds_path = Path(connector._credentials_path)
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text(json.dumps({"token": "grl_fake"}), encoding="utf-8")

    mock_list.return_value = _LIST_RESPONSE
    mock_get.side_effect = [_NOTE_1, _NOTE_2]

    store = KnowledgeStore(db_path=tmp_path / "granola_e2e.db")
    pipeline = IngestionPipeline(store)
    chunks_stored = pipeline.ingest(connector.sync())

    # Two notes; the chunker may split summary/transcript sections, so
    # we just assert at least one chunk per note made it in.
    assert chunks_stored >= 2

    hybrid = HybridSearch(store)
    hits = hybrid.search("sprint goals", limit=5)
    assert len(hits) >= 1

    target = next(
        (h for h in hits if "Sprint Planning" in h.title),
        None,
    )
    assert target is not None
    assert target.source == "granola"
    assert target.title == "Sprint Planning"
    # thread_id is namespaced by the pipeline.
    assert target.thread_id == "granola:not_abc12345678901"
    assert target.participants == ["alice@co.com", "carol@co.com"]
    assert target.document_id == "granola:not_abc12345678901"
    # The connector-supplied web_url survives ingest → store → hit and is
    # what the research-loop client sees as the citation URL. The doc_id-
    # based reconstruction can't recover this because the web UUID is
    # different from the API note_id.
    assert target.url == _NOTE_1_WEB_URL

    from openjarvis.agents.research_loop import (  # noqa: PLC0415
        _hit_url,
        build_sources_for_client,
    )

    # _hit_url alone cannot reconstruct a Granola URL — there is no UUID
    # in the doc_id. It must return empty, leaving the URL to be sourced
    # from the stored ``SearchHit.url``.
    assert _hit_url(target.source, target.document_id) == ""

    # And the client-facing sources list does end up with the stored URL.
    client_sources = build_sources_for_client([target])
    assert client_sources[0]["url"] == _NOTE_1_WEB_URL
