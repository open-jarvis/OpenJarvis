"""Tests for GmailConnector — OAuth-authenticated Gmail sync connector.

All Gmail API calls are mocked; no network access is required.
"""

from __future__ import annotations

import base64
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
    assert "gmail.modify" in url


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
    # Deep-link permalink to the message must be populated at ingest time
    # (GH #408) — not left empty for _hit_url to reconstruct later.
    assert doc1.url == "https://mail.google.com/mail/u/0/#all/msg1"

    # --- Message 2 ---
    doc2 = next(d for d in docs if d.doc_id == "gmail:msg2")
    assert doc2.title == "Re: Budget"
    assert doc2.author == "bob@example.com"
    assert doc2.content == "Budget reply"
    assert doc2.thread_id == "thread2"
    assert doc2.url == "https://mail.google.com/mail/u/0/#all/msg2"

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
    assert "after:" in call_kwargs["query"]
    # Verify the epoch value is correct
    expected_epoch = int(since_dt.timestamp())
    assert f"after:{expected_epoch}" in call_kwargs["query"]
    # No category filter — sent mail and all Gmail tabs should be reachable.
    assert "category:" not in call_kwargs["query"]


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
    # No since= and no hardcoded category filter → empty query.
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


# ---------------------------------------------------------------------------
# v1 schema tests
# ---------------------------------------------------------------------------

# base64url("Migration body") == "TWlncmF0aW9uIGJvZHk="
_MSG_RICH = {
    "id": "msg-rich-1",
    "threadId": "thread-rich-1",
    "labelIds": ["SENT", "CATEGORY_PERSONAL"],
    "snippet": "Quick note on the migration",
    "historyId": "1234567",
    "sizeEstimate": 4096,
    "payload": {
        "mimeType": "text/plain",
        "headers": [
            {"name": "From", "value": "Alice Bose <alice@example.com>"},
            {
                "name": "To",
                "value": "Bob <bob@example.com>, charlie@example.com",
            },
            {"name": "Cc", "value": "dana@example.com"},
            {"name": "Subject", "value": "Migration plan"},
            {"name": "Date", "value": "Mon, 01 Jan 2024 10:00:00 +0000"},
            {"name": "Message-ID", "value": "<abc123@mail.example.com>"},
        ],
        "body": {"data": "TWlncmF0aW9uIGJvZHk="},
    },
}


