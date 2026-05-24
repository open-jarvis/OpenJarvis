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

_AUTH_TEST_RESPONSE = {
    "ok": True,
    "team_id": "T0ACME",
    "team": "Acme",
    "url": "https://acme.slack.com/",
    "user": "bot",
    "user_id": "UBOT",
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
    """auth_url() returns a URL requesting user-token scopes (not bot scopes).

    The migration to user OAuth tokens means scopes go in ``user_scope``
    (not ``scope``), and DM/MPIM history scopes are mandatory.
    """
    url = connector.auth_url()
    assert isinstance(url, str)
    assert "slack.com" in url
    # User-token install: scopes carried by ``user_scope``, not ``scope``.
    assert "user_scope=" in url
    # DM and MPIM history are required for Deep Research over personal DMs.
    assert "im:history" in url or "im%3Ahistory" in url
    assert "mpim:history" in url or "mpim%3Ahistory" in url
    assert "channels:history" in url or "channels%3Ahistory" in url


# ---------------------------------------------------------------------------
# Test 4 — sync yields documents with correct fields (mocked API)
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.slack_connector._slack_api_auth_test")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_list")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_history")
@patch("openjarvis.connectors.slack_connector._slack_api_users_list")
def test_sync_yields_documents(
    mock_users,
    mock_history,
    mock_channels,
    mock_auth,
    connector,
    tmp_path: Path,
) -> None:
    """sync() yields one Document per message with correct metadata.

    With 2 channels each having 2 messages, we expect exactly 4 documents.
    """
    # Set up fake credentials so is_connected() returns True. User tokens
    # (``xoxp-``) are the only shape the connector accepts post-migration.
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(
        json.dumps({"token": "xoxp-fake-user-token"}), encoding="utf-8"
    )

    # Configure mocks
    mock_auth.return_value = _AUTH_TEST_RESPONSE
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

    # Check a specific document from #general — doc_id encodes the
    # workspace subdomain so research_loop can rebuild the permalink.
    doc_c001 = next(
        (d for d in docs if d.doc_id == "slack:acme:C001:1710500000.000100"),
        None,
    )
    assert doc_c001 is not None
    assert doc_c001.title == "#general"
    assert doc_c001.author == "alice@co.com"
    assert doc_c001.content == "Let's discuss the API redesign."
    assert doc_c001.thread_id == "1710500000.000100"
    # v1 schema fields
    assert doc_c001.participants == ["alice@co.com"]
    assert doc_c001.participants_raw == ["U001"]
    assert doc_c001.channel == "general"
    assert doc_c001.url == (
        "https://acme.slack.com/archives/C001/p1710500000000100"
    )
    assert doc_c001.metadata["channel_id"] == "C001"
    assert doc_c001.metadata["channel_name"] == "general"
    assert doc_c001.metadata["team_id"] == "T0ACME"
    assert doc_c001.metadata["team_domain"] == "acme"

    # Check a specific document from #engineering
    doc_c002 = next(
        (d for d in docs if d.doc_id == "slack:acme:C002:1710500060.000200"),
        None,
    )
    assert doc_c002 is not None
    assert doc_c002.title == "#engineering"
    assert doc_c002.author == "bob@co.com"
    assert doc_c002.content == "Sounds good, I'll prepare a doc."
    assert doc_c002.thread_id is None
    assert doc_c002.channel == "engineering"

    # Verify the API was called correctly
    mock_auth.assert_called_once()
    mock_users.assert_called_once()
    assert mock_channels.call_count == 1
    # conversations.history called once per channel (2 channels)
    assert mock_history.call_count == 2


# ---------------------------------------------------------------------------
# Test — conversations.list is called with every conversation type so
# DMs and group DMs auto-sync alongside public/private channels.
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.slack_connector._slack_api_with_retry")
def test_conversations_list_requests_all_conversation_types(mock_retry) -> None:
    """``_slack_api_conversations_list`` widens ``types`` to cover IMs + MPIMs.

    A user connecting Slack expects ``everything I can see is searchable``
    without a per-channel opt-in — same as Gmail. The proxy for that here
    is the API request shape: ``types`` must include im + mpim so the bot
    token's DMs and group DMs come back in the listing.
    """
    from openjarvis.connectors.slack_connector import (  # noqa: PLC0415
        _slack_api_conversations_list,
    )

    mock_retry.return_value = {"channels": [], "response_metadata": {}}
    _slack_api_conversations_list("fake-token")

    method, _token, params = mock_retry.call_args.args[:3]
    assert method == "conversations.list"
    types = params["types"].split(",")
    assert set(types) == {"public_channel", "private_channel", "mpim", "im"}


