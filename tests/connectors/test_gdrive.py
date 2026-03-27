"""Tests for GDriveConnector — OAuth-authenticated Google Drive sync connector.

All Drive API calls are mocked; no network access is required.
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

_FILES_LIST_RESPONSE = {
    "files": [
        {
            "id": "doc1",
            "name": "Q3 Roadmap",
            "mimeType": "application/vnd.google-apps.document",
            "modifiedTime": "2024-03-15T10:00:00.000Z",
            "owners": [{"emailAddress": "alice@co.com", "displayName": "Alice"}],
            "webViewLink": "https://docs.google.com/document/d/doc1/edit",
        },
        {
            "id": "sheet1",
            "name": "Budget 2024",
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "modifiedTime": "2024-03-16T11:00:00.000Z",
            "owners": [{"emailAddress": "bob@co.com", "displayName": "Bob"}],
            "webViewLink": "https://docs.google.com/spreadsheets/d/sheet1/edit",
        },
    ],
    "nextPageToken": None,
}

_EXPORT_RESPONSE = "# Q3 Roadmap\n\nThis is the roadmap content."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def connector(tmp_path: Path):
    """GDriveConnector pointing at a tmp credentials path (no file yet)."""
    from openjarvis.connectors.gdrive import GDriveConnector  # noqa: PLC0415

    creds_path = str(tmp_path / "gdrive.json")
    return GDriveConnector(credentials_path=creds_path)


# ---------------------------------------------------------------------------
# Test 1 — not connected without a credentials file
# ---------------------------------------------------------------------------


def test_not_connected(connector) -> None:
    """is_connected() returns False when no credentials file exists."""
    assert connector.is_connected() is False


# ---------------------------------------------------------------------------
# Test 2 — auth_url contains drive.readonly scope
# ---------------------------------------------------------------------------


def test_auth_url(connector) -> None:
    """auth_url() returns a Google OAuth URL with drive.readonly scope."""
    url = connector.auth_url()
    assert isinstance(url, str)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "drive.readonly" in url


# ---------------------------------------------------------------------------
# Test 3 — sync yields documents with correct fields (mocked API)
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.gdrive._gdrive_api_list_files")
@patch("openjarvis.connectors.gdrive._gdrive_api_export")
def test_sync_yields_documents(
    mock_export,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """sync() yields one Document per file with correct metadata."""
    # Set up fake credentials so is_connected() returns True
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    # Configure mocks
    mock_list.return_value = _FILES_LIST_RESPONSE
    mock_export.return_value = _EXPORT_RESPONSE

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 2

    # --- Document 1 (Google Doc) ---
    doc1 = next(d for d in docs if d.doc_id == "gdrive:doc1")
    assert doc1.source == "gdrive"
    assert doc1.doc_type == "document"
    assert doc1.title == "Q3 Roadmap"
    assert doc1.author == "Alice"
    assert doc1.url == "https://docs.google.com/document/d/doc1/edit"
    assert doc1.content == _EXPORT_RESPONSE

    # --- Document 2 (Google Sheet) ---
    doc2 = next(d for d in docs if d.doc_id == "gdrive:sheet1")
    assert doc2.title == "Budget 2024"
    assert doc2.author == "Bob"
    assert doc2.url == "https://docs.google.com/spreadsheets/d/sheet1/edit"
    assert doc2.content == _EXPORT_RESPONSE

    # Verify the API was called correctly
    mock_list.assert_called_once()
    assert mock_export.call_count == 2


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
    assert "gdrive_search_files" in names
    assert "gdrive_get_document" in names
    assert "gdrive_list_recent" in names


# ---------------------------------------------------------------------------
# Test 6 — ConnectorRegistry contains "gdrive" after import
# ---------------------------------------------------------------------------


def test_registry() -> None:
    """GDriveConnector can be registered and retrieved via ConnectorRegistry."""
    from openjarvis.connectors.gdrive import GDriveConnector  # noqa: PLC0415

    # The registry is cleared before each test by the autouse conftest fixture,
    # so we imperatively re-register here (same pattern as test_gmail.py).
    ConnectorRegistry.register_value("gdrive", GDriveConnector)
    assert ConnectorRegistry.contains("gdrive")
    cls = ConnectorRegistry.get("gdrive")
    assert cls.connector_id == "gdrive"