@patch("openjarvis.connectors.gmail._gmail_api_list_messages")
@patch("openjarvis.connectors.gmail._gmail_api_get_message")
def test_sync_emits_v1_fields(
    mock_get,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """sync() populates source_id, participants_raw, normalized participants,
    channel from labels, and Gmail-specific fields in metadata."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    mock_list.return_value = {"messages": [{"id": "msg-rich-1"}]}
    mock_get.return_value = _MSG_RICH

    docs: List[Document] = list(connector.sync())
    assert len(docs) == 1
    doc = docs[0]

    # source_id is the raw Gmail msg.id (no "gmail:" prefix); doc_id stays
    # composite for back-compat with legacy callers.
    assert doc.source_id == "msg-rich-1"
    assert doc.doc_id == "gmail:msg-rich-1"

    # participants_raw preserves From / To / Cc as Gmail returned them.
    assert doc.participants_raw == [
        "Alice Bose <alice@example.com>",
        "Bob <bob@example.com>, charlie@example.com",
        "dana@example.com",
    ]
    # participants extracts and lowercases all addresses, multi-recipient-aware.
    assert doc.participants == [
        "alice@example.com",
        "bob@example.com",
        "charlie@example.com",
        "dana@example.com",
    ]

    # channel comes from the highest-priority system label.
    assert doc.channel == "SENT"

    # Gmail-specific richness lives in source_metadata.
    assert doc.metadata["rfc_message_id"] == "<abc123@mail.example.com>"
    assert doc.metadata["snippet"] == "Quick note on the migration"
    assert doc.metadata["history_id"] == "1234567"
    assert doc.metadata["size_estimate"] == 4096
    assert "SENT" in doc.metadata["labels"]
    assert "CATEGORY_PERSONAL" in doc.metadata["labels"]


@patch("openjarvis.connectors.gmail._gmail_api_list_messages")
@patch("openjarvis.connectors.gmail._gmail_api_get_message")
def test_sync_channel_falls_back_to_inbox(
    mock_get,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """When only INBOX is present among system labels, channel == 'INBOX'."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    mock_list.return_value = _LIST_RESPONSE
    mock_get.side_effect = lambda token, msg_id: _MSG1 if msg_id == "msg1" else _MSG2

    docs = list(connector.sync())
    assert all(d.channel == "INBOX" for d in docs)


@patch("openjarvis.connectors.gmail._gmail_api_list_messages")
@patch("openjarvis.connectors.gmail._gmail_api_get_message")
def test_sync_channel_none_when_no_system_label(
    mock_get,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """A message with only user-defined labels has channel=None."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    msg_userlabel = {
        **_MSG1,
        "id": "msg-user",
        "labelIds": ["Label_1234", "CATEGORY_FORUMS"],
    }
    mock_list.return_value = {"messages": [{"id": "msg-user"}]}
    mock_get.return_value = msg_userlabel

    docs = list(connector.sync())
    assert len(docs) == 1
    assert docs[0].channel is None


# ---------------------------------------------------------------------------
# HTML body stripping
# ---------------------------------------------------------------------------


def test_html_to_text_strips_basic_tags() -> None:
    """_html_to_text() removes tags but preserves visible text content."""
    from openjarvis.connectors.gmail import _html_to_text  # noqa: PLC0415

    html = (
        "<html><body><p>Hello <b>world</b>!</p><p>Second paragraph.</p></body></html>"
    )
    text = _html_to_text(html)
    assert "Hello" in text
    assert "world" in text
    assert "Second paragraph" in text
    assert "<" not in text and ">" not in text


def test_html_to_text_drops_script_and_style() -> None:
    """Content inside <script>/<style>/<head> is stripped, not rendered."""
    from openjarvis.connectors.gmail import _html_to_text  # noqa: PLC0415

    html = """
    <html>
      <head><style>.foo { color: red; }</style><title>Ignore me</title></head>
      <body>
        <script>alert('xss')</script>
        <p>Visible content here.</p>
      </body>
    </html>
    """
    text = _html_to_text(html)
    assert "Visible content here" in text
    assert "color: red" not in text
    assert "alert" not in text
    assert "Ignore me" not in text


def test_html_to_text_decodes_entities() -> None:
    """Named and numeric HTML entities are decoded to their characters."""
    from openjarvis.connectors.gmail import _html_to_text  # noqa: PLC0415

    html = "<p>Tom &amp; Jerry &mdash; 50&nbsp;cents</p>"
    text = _html_to_text(html)
    assert "Tom & Jerry" in text
    assert "—" in text  # &mdash;
    assert "50" in text and "cents" in text


def test_html_to_text_inserts_paragraph_breaks() -> None:
    """Block-level tags produce newlines so the chunker sees structure."""
    from openjarvis.connectors.gmail import _html_to_text  # noqa: PLC0415

    html = "<div>line one</div><div>line two</div><div>line three</div>"
    text = _html_to_text(html)
    # Each block produces at least one newline boundary.
    assert text.count("\n") >= 2


@patch("openjarvis.connectors.gmail._gmail_api_list_messages")
@patch("openjarvis.connectors.gmail._gmail_api_get_message")
def test_sync_strips_html_when_no_text_plain(
    mock_get,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """A multipart message with only text/html yields stripped plain text."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    html_bytes = (
        b"<html><body><p>Hello <b>world</b>!</p><p>Second paragraph.</p></body></html>"
    )
    html_b64 = base64.urlsafe_b64encode(html_bytes).decode().rstrip("=")

    msg_html = {
        "id": "msg-html-1",
        "threadId": "thread-html-1",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "marketer@example.com"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Marketing"},
                {"name": "Date", "value": "Mon, 01 Jan 2024 10:00:00 +0000"},
            ],
            "parts": [
                # No text/plain alternative — only text/html.
                {
                    "mimeType": "text/html",
                    "body": {"data": html_b64},
                },
            ],
        },
    }

    mock_list.return_value = {"messages": [{"id": "msg-html-1"}]}
    mock_get.return_value = msg_html

    docs = list(connector.sync())
    assert len(docs) == 1
    content = docs[0].content
    assert "Hello" in content
    assert "world" in content
    assert "Second paragraph" in content
    assert "<" not in content and ">" not in content