# ---------------------------------------------------------------------------
# Test — sync() yields documents for DMs (im) and group DMs (mpim) too,
# without requiring conversations.join (no join concept on those types).
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.slack_connector._slack_api_with_retry")
@patch("openjarvis.connectors.slack_connector._slack_api_auth_test")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_list")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_history")
@patch("openjarvis.connectors.slack_connector._slack_api_users_list")
def test_sync_includes_dms_and_group_dms(
    mock_users,
    mock_history,
    mock_channels,
    mock_auth,
    mock_retry,
    connector,
    tmp_path: Path,
) -> None:
    """IMs and MPIMs are synced with sensible labels — no join, no membership filter.

    With a user token, ``conversations.list`` already reflects what the
    user can see. The connector must NOT call ``conversations.join`` for
    any conversation type, and must NOT skip non-``is_member`` channels.
    """
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(
        json.dumps({"token": "xoxp-fake-user-token"}), encoding="utf-8"
    )

    mock_auth.return_value = _AUTH_TEST_RESPONSE
    mock_users.return_value = _USERS_RESPONSE
    mock_channels.return_value = {
        "channels": [
            {
                "id": "C001",
                "name": "general",
                # No is_member field — user tokens shouldn't depend on it.
            },
            {
                "id": "D001",
                "is_im": True,
                "user": "U001",  # 1:1 DM with Alice
            },
            {
                "id": "G001",
                "name": "mpdm-alice--bob-1",
                "is_mpim": True,
            },
        ],
        "response_metadata": {"next_cursor": ""},
    }
    mock_history.return_value = {
        "messages": [
            {
                "ts": "1710500000.000100",
                "user": "U001",
                "text": "context-specific message",
            },
        ],
        "has_more": False,
    }
    # _slack_api_with_retry covers any endpoint not individually mocked
    # (auth.test, users.list, conversations.list, conversations.history
    # are intercepted above). A call to ``conversations.join`` here would
    # mean the connector is back to bot-token behavior.
    mock_retry.return_value = {"ok": False}

    docs: List[Document] = list(connector.sync())

    # One message per conversation × 3 conversations = 3 documents.
    assert len(docs) == 3

    by_chan_id = {d.metadata["channel_id"]: d for d in docs}

    public_doc = by_chan_id["C001"]
    assert public_doc.title == "#general"
    assert public_doc.channel == "general"
    assert public_doc.metadata["channel_type"] == "public_channel"

    im_doc = by_chan_id["D001"]
    assert im_doc.title == "DM with Alice"
    assert im_doc.channel == "dm-Alice"
    assert im_doc.metadata["channel_type"] == "im"

    mpim_doc = by_chan_id["G001"]
    assert mpim_doc.title == "#mpdm-alice--bob-1"
    assert mpim_doc.channel == "mpdm-alice--bob-1"
    assert mpim_doc.metadata["channel_type"] == "mpim"

    # User-token sync must NEVER call conversations.join (the user is
    # already in the conversations the listing returns).
    join_calls = [
        c
        for c in mock_retry.call_args_list
        if c.args and c.args[0] == "conversations.join"
    ]
    assert join_calls == []


# ---------------------------------------------------------------------------
# Test 5 — disconnect removes the credentials file
# ---------------------------------------------------------------------------


