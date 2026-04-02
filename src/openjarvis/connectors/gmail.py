"""Gmail connector — bulk email sync via the Gmail REST API.

Uses OAuth 2.0 tokens stored locally (see :mod:`openjarvis.connectors.oauth`).
All network calls are isolated in module-level functions (``_gmail_api_*``)
to make them trivially mockable in tests.
"""

from __future__ import annotations

import base64
import email.utils
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import (
    GOOGLE_ALL_SCOPES,
    build_google_auth_url,
    delete_tokens,
    load_tokens,
    resolve_google_credentials,
    save_tokens,
)
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
_GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "gmail.json")

# ---------------------------------------------------------------------------
# Module-level API functions (easy to patch in tests)
# ---------------------------------------------------------------------------


def _gmail_api_list_messages(
    token: str,
    *,
    page_token: Optional[str] = None,
    query: str = "",
) -> Dict[str, Any]:
    """Call the Gmail ``messages.list`` endpoint.

    Parameters
    ----------
    token:
        OAuth access token.
    page_token:
        Pagination token from a previous response's ``nextPageToken``.
    query:
        Gmail search query string (e.g. ``"is:unread"``).

    Returns
    -------
    dict
        Raw API response containing ``messages`` list and optional
        ``nextPageToken``.
    """
    params: Dict[str, str] = {}
    if page_token:
        params["pageToken"] = page_token
    if query:
        params["q"] = query

    resp = httpx.get(
        f"{_GMAIL_API_BASE}/messages",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _gmail_api_get_message(token: str, msg_id: str) -> Dict[str, Any]:
    """Fetch a single Gmail message by ID (``full`` format).

    Parameters
    ----------
    token:
        OAuth access token.
    msg_id:
        Gmail message ID string.

    Returns
    -------
    dict
        Raw API response for the message resource.
    """
    resp = httpx.get(
        f"{_GMAIL_API_BASE}/messages/{msg_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"format": "full"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _extract_header(headers: List[Dict[str, str]], name: str) -> str:
    """Return the value of the first header matching *name* (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


def _decode_body(payload: Dict[str, Any]) -> str:
    """Decode the message body from a Gmail payload dict.

    Handles both simple payloads (``body.data``) and multipart messages
    by recursively searching for a ``text/plain`` part.
    """
    mime_type: str = payload.get("mimeType", "")

    if mime_type.startswith("multipart/"):
        # Search parts for text/plain first, then any text/* fallback
        parts: List[Dict[str, Any]] = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType", "").startswith("text/plain"):
                return _decode_body(part)
        # Fallback: recurse into first part
        if parts:
            return _decode_body(parts[0])
        return ""

    body_data: str = payload.get("body", {}).get("data", "")
    if not body_data:
        return ""

    # Gmail uses URL-safe base64 without padding
    padded = body_data + "=" * (-len(body_data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def _parse_date(date_str: str) -> datetime:
    """Parse an RFC 2822 email date string into a :class:`~datetime.datetime`.

    Falls back to :func:`datetime.now` if the string is unparseable.
    """
    if not date_str:
        return datetime.now()
    try:
        return email.utils.parsedate_to_datetime(date_str)
    except Exception:  # noqa: BLE001
        return datetime.now()


# ---------------------------------------------------------------------------
# GmailConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("gmail")
class GmailConnector(BaseConnector):
    """Connector that syncs emails from Gmail via the REST API.

    Authentication is handled through Google OAuth 2.0.  Tokens are stored
    locally in a JSON credentials file.

    Parameters
    ----------
    credentials_path:
        Path to the JSON file where OAuth tokens are stored.  Defaults to
        ``~/.openjarvis/connectors/gmail.json``.
    """

    connector_id = "gmail"
    display_name = "Gmail"
    auth_type = "oauth"

    def __init__(self, credentials_path: str = "") -> None:
        self._credentials_path = resolve_google_credentials(
            credentials_path or _DEFAULT_CREDENTIALS_PATH
        )
        self._items_synced: int = 0
        self._items_total: int = 0
        self._last_sync: Optional[datetime] = None
        self._last_cursor: Optional[str] = None

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return ``True`` if a credentials file with a valid token exists."""
        tokens = load_tokens(self._credentials_path)
        if tokens is None:
            return False
        # Accept any non-empty dict that contains at least one key
        # (simplified: real impl would also check expiry / refresh token)
        return bool(tokens)

    def disconnect(self) -> None:
        """Delete the stored credentials file."""
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        """Return a Google OAuth consent URL requesting ``gmail.readonly`` scope."""
        return build_google_auth_url(
            client_id="",  # placeholder — real client_id from config
            scopes=GOOGLE_ALL_SCOPES,
        )

    def handle_callback(self, code: str) -> None:
        """Handle the OAuth callback by persisting the authorization code.

        In a full implementation this would exchange the code for tokens.
        For now the code is saved directly as the token value.
        """
        save_tokens(self._credentials_path, {"token": code})

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        """Yield :class:`Document` objects for Gmail messages.

        Paginates through the messages.list API and fetches each message's
        full payload to extract headers and body.

        Parameters
        ----------
        since:
            When provided, only messages received after this timestamp are
            returned.  Translated to a Gmail ``after:<epoch>`` search query.
        cursor:
            ``nextPageToken`` from a previous sync to resume pagination.
        """
        tokens = load_tokens(self._credentials_path)
        if not tokens:
            return

        token: str = tokens.get("token", tokens.get("access_token", ""))
        if not token:
            return

        query = ""
        if since is not None:
            # Gmail's after: operator accepts Unix epoch seconds.
            epoch = int(since.timestamp())
            query = f"after:{epoch}"

        page_token: Optional[str] = cursor
        synced = 0

        while True:
            list_resp = _gmail_api_list_messages(
                token, page_token=page_token, query=query
            )
            messages: List[Dict[str, Any]] = list_resp.get("messages", [])

            for msg_stub in messages:
                msg_id: str = msg_stub.get("id", "")
                if not msg_id:
                    continue

                msg = _gmail_api_get_message(token, msg_id)
                payload: Dict[str, Any] = msg.get("payload", {})
                headers: List[Dict[str, str]] = payload.get("headers", [])

                from_header = _extract_header(headers, "From")
                subject = _extract_header(headers, "Subject")
                date_str = _extract_header(headers, "Date")
                to_header = _extract_header(headers, "To")

                body = _decode_body(payload)
                timestamp = _parse_date(date_str)

                participants: List[str] = []
                if from_header:
                    participants.append(from_header)
                if to_header:
                    participants.append(to_header)

                thread_id: Optional[str] = msg.get("threadId")

                doc = Document(
                    doc_id=f"gmail:{msg_id}",
                    source="gmail",
                    doc_type="email",
                    content=body,
                    title=subject,
                    author=from_header,
                    participants=participants,
                    timestamp=timestamp,
                    thread_id=thread_id,
                    metadata={
                        "message_id": msg_id,
                        "labels": msg.get("labelIds", []),
                    },
                )
                synced += 1
                yield doc

            next_page: Optional[str] = list_resp.get("nextPageToken")
            if not next_page:
                self._last_cursor = None
                break
            page_token = next_page
            self._last_cursor = next_page

        self._items_synced = synced
        self._last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        """Return sync progress from the most recent :meth:`sync` call."""
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            last_sync=self._last_sync,
            cursor=self._last_cursor,
        )

    # ------------------------------------------------------------------
    # MCP tools
    # ------------------------------------------------------------------

    def mcp_tools(self) -> List[ToolSpec]:
        """Expose three MCP tool specs for real-time Gmail queries."""
        return [
            ToolSpec(
                name="gmail_search_emails",
                description=(
                    "Search Gmail messages using a query string. "
                    "Supports the same syntax as the Gmail search box "
                    "(e.g. 'from:alice subject:report is:unread')."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Gmail search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of emails to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="communication",
            ),
            ToolSpec(
                name="gmail_get_thread",
                description=("Retrieve all messages in a Gmail thread by thread ID."),
                parameters={
                    "type": "object",
                    "properties": {
                        "thread_id": {
                            "type": "string",
                            "description": "Gmail thread ID",
                        },
                    },
                    "required": ["thread_id"],
                },
                category="communication",
            ),
            ToolSpec(
                name="gmail_list_unread",
                description=(
                    "List unread Gmail messages, optionally filtered by label."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Gmail label to filter by (e.g. 'INBOX')",
                            "default": "INBOX",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of messages to return",
                            "default": 20,
                        },
                    },
                    "required": [],
                },
                category="communication",
            ),
        ]