@patch("openjarvis.connectors.gmail._gmail_api_list_messages")
@patch("openjarvis.connectors.gmail._gmail_api_get_message")
def test_sync_prefers_text_plain_over_text_html(
    mock_get,
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """When both alternatives are present, text/plain wins over text/html."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    plain_b64 = (
        base64.urlsafe_b64encode(b"Plain text version preferred.").decode().rstrip("=")
    )
    html_b64 = (
        base64.urlsafe_b64encode(b"<html><body><p>HTML version</p></body></html>")
        .decode()
        .rstrip("=")
    )

    msg_alt = {
        "id": "msg-alt-1",
        "threadId": "thread-alt-1",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "alice@example.com"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Both alternatives"},
                {"name": "Date", "value": "Mon, 01 Jan 2024 10:00:00 +0000"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": plain_b64}},
                {"mimeType": "text/html", "body": {"data": html_b64}},
            ],
        },
    }

    mock_list.return_value = {"messages": [{"id": "msg-alt-1"}]}
    mock_get.return_value = msg_alt

    docs = list(connector.sync())
    assert len(docs) == 1
    assert docs[0].content == "Plain text version preferred."


# ---------------------------------------------------------------------------
# Auto-refresh on 401
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for httpx.Response used by the refresh test."""

    def __init__(
        self, *, status_code: int, json_data: dict | None = None, text: str = ""
    ):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx as _httpx

            raise _httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self
            )


def _write_full_creds(tmp_path: Path) -> str:
    """Write a credentials file with a refresh_token and client credentials."""
    creds_path = tmp_path / "gmail.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "old-access-token",
                "refresh_token": "stored-refresh-token",
                "client_id": "client-id-abc",
                "client_secret": "client-secret-xyz",
            }
        ),
        encoding="utf-8",
    )
    return str(creds_path)


def test_401_triggers_refresh_and_retries_with_new_token(tmp_path: Path) -> None:
    """A 401 on a Gmail API call refreshes the token, persists it, and retries."""
    from openjarvis.connectors import gmail as gmail_mod

    creds_path = _write_full_creds(tmp_path)

    # The first httpx.get returns 401, the second returns 200.
    get_calls: list[dict] = []

    def fake_get(url, *, headers, params, timeout):
        get_calls.append({"url": url, "headers": dict(headers), "params": dict(params)})
        if len(get_calls) == 1:
            return _FakeResponse(status_code=401, text="unauthorized")
        return _FakeResponse(status_code=200, json_data={"id": "msg-1", "payload": {}})

    post_calls: list[dict] = []

    def fake_post(url, *, data, timeout):
        post_calls.append({"url": url, "data": dict(data)})
        return _FakeResponse(
            status_code=200,
            json_data={"access_token": "fresh-access-token", "expires_in": 3599},
        )

    with (
        patch.object(gmail_mod.httpx, "get", side_effect=fake_get),
        patch.object(gmail_mod.httpx, "post", side_effect=fake_post),
    ):
        result = gmail_mod._call_with_refresh(
            gmail_mod._gmail_api_get_message, creds_path, "msg-1"
        )

    # The retried request must carry the fresh token.
    assert len(get_calls) == 2
    assert get_calls[0]["headers"]["Authorization"] == "Bearer old-access-token"
    assert get_calls[1]["headers"]["Authorization"] == "Bearer fresh-access-token"

    # The refresh hit Google's token endpoint with the stored refresh credentials.
    assert len(post_calls) == 1
    assert post_calls[0]["url"] == "https://oauth2.googleapis.com/token"
    assert post_calls[0]["data"] == {
        "client_id": "client-id-abc",
        "client_secret": "client-secret-xyz",
        "refresh_token": "stored-refresh-token",
        "grant_type": "refresh_token",
    }

    # The new access_token is persisted to the credentials file.
    on_disk = json.loads(Path(creds_path).read_text(encoding="utf-8"))
    assert on_disk["access_token"] == "fresh-access-token"
    assert on_disk["token"] == "fresh-access-token"  # legacy key kept in sync
    assert on_disk["refresh_token"] == "stored-refresh-token"
    assert on_disk["expires_in"] == 3599

    # And the caller saw the body of the retried request.
    assert result == {"id": "msg-1", "payload": {}}