def test_disconnect(connector, tmp_path: Path) -> None:
    """disconnect() deletes the credentials file."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(
        json.dumps({"token": "xoxp-fake-user-token"}), encoding="utf-8"
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


# ---------------------------------------------------------------------------
# Test 8 — end-to-end: connector → pipeline → KnowledgeStore → HybridSearch
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.slack_connector._slack_api_auth_test")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_list")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_history")
@patch("openjarvis.connectors.slack_connector._slack_api_users_list")
def test_end_to_end_ingest_and_search(
    mock_users,
    mock_history,
    mock_channels,
    mock_auth,
    connector,
    tmp_path: Path,
) -> None:
    """Synced Slack messages are searchable via HybridSearch with v1 fields.

    Lexical-only path (no embedder) so this stays a pure unit test — no
    Ollama daemon needed. Confirms the v1 contract end-to-end: source,
    namespaced thread_id, channel, participants, and a workspace-qualified
    permalink all survive ingest → store → hit.
    """
    from openjarvis.connectors.hybrid_search import HybridSearch  # noqa: PLC0415
    from openjarvis.connectors.pipeline import IngestionPipeline  # noqa: PLC0415
    from openjarvis.connectors.store import KnowledgeStore  # noqa: PLC0415

    creds_path = Path(connector._credentials_path)
    creds_path.write_text(
        json.dumps({"token": "xoxp-fake-user-token"}), encoding="utf-8"
    )
    mock_auth.return_value = _AUTH_TEST_RESPONSE
    mock_users.return_value = _USERS_RESPONSE
    mock_channels.return_value = _CHANNELS_RESPONSE
    mock_history.return_value = _HISTORY_RESPONSE

    store = KnowledgeStore(db_path=tmp_path / "slack_e2e.db")
    pipeline = IngestionPipeline(store)
    chunks_stored = pipeline.ingest(connector.sync())

    # 4 short messages → 4 chunks (no chunk splitting at this length).
    assert chunks_stored == 4

    hybrid = HybridSearch(store)
    hits = hybrid.search("API redesign", limit=5)
    assert len(hits) >= 1

    target = next(
        (h for h in hits if "API redesign" in h.content_snippet),
        None,
    )
    assert target is not None
    assert target.source == "slack"
    assert target.title == "#general"
    # Thread id is namespaced by the pipeline.
    assert target.thread_id == "slack:1710500000.000100"
    assert target.participants == ["alice@co.com"]
    # The stored doc_id flows through the hit and is the format the
    # research-loop URL builder expects.
    assert target.document_id == "slack:acme:C001:1710500000.000100"

    # And the research-loop builder reconstructs the workspace permalink.
    from openjarvis.agents.research_loop import _hit_url  # noqa: PLC0415

    assert _hit_url(target.source, target.document_id) == (
        "https://acme.slack.com/archives/C001/p1710500000000100"
    )


# ---------------------------------------------------------------------------
# Test — bot tokens (xoxb-) are rejected with a clear error at connect time.
# ---------------------------------------------------------------------------


def test_handle_callback_rejects_xoxb(connector) -> None:
    """handle_callback() refuses bot tokens before writing them to disk."""
    from openjarvis.connectors.slack_connector import (  # noqa: PLC0415
        SlackTokenError,
    )

    with pytest.raises(SlackTokenError) as excinfo:
        connector.handle_callback("xoxb-some-bot-token")

    msg = str(excinfo.value).lower()
    assert "xoxb" in msg
    assert "user oauth token" in msg or "xoxp" in msg
    # Token must not have been persisted on rejection.
    assert not Path(connector._credentials_path).exists()


def test_handle_callback_rejects_unknown_prefix(connector) -> None:
    """handle_callback() refuses tokens that don't match the user-token shape."""
    from openjarvis.connectors.slack_connector import (  # noqa: PLC0415
        SlackTokenError,
    )

    with pytest.raises(SlackTokenError):
        connector.handle_callback("xapp-app-level-token")
    assert not Path(connector._credentials_path).exists()


# ---------------------------------------------------------------------------
# Test — a stored bot token surfaces an error in sync_status and yields
# zero documents (defensive guard for credentials written before this
# migration).
# ---------------------------------------------------------------------------


