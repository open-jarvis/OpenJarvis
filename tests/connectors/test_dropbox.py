"""Tests for DropboxConnector — OAuth-authenticated Dropbox sync connector.

All Dropbox API calls are mocked; no network access is required.
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

_LIST_RESPONSE = {
    "entries": [
        {
            "name": "notes.md",
            "path_lower": "/notes.md",
            ".tag": "file",
            "server_modified": "2024-03-15T10:00:00Z",
            "size": 1024,
        },
        {
            "name": "report.txt",
            "path_lower": "/docs/report.txt",
            ".tag": "file",
            "server_modified": "2024-03-16T11:00:00Z",
            "size": 2048,
        },
    ],
    "has_more": False,
    "cursor": "cursor-abc123",
}

_DOWNLOAD_RESPONSE = "# My Notes\n\nSome content here."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def connector(tmp_path: Path):
    """DropboxConnector pointing at a tmp credentials path (no file yet)."""
    from openjarvis.connectors.dropbox import DropboxConnector  # noqa: PLC0415

    creds_path = str(tmp_path / "dropbox.json")
    return DropboxConnector(credentials_path=creds_path)


# ---------------------------------------------------------------------------
# Test 1 — not connected without a credentials file
# ---------------------------------------------------------------------------


def test_not_connected(connector) -> None:
    """is_connected() returns False when no credentials file exists."""
    assert connector.is_connected() is False


# ---------------------------------------------------------------------------
# Test 2 — auth_url contains dropbox
# ---------------------------------------------------------------------------


def test_auth_url(connector) -> None:
    """auth_url() returns a Dropbox OAuth URL."""
    url = connector.auth_url()
    assert isinstance(url, str)
    assert "dropbox" in url.lower()


# ---------------------------------------------------------------------------
# Test 3 — sync yields documents with correct fields (mocked API)
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.dropbox._dropbox_api_list_folder")
@patch("openjarvis.connectors.dropbox._dropbox_api_download")
def test_sync_yields_documents(
    mock_download,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """sync() yields one Document per file with correct metadata."""
    # Set up fake credentials so is_connected() returns True
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    # Configure mocks
    mock_list.return_value = _LIST_RESPONSE
    mock_download.return_value = _DOWNLOAD_RESPONSE

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 2

    # --- Document 1 (notes.md) ---
    doc1 = next(d for d in docs if d.doc_id == "dropbox:/notes.md")
    assert doc1.source == "dropbox"
    assert doc1.doc_type == "document"
    assert doc1.title == "notes.md"
    assert doc1.content == _DOWNLOAD_RESPONSE

    # --- Document 2 (report.txt) ---
    doc2 = next(d for d in docs if d.doc_id == "dropbox:/docs/report.txt")
    assert doc2.title == "report.txt"
    assert doc2.content == _DOWNLOAD_RESPONSE

    # Verify the API was called correctly
    mock_list.assert_called_once()
    assert mock_download.call_count == 2


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
    assert "dropbox_search_files" in names
    assert "dropbox_get_file" in names
    assert "dropbox_list_recent" in names


# ---------------------------------------------------------------------------
# Test 6 — ConnectorRegistry contains "dropbox" after import
# ---------------------------------------------------------------------------


def test_registry() -> None:
    """DropboxConnector can be registered and retrieved via ConnectorRegistry."""
    from openjarvis.connectors.dropbox import DropboxConnector  # noqa: PLC0415

    ConnectorRegistry.register_value("dropbox", DropboxConnector)
    assert ConnectorRegistry.contains("dropbox")
    cls = ConnectorRegistry.get("dropbox")
    assert cls.connector_id == "dropbox"
