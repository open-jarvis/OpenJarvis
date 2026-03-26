"""Tests for SlackConnector — OAuth-authenticated Slack channel message sync.

All Slack API calls are mocked; no network access is required.
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

_CHANNELS_RESPONSE = {
    "channels": [
        {"id": "C001", "name": "general", "is_member": True},
        {"id": "C002", "name": "engineering", "is_member": True},
    ],
    "response_metadata": {"next_cursor": ""},
}

_HISTORY_RESPONSE = {
    "messages": [
        {
            "ts": "1710500000.000100",
            "user": "U001",
            "text": "Let's discuss the API redesign.",
            "thread_ts": "1710500000.000100",
        },
        {
            "ts": "1710500060.000200",
            "user": "U002",
            "text": "Sounds good, I'll prepare a doc.",
        },
    ],
    "has_more": False,
}

_USERS_RESPONSE = {
    "members": [
        {"id": "U001", "real_name": "Alice", "profile": {"email": "alice@co.com"}},
        {"id": "U002", "real_name": "Bob", "profile": {"email": "bob@co.com"}},
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def connector(tmp_path: Path):
    """SlackConnector pointing at a tmp credentials path (no file yet)."""
    from openjarvis.connectors.slack_connector import SlackConnector  # noqa: PLC0415

    creds_path = str(tmp_path / "slack.json")
    return SlackConnector(credentials_path=creds_path)


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
    """SlackConnector.auth_type must be 'oauth'."""
    assert connector.auth_type == "oauth"


# ---------------------------------------------------------------------------
# Test 3 — auth_url contains "slack.com"
# ---------------------------------------------------------------------------


def test_auth_url(connector) -> None:
    """auth_url() returns a URL pointing to Slack's OAuth endpoint."""
    url = connector.auth_url()
    assert isinstance(url, str)
    assert "slack.com" in url
    assert "channels:history" in url or "channels%3Ahistory" in url


# ---------------------------------------------------------------------------
# Test 4 — sync yields documents with correct fields (mocked API)
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.slack_connector._slack_api_conversations_list")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_history")
@patch("openjarvis.connectors.slack_connector._slack_api_users_list")
def test_sync_yields_documents(
    mock_users,
    mock_history,
    mock_channels,
    connector,
    tmp_path: Path,
) -> None:
    """sync() yields one Document per message with correct metadata.

    With 2 channels each having 2 messages, we expect exactly 4 documents.
    """
    # Set up fake credentials so is_connected() returns True
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(
        json.dumps({"token": "fake-access-token"}), encoding="utf-8"
    )

    # Configure mocks
    mock_users.return_value = _USERS_RESPONSE
    mock_channels.return_value = _CHANNELS_RESPONSE
    mock_history.return_value = _HISTORY_RESPONSE

    docs: List[Document] = list(connector.sync())

    # 2 channels × 2 messages = 4 documents
    assert len(docs) == 4

    # Verify all docs have correct source and doc_type
    for doc in docs:
        assert doc.source == "slack"
        assert doc.doc_type == "message"

    # Check a specific document from #general
    doc_c001 = next(
        (d for d in docs if d.doc_id == "slack:C001:1710500000.000100"), None
    )
    assert doc_c001 is not None
    assert doc_c001.title == "#general"
    assert doc_c001.author == "Alice"
    assert doc_c001.content == "Let's discuss the API redesign."
    assert doc_c001.thread_id == "1710500000.000100"
    assert doc_c001.metadata["channel_id"] == "C001"
    assert doc_c001.metadata["channel_name"] == "general"

    # Check a specific document from #engineering
    doc_c002 = next(
        (d for d in docs if d.doc_id == "slack:C002:1710500060.000200"), None
    )
    assert doc_c002 is not None
    assert doc_c002.title == "#engineering"
    assert doc_c002.author == "Bob"
    assert doc_c002.content == "Sounds good, I'll prepare a doc."
    assert doc_c002.thread_id is None

    # Verify the API was called correctly
    mock_users.assert_called_once()
    assert mock_channels.call_count == 1
    # conversations.history called once per channel (2 channels)
    assert mock_history.call_count == 2


# ---------------------------------------------------------------------------
# Test 5 — disconnect removes the credentials file
# ---------------------------------------------------------------------------


def test_disconnect(connector, tmp_path: Path) -> None:
    """disconnect() deletes the credentials file."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(
        json.dumps({"token": "fake-access-token"}), encoding="utf-8"
    )
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
    assert "slack_search_messages" in names
    assert "slack_get_thread" in names
    assert "slack_list_channels" in names


# ---------------------------------------------------------------------------
# Test 7 — ConnectorRegistry contains "slack" after import
# ---------------------------------------------------------------------------


def test_registry() -> None:
    """SlackConnector can be registered and retrieved via ConnectorRegistry."""
    from openjarvis.connectors.slack_connector import SlackConnector  # noqa: PLC0415

    # The registry is cleared before each test by the autouse conftest fixture,
    # so we imperatively re-register here (same pattern as test_gmail.py).
    ConnectorRegistry.register_value("slack", SlackConnector)
    assert ConnectorRegistry.contains("slack")
    cls = ConnectorRegistry.get("slack")
    assert cls.connector_id == "slack"