def test_sync_with_xoxb_token_surfaces_error(connector, tmp_path: Path) -> None:
    """A leftover bot token must produce an explanatory sync error."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "xoxb-bot-token"}), encoding="utf-8")

    docs = list(connector.sync())

    assert docs == []
    status = connector.sync_status()
    assert status.error is not None
    assert "xoxb" in status.error.lower() or "user oauth token" in status.error.lower()
    assert "xoxp" in status.error.lower()


# ---------------------------------------------------------------------------
# Test — sync logs a per-type channel count before fetching history so
# operators can see at a glance what the token has access to.
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.slack_connector._slack_api_auth_test")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_list")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_history")
@patch("openjarvis.connectors.slack_connector._slack_api_users_list")
def test_sync_logs_per_type_channel_counts(
    mock_users,
    mock_history,
    mock_channels,
    mock_auth,
    connector,
    tmp_path: Path,
    caplog,
) -> None:
    """Each sync logs ``Found X public, Y private, Z DMs, W group DMs``.

    The diagnostic is the single fastest way to tell whether a token's
    scopes are correct without grepping per-channel logs.
    """
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(
        json.dumps({"token": "xoxp-fake-user-token"}), encoding="utf-8"
    )

    mock_auth.return_value = _AUTH_TEST_RESPONSE
    mock_users.return_value = _USERS_RESPONSE
    mock_channels.return_value = {
        "channels": [
            {"id": "C001", "name": "public-1"},
            {"id": "C002", "name": "public-2"},
            {"id": "C003", "name": "public-3"},
            {"id": "P001", "name": "private-1", "is_private": True},
            {"id": "D001", "is_im": True, "user": "U001"},
            {"id": "D002", "is_im": True, "user": "U002"},
            {"id": "G001", "name": "mpdm-x", "is_mpim": True},
        ],
        "response_metadata": {"next_cursor": ""},
    }
    mock_history.return_value = {"messages": [], "has_more": False}

    with caplog.at_level("INFO", logger="openjarvis.connectors.slack_connector"):
        list(connector.sync())

    summary = " ".join(r.message for r in caplog.records)
    assert "Found 3 public channels" in summary
    assert "1 private channels" in summary
    assert "2 DMs" in summary
    assert "1 group DMs" in summary


# ---------------------------------------------------------------------------
# Test — handle_callback verifies the token with a live auth.test BEFORE it
# persists anything, so a syntactically-valid-but-dead token is rejected at
# connect time instead of overwriting a working credential on disk.
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.slack_connector._slack_api_auth_test")
def test_handle_callback_persists_after_auth_test_succeeds(
    mock_auth, connector
) -> None:
    """A valid xoxp- token is persisted only after auth.test returns ok."""
    mock_auth.return_value = _AUTH_TEST_RESPONSE

    connector.handle_callback("xoxp-valid-user-token")

    mock_auth.assert_called_once_with("xoxp-valid-user-token")
    stored = json.loads(Path(connector._credentials_path).read_text())
    assert stored["token"] == "xoxp-valid-user-token"


@patch("openjarvis.connectors.slack_connector._slack_api_auth_test")
def test_handle_callback_rejects_when_auth_test_fails(mock_auth, connector) -> None:
    """A well-formed token Slack rejects (auth.test not ok) is never written."""
    from openjarvis.connectors.slack_connector import SlackTokenError  # noqa: PLC0415

    mock_auth.return_value = {"ok": False, "error": "invalid_auth"}

    with pytest.raises(SlackTokenError) as excinfo:
        connector.handle_callback("xoxp-revoked-token")

    assert "invalid_auth" in str(excinfo.value)
    assert not Path(connector._credentials_path).exists()


@patch("openjarvis.connectors.slack_connector._slack_api_auth_test")
def test_handle_callback_skips_auth_test_for_bad_shape(mock_auth, connector) -> None:
    """Shape validation short-circuits before any network call is made."""
    from openjarvis.connectors.slack_connector import SlackTokenError  # noqa: PLC0415

    with pytest.raises(SlackTokenError):
        connector.handle_callback("xoxb-bot-token")

    mock_auth.assert_not_called()
    assert not Path(connector._credentials_path).exists()


def test_handle_callback_xoxb_message_wording(connector) -> None:
    """The xoxb- rejection carries the user-facing 'can't read DMs' guidance."""
    from openjarvis.connectors.slack_connector import SlackTokenError  # noqa: PLC0415

    with pytest.raises(SlackTokenError) as excinfo:
        connector.handle_callback("xoxb-bot-token")

    assert str(excinfo.value) == (
        "Bot tokens (xoxb-) can't read DMs. "
        "Use a User OAuth Token (xoxp-) instead."
    )
