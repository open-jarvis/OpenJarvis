"""Tests for GContactsConnector — OAuth-authenticated Google Contacts sync connector.

All People API calls are mocked; no network access is required.
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

_CONNECTIONS_RESPONSE = {
    "connections": [
        {
            "resourceName": "people/c1",
            "names": [{"displayName": "Alice Smith"}],
            "emailAddresses": [{"value": "alice@co.com"}],
            "phoneNumbers": [{"value": "+1-555-0100"}],
            "organizations": [{"name": "Acme Corp", "title": "VP Engineering"}],
        },
        {
            "resourceName": "people/c2",
            "names": [{"displayName": "Bob Jones"}],
            "emailAddresses": [{"value": "bob@co.com"}],
            "phoneNumbers": [],
            "organizations": [{"name": "Acme Corp", "title": "Designer"}],
        },
    ],
    "nextPageToken": None,
}


def _make_credentials(tmp_path: Path) -> Path:
    """Write a minimal fake credentials file and return its path."""
    creds = tmp_path / "gcontacts.json"
    creds.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")
    return creds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def connector(tmp_path: Path):
    """GContactsConnector pointing at a tmp credentials path (no file yet)."""
    from openjarvis.connectors.gcontacts import GContactsConnector  # noqa: PLC0415

    creds_path = str(tmp_path / "gcontacts.json")
    return GContactsConnector(credentials_path=creds_path)


# ---------------------------------------------------------------------------
# Test 1 — not connected without a credentials file
# ---------------------------------------------------------------------------


def test_not_connected(connector) -> None:
    """is_connected() returns False when no credentials file exists."""
    assert connector.is_connected() is False


# ---------------------------------------------------------------------------
# Test 2 — auth_url contains contacts.readonly scope
# ---------------------------------------------------------------------------


def test_auth_url(connector) -> None:
    """auth_url() returns the credentials page when no client_id is stored."""
    url = connector.auth_url()
    assert isinstance(url, str)
    # Without a stored client_id, points to the Cloud Console credentials page
    assert url == "https://console.cloud.google.com/apis/credentials"


# ---------------------------------------------------------------------------
# Test 3 — sync yields contacts with correct fields (mocked API)
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.gcontacts._gcontacts_api_list")
def test_sync_yields_contacts(
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """sync() yields one Document per contact with correct metadata."""
    # Set up fake credentials so is_connected() returns True
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    # Configure mock
    mock_list.return_value = _CONNECTIONS_RESPONSE

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 2

    # --- Contact 1: Alice ---
    doc1 = next(d for d in docs if d.doc_id == "gcontacts:people/c1")
    assert doc1.source == "gcontacts"
    assert doc1.doc_type == "contact"
    assert doc1.title == "Alice Smith"
    assert doc1.author == "alice@co.com"
    assert "alice@co.com" in doc1.content
    assert "Acme Corp" in doc1.content

    # --- Contact 2: Bob ---
    doc2 = next(d for d in docs if d.doc_id == "gcontacts:people/c2")
    assert doc2.doc_type == "contact"
    assert doc2.title == "Bob Jones"
    assert doc2.author == "bob@co.com"
    assert "bob@co.com" in doc2.content
    assert "Acme Corp" in doc2.content

    # Verify the API was called once (single page, no nextPageToken)
    mock_list.assert_called_once()


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
# Test 5 — mcp_tools returns the two expected tool specs
# ---------------------------------------------------------------------------


def test_mcp_tools(connector) -> None:
    """mcp_tools() returns exactly 2 tools with the required names."""
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert len(tools) == 2
    assert "contacts_find" in names
    assert "contacts_get_info" in names


# ---------------------------------------------------------------------------
# Test 6 — ConnectorRegistry contains "gcontacts" after import
# ---------------------------------------------------------------------------


def test_registry() -> None:
    """GContactsConnector can be registered and retrieved via ConnectorRegistry."""
    from openjarvis.connectors.gcontacts import GContactsConnector  # noqa: PLC0415

    # The registry is cleared before each test by the autouse conftest fixture,
    # so we imperatively re-register here (same pattern as test_gcalendar.py).
    ConnectorRegistry.register_value("gcontacts", GContactsConnector)
    assert ConnectorRegistry.contains("gcontacts")
    cls = ConnectorRegistry.get("gcontacts")
    assert cls.connector_id == "gcontacts"
