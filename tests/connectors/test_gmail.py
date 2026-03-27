"""Tests for GmailConnector — OAuth-authenticated Gmail sync connector.

All Gmail API calls are mocked; no network access is required.
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

# base64url("Hello world") == "SGVsbG8gd29ybGQ="
# base64url("Budget reply") == "QnVkZ2V0IHJlcGx5"

_MSG1 = {
    "id": "msg1",
    "threadId": "thread1",
    "labelIds": ["INBOX"],
    "payload": {
        "mimeType": "text/plain",
        "headers": [
            {"name": "From", "value": "alice@example.com"},
            {"name": "To", "value": "me@example.com"},
            {"name": "Subject", "value": "Q3 Planning"},
            {"name": "Date", "value": "Mon, 01 Jan 2024 10:00:00 +0000"},
        ],
        "body": {"data": "SGVsbG8gd29ybGQ="},
    },
}

_MSG2 = {
    "id": "msg2",
    "threadId": "thread2",
    "labelIds": ["INBOX"],
    "payload": {
        "mimeType": "text/plain",
        "headers": [
            {"name": "From", "value": "bob@example.com"},
            {"name": "To", "value": "me@example.com"},
            {"name": "Subject", "value": "Re: Budget"},
            {"name": "Date", "value": "Tue, 02 Jan 2024 12:00:00 +0000"},
        ],
        "body": {"data": "QnVkZ2V0IHJlcGx5"},
    },
}

_LIST_RESPONSE = {
    "messages": [{"id": "msg1"}, {"id": "msg2"}],
    # No nextPageToken → single page
}


def _make_credentials(tmp_path: Path) -> Path:
    """Write a minimal fake credentials file and return its path."""
    creds = tmp_path / "gmail.json"
    creds.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")
    return creds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def connector(tmp_path: Path):
    """GmailConnector pointing at a tmp credentials path (no file yet)."""
    from openjarvis.connectors.gmail import GmailConnector  # noqa: PLC0415

    creds_path = str(tmp_path / "gmail.json")
    return GmailConnector(credentials_path=creds_path)


# ---------------------------------------------------------------------------
# Test 1 — not connected without a credentials file
# ---------------------------------------------------------------------------


def test_not_connected_without_credentials(connector) -> None:
    """is_connected() returns False when no credentials file exists."""
    assert connector.is_connected() is False


# ---------------------------------------------------------------------------
# Test 2 — auth_type is "oauth"
# ---------------------------------------------------------------------------


def test_auth_type_is_oauth(connector) -> None:
    """GmailConnector.auth_type must be 'oauth'."""
    assert connector.auth_type == "oauth"


# ---------------------------------------------------------------------------
# Test 3 — auth_url returns a valid Google consent URL
# ---------------------------------------------------------------------------


def test_auth_url_returns_string(connector) -> None:
    """auth_url() returns a URL pointing to Google's OAuth endpoint."""
    url = connector.auth_url()
    assert isinstance(url, str)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "gmail.readonly" in url


# ---------------------------------------------------------------------------
# Test 4 — sync yields documents with correct fields (mocked API)
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.gmail._gmail_api_list_messages")
@patch("openjarvis.connectors.gmail._gmail_api_get_message")
def test_sync_yields_documents(
    mock_get,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """sync() yields one Document per message with correct metadata."""
    # Set up fake credentials so is_connected() returns True
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    # Configure mocks
    mock_list.return_value = _LIST_RESPONSE
    mock_get.side_effect = lambda token, msg_id: _MSG1 if msg_id == "msg1" else _MSG2

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 2

    # --- Message 1 ---
    doc1 = next(d for d in docs if d.doc_id == "gmail:msg1")
    assert doc1.source == "gmail"
    assert doc1.doc_type == "email"
    assert doc1.title == "Q3 Planning"
    assert doc1.author == "alice@example.com"
    assert doc1.content == "Hello world"
    assert doc1.thread_id == "thread1"
    assert "alice@example.com" in doc1.participants

    # --- Message 2 ---
    doc2 = next(d for d in docs if d.doc_id == "gmail:msg2")
    assert doc2.title == "Re: Budget"
    assert doc2.author == "bob@example.com"
    assert doc2.content == "Budget reply"
    assert doc2.thread_id == "thread2"

    # Verify the API was called correctly
    mock_list.assert_called_once()
    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# Test 5 — disconnect removes the credentials file
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
# Test 6 — mcp_tools returns the three expected tool specs
# ---------------------------------------------------------------------------


def test_mcp_tools(connector) -> None:
    """mcp_tools() returns exactly 3 tools with the required names."""
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert len(tools) == 3
    assert "gmail_search_emails" in names
    assert "gmail_get_thread" in names
    assert "gmail_list_unread" in names


# ---------------------------------------------------------------------------
# Test 7 — sync passes since as an after: query to the list messages API
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.gmail._gmail_api_list_messages")
@patch("openjarvis.connectors.gmail._gmail_api_get_message")
def test_sync_passes_since_as_query(
    mock_get,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """sync(since=...) passes an after:<epoch> query to _gmail_api_list_messages."""
    from datetime import datetime, timezone  # noqa: PLC0415

    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    mock_list.return_value = {"messages": []}  # no messages needed for this test

    since_dt = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    list(connector.sync(since=since_dt))

    mock_list.assert_called_once()
    _, call_kwargs = mock_list.call_args
    assert "query" in call_kwargs
    assert call_kwargs["query"].startswith("after:")
    # Verify the epoch value is correct
    expected_epoch = int(since_dt.timestamp())
    assert call_kwargs["query"] == f"after:{expected_epoch}"


# ---------------------------------------------------------------------------
# Test 8 — sync without since passes an empty query
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.gmail._gmail_api_list_messages")
@patch("openjarvis.connectors.gmail._gmail_api_get_message")
def test_sync_without_since_passes_empty_query(
    mock_get,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """sync() without since= passes an empty query string."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    mock_list.return_value = {"messages": []}

    list(connector.sync())

    mock_list.assert_called_once()
    _, call_kwargs = mock_list.call_args
    assert call_kwargs.get("query", "") == ""


# ---------------------------------------------------------------------------
# Test 9 — ConnectorRegistry contains "gmail" after import
# ---------------------------------------------------------------------------


def test_registry() -> None:
    """GmailConnector can be registered and retrieved via ConnectorRegistry."""
    from openjarvis.connectors.gmail import GmailConnector  # noqa: PLC0415

    # The registry is cleared before each test by the autouse conftest fixture,
    # so we imperatively re-register here (same pattern as test_obsidian.py).
    ConnectorRegistry.register_value("gmail", GmailConnector)
    assert ConnectorRegistry.contains("gmail")
    cls = ConnectorRegistry.get("gmail")
    assert cls.connector_id == "gmail"
