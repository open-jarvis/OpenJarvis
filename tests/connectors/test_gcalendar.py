"""Tests for GCalendarConnector — OAuth-authenticated Google Calendar sync connector.

All Calendar API calls are mocked; no network access is required.
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
# Helpers — fake API payloads
# ---------------------------------------------------------------------------

_CALENDARS_RESPONSE = {"items": [{"id": "primary", "summary": "My Calendar"}]}

_EVENTS_RESPONSE = {
    "items": [
        {
            "id": "evt1",
            "summary": "Sprint Planning",
            "description": "Review sprint goals and capacity.",
            "start": {"dateTime": "2024-03-15T10:00:00Z"},
            "end": {"dateTime": "2024-03-15T11:00:00Z"},
            "attendees": [
                {"email": "alice@co.com", "displayName": "Alice"},
                {"email": "bob@co.com", "displayName": "Bob"},
            ],
            "location": "Room 3",
            "organizer": {"email": "alice@co.com", "displayName": "Alice"},
            "htmlLink": "https://calendar.google.com/event?eid=evt1",
        }
    ],
    "nextPageToken": None,
}


def _make_credentials(tmp_path: Path) -> Path:
    """Write a minimal fake credentials file and return its path."""
    creds = tmp_path / "gcalendar.json"
    creds.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")
    return creds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def connector(tmp_path: Path):
    """GCalendarConnector pointing at a tmp credentials path (no file yet)."""
    from unittest.mock import patch

    from openjarvis.connectors.gcalendar import GCalendarConnector  # noqa: PLC0415

    creds_path = str(tmp_path / "gcalendar.json")
    with patch(
        "openjarvis.connectors.oauth._SHARED_GOOGLE_CREDENTIALS_PATH",
        str(tmp_path / "google_shared.json"),
    ):
        yield GCalendarConnector(credentials_path=creds_path)


# ---------------------------------------------------------------------------
# Test 1 — not connected without a credentials file
# ---------------------------------------------------------------------------


def test_not_connected(connector) -> None:
    """is_connected() returns False when no credentials file exists."""
    assert connector.is_connected() is False


# ---------------------------------------------------------------------------
# Test 2 — auth_url contains calendar.readonly scope
# ---------------------------------------------------------------------------


def test_auth_url(connector) -> None:
    """auth_url() returns the credentials page when no client_id is stored."""
    url = connector.auth_url()
    assert isinstance(url, str)
    # Without a stored client_id, points to the Cloud Console credentials page
    assert url == "https://console.cloud.google.com/apis/credentials"


# ---------------------------------------------------------------------------
# Test 3 — sync yields events with correct fields (mocked API)
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.gcalendar._gcal_api_calendars_list")
@patch("openjarvis.connectors.gcalendar._gcal_api_events_list")
def test_sync_yields_events(
    mock_events,
    mock_calendars,
    connector,
    tmp_path: Path,
) -> None:
    """sync() yields one Document per event with correct metadata."""
    # Set up fake credentials so is_connected() returns True
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    # Configure mocks
    mock_calendars.return_value = _CALENDARS_RESPONSE
    mock_events.return_value = _EVENTS_RESPONSE

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 1

    doc = docs[0]
    assert doc.doc_id == "gcalendar:evt1"
    assert doc.source == "gcalendar"
    assert doc.doc_type == "event"
    assert doc.title == "Sprint Planning"
    assert doc.author == "alice@co.com"
    assert "alice@co.com" in doc.participants
    assert "bob@co.com" in doc.participants
    assert "Room 3" in doc.content
    assert doc.url == "https://calendar.google.com/event?eid=evt1"

    # Verify the API was called correctly
    mock_calendars.assert_called_once()
    mock_events.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4 — disconnect removes the credentials file
# ---------------------------------------------------------------------------


def test_disconnect(connector, tmp_path: Path) -> None:
    """disconnect() deletes the credentials file."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")
    assert connector.is_connected() is True

    connector.disconnect()

    assert not creds_path.exists()
    assert connector.is_connected() is False


# ---------------------------------------------------------------------------
# Test 5 — mcp_tools returns the three expected tool specs
# ---------------------------------------------------------------------------


def test_mcp_tools(connector) -> None:
    """mcp_tools() returns exactly 3 tools with the required names."""
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert len(tools) == 3
    assert "calendar_get_events_today" in names
    assert "calendar_search_events" in names
    assert "calendar_next_meeting" in names


# ---------------------------------------------------------------------------
# Test 6 — ConnectorRegistry contains "gcalendar" after import
# ---------------------------------------------------------------------------


def test_registry() -> None:
    """GCalendarConnector can be registered and retrieved via ConnectorRegistry."""
    from openjarvis.connectors.gcalendar import GCalendarConnector  # noqa: PLC0415

    # The registry is cleared before each test by the autouse conftest fixture,
    # so we imperatively re-register here (same pattern as test_gmail.py).
    ConnectorRegistry.register_value("gcalendar", GCalendarConnector)
    assert ConnectorRegistry.contains("gcalendar")
    cls = ConnectorRegistry.get("gcalendar")
    assert cls.connector_id == "gcalendar"