def test_non_401_status_is_not_refreshed(tmp_path: Path) -> None:
    """A 500 from Gmail must propagate — only 401 should trigger refresh."""
    import httpx as _httpx

    from openjarvis.connectors import gmail as gmail_mod

    creds_path = _write_full_creds(tmp_path)

    def fake_get(url, *, headers, params, timeout):
        return _FakeResponse(status_code=503, text="service unavailable")

    fake_post = patch.object(
        gmail_mod.httpx,
        "post",
        side_effect=AssertionError(
            "_call_with_refresh must not refresh on non-401 status"
        ),
    )

    with patch.object(gmail_mod.httpx, "get", side_effect=fake_get), fake_post:
        with pytest.raises(_httpx.HTTPStatusError):
            gmail_mod._call_with_refresh(
                gmail_mod._gmail_api_get_message, creds_path, "msg-1"
            )


def test_refresh_raises_when_refresh_token_missing(tmp_path: Path) -> None:
    """Refresh aborts with a clear error when no refresh_token is stored."""
    from openjarvis.connectors import google_auth

    creds_path = tmp_path / "gmail.json"
    creds_path.write_text(
        json.dumps({"access_token": "stale", "client_id": "c", "client_secret": "s"}),
        encoding="utf-8",
    )

    with pytest.raises(google_auth.GoogleAuthError, match="refresh_token"):
        google_auth.refresh_access_token(str(creds_path))


def test_sync_recovers_when_list_returns_401(tmp_path: Path) -> None:
    """An end-to-end sync survives a 401 on messages.list without re-auth.

    Sets up a connector against a creds file with full refresh credentials,
    has the first list call return 401, the refresh return a new token, and
    the retried list call return one message stub which is then fetched
    successfully. Verifies the connector yields the expected Document and
    that the credentials file is rewritten with the fresh token.
    """
    from openjarvis.connectors import gmail as gmail_mod

    creds_path = _write_full_creds(tmp_path)
    connector = gmail_mod.GmailConnector(credentials_path=creds_path)

    list_calls: list[str] = []

    def fake_get(url, *, headers, params, timeout):
        auth = headers.get("Authorization", "")
        if "/messages/" in url:
            # The single get_message call after the retried list call.
            return _FakeResponse(
                status_code=200,
                json_data={
                    "id": "msg-99",
                    "threadId": "thread-99",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "mimeType": "text/plain",
                        "headers": [
                            {"name": "From", "value": "alice@example.com"},
                            {"name": "To", "value": "me@example.com"},
                            {"name": "Subject", "value": "Hi"},
                            {
                                "name": "Date",
                                "value": "Mon, 01 Jan 2024 10:00:00 +0000",
                            },
                        ],
                        "body": {"data": "SGVsbG8="},
                    },
                },
            )
        # /messages list call
        list_calls.append(auth)
        if len(list_calls) == 1:
            return _FakeResponse(status_code=401, text="unauthorized")
        return _FakeResponse(
            status_code=200,
            json_data={"messages": [{"id": "msg-99"}]},
        )

    def fake_post(url, *, data, timeout):
        return _FakeResponse(
            status_code=200,
            json_data={"access_token": "fresh-token-after-401", "expires_in": 3599},
        )

    with (
        patch.object(gmail_mod.httpx, "get", side_effect=fake_get),
        patch.object(gmail_mod.httpx, "post", side_effect=fake_post),
    ):
        docs: List[Document] = list(connector.sync())

    assert len(docs) == 1
    assert docs[0].title == "Hi"
    assert docs[0].author == "alice@example.com"
    # First list call carried the stale token; second carried the fresh one.
    assert list_calls == ["Bearer old-access-token", "Bearer fresh-token-after-401"]
    # Creds file persisted the new token.
    on_disk = json.loads(Path(creds_path).read_text(encoding="utf-8"))
    assert on_disk["access_token"] == "fresh-token-after-401"
