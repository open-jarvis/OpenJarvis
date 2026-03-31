"""Slack connector — bulk channel message sync via the Slack Web API.

Uses OAuth tokens stored locally (see :mod:`openjarvis.connectors.oauth`).
All network calls are isolated in module-level functions (``_slack_api_*``)
to make them trivially mockable in tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlencode

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import delete_tokens, load_tokens, save_tokens
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SLACK_API_BASE = "https://slack.com/api"
_SLACK_AUTH_ENDPOINT = "https://slack.com/oauth/v2/authorize"
_SLACK_SCOPES = (
    "channels:read,channels:history,groups:read,groups:history,"
    "im:read,im:history,mpim:read,mpim:history,users:read"
)
_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "slack.json")

# ---------------------------------------------------------------------------
# Module-level API functions (easy to patch in tests)
# ---------------------------------------------------------------------------


def _slack_api_conversations_list(
    token: str,
    *,
    cursor: str = "",
) -> Dict[str, Any]:
    """Call the Slack ``conversations.list`` endpoint.

    Parameters
    ----------
    token:
        OAuth access token.
    cursor:
        Pagination cursor from a previous response's ``next_cursor``.

    Returns
    -------
    dict
        Raw API response containing ``channels`` list and ``response_metadata``.
    """
    params: Dict[str, str] = {
        "types": "public_channel,private_channel",
        "exclude_archived": "true",
    }
    if cursor:
        params["cursor"] = cursor

    return _slack_api_with_retry("conversations.list", token, params)


def _slack_api_conversations_history(
    token: str,
    channel_id: str,
    *,
    cursor: str = "",
) -> Dict[str, Any]:
    """Call the Slack ``conversations.history`` endpoint.

    Parameters
    ----------
    token:
        OAuth access token.
    channel_id:
        The Slack channel ID to retrieve history for.
    cursor:
        Pagination cursor from a previous response's ``next_cursor``.

    Returns
    -------
    dict
        Raw API response containing ``messages`` list and ``has_more`` flag.
    """
    params: Dict[str, str] = {"channel": channel_id}
    if cursor:
        params["cursor"] = cursor

    return _slack_api_with_retry("conversations.history", token, params)


def _slack_api_users_list(token: str) -> Dict[str, Any]:
    """Call the Slack ``users.list`` endpoint.

    Parameters
    ----------
    token:
        OAuth access token.

    Returns
    -------
    dict
        Raw API response containing ``members`` list.
    """
    return _slack_api_with_retry("users.list", token)


def _slack_api_with_retry(
    method: str,
    token: str,
    params: Optional[Dict[str, str]] = None,
    max_retries: int = 3,
    http_method: str = "GET",
) -> Dict[str, Any]:
    """Call a Slack API method with automatic retry on rate limits."""
    import time as _time

    for attempt in range(max_retries + 1):
        if http_method == "POST":
            resp = httpx.post(
                f"{_SLACK_API_BASE}/{method}",
                headers={"Authorization": f"Bearer {token}"},
                json=params or {},
                timeout=30.0,
            )
        else:
            resp = httpx.get(
                f"{_SLACK_API_BASE}/{method}",
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
                timeout=30.0,
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            if attempt < max_retries:
                _time.sleep(retry_after)
                continue
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok") and data.get("error") == "ratelimited":
            if attempt < max_retries:
                _time.sleep(5)
                continue
        return data
    return {}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _build_user_map(members: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """Build a user_id → {name, email} map from a ``users.list`` members list."""
    user_map: Dict[str, Dict[str, str]] = {}
    for member in members:
        uid = member.get("id", "")
        if not uid:
            continue
        profile = member.get("profile", {})
        user_map[uid] = {
            "name": member.get("real_name", uid),
            "email": profile.get("email", ""),
        }
    return user_map


def _ts_to_datetime(ts: str) -> datetime:
    """Convert a Slack timestamp string (e.g. '1710500000.000100') to datetime."""
    if not ts:
        return datetime.now()
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (ValueError, OSError):
        return datetime.now()


def _slack_archive_url(team_id: str, channel_id: str, ts: str) -> str:
    """Build a Slack message archive URL from team, channel, and timestamp."""
    ts_clean = ts.replace(".", "")
    return f"https://slack.com/archives/{channel_id}/p{ts_clean}"


# ---------------------------------------------------------------------------
# SlackConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("slack")
class SlackConnector(BaseConnector):
    """Connector that syncs channel message history from Slack via the Web API.

    Authentication is handled through Slack OAuth 2.0.  Tokens are stored
    locally in a JSON credentials file.

    Parameters
    ----------
    credentials_path:
        Path to the JSON file where OAuth tokens are stored.  Defaults to
        ``~/.openjarvis/connectors/slack.json``.
    """

    connector_id = "slack"
    display_name = "Slack"
    auth_type = "oauth"

    def __init__(self, credentials_path: str = "") -> None:
        self._credentials_path = credentials_path or _DEFAULT_CREDENTIALS_PATH
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
        return bool(tokens)

    def disconnect(self) -> None:
        """Delete the stored credentials file."""
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        """Return a Slack OAuth consent URL requesting channel history scopes."""
        params = {
            "client_id": "",  # placeholder — real client_id from config
            "scope": _SLACK_SCOPES,
            "redirect_uri": "http://localhost:8789/callback",
        }
        return f"{_SLACK_AUTH_ENDPOINT}?{urlencode(params)}"

    def handle_callback(self, code: str) -> None:
        """Handle the OAuth callback by persisting the authorization code.

        In a full implementation this would exchange the code for tokens.
        For now the code is saved directly as the token value.
        """
        save_tokens(self._credentials_path, {"token": code})

    def sync(
        self,
        *,
        since: Optional[datetime] = None,  # noqa: ARG002 — reserved for future use
        cursor: Optional[str] = None,  # noqa: ARG002 — reserved for future use
    ) -> Iterator[Document]:
        """Yield :class:`Document` objects for Slack channel messages.

        Builds a user map, then paginates through channels and retrieves
        message history for each channel.

        Parameters
        ----------
        since:
            Not yet used (reserved for incremental sync).
        cursor:
            Not yet used (reserved for pagination resumption).
        """
        tokens = load_tokens(self._credentials_path)
        if not tokens:
            return

        token: str = tokens.get("token", tokens.get("access_token", ""))
        if not token:
            return

        # Step 1: build user map
        users_resp = _slack_api_users_list(token)
        members: List[Dict[str, Any]] = users_resp.get("members", [])
        user_map = _build_user_map(members)

        synced = 0
        channels_cursor = ""

        # Step 2: paginate through channels
        while True:
            channels_resp = _slack_api_conversations_list(token, cursor=channels_cursor)
            channels: List[Dict[str, Any]] = channels_resp.get("channels", [])

            for channel in channels:
                chan_id: str = channel.get("id", "")
                chan_name: str = channel.get("name", chan_id)
                is_member: bool = channel.get("is_member", False)
                is_private: bool = channel.get("is_private", False)
                if not chan_id:
                    continue

                # Auto-join public channels; skip private channels the bot isn't in
                if not is_member:
                    if is_private:
                        continue  # Can't join private channels without invite
                    # Try to join the public channel
                    try:
                        join_resp = _slack_api_with_retry(
                            "conversations.join", token, {"channel": chan_id},
                            http_method="POST",
                        )
                        if not join_resp.get("ok"):
                            continue
                    except Exception:
                        continue

                # Step 3: paginate through message history
                history_cursor = ""
                while True:
                    try:
                        history_resp = _slack_api_conversations_history(
                            token, chan_id, cursor=history_cursor
                        )
                    except Exception:
                        break  # Skip channels we can't read
                    if not history_resp.get("ok", True):
                        break  # not_in_channel or other error
                    messages: List[Dict[str, Any]] = history_resp.get("messages", [])

                    for msg in messages:
                        # Skip bot messages and non-content subtypes
                        if msg.get("bot_id") or msg.get("subtype") in (
                            "message_changed",
                            "message_deleted",
                            "bot_message",
                            "channel_join",
                            "channel_leave",
                        ):
                            continue

                        ts: str = msg.get("ts", "")
                        user_id: str = msg.get("user", "")
                        text: str = msg.get("text", "")
                        thread_ts: Optional[str] = msg.get("thread_ts")

                        user_info = user_map.get(user_id, {})
                        author = user_info.get("name", user_id)

                        timestamp = _ts_to_datetime(ts)
                        url = _slack_archive_url("", chan_id, ts)

                        doc = Document(
                            doc_id=f"slack:{chan_id}:{ts}",
                            source="slack",
                            doc_type="message",
                            content=text,
                            title=f"#{chan_name}",
                            author=author,
                            timestamp=timestamp,
                            thread_id=thread_ts,
                            url=url,
                            metadata={
                                "channel_id": chan_id,
                                "channel_name": chan_name,
                                "user_id": user_id,
                                "ts": ts,
                            },
                        )
                        synced += 1
                        yield doc

                    next_history_cursor: str = (
                        history_resp.get("response_metadata", {}).get("next_cursor", "")
                        or ""
                    )
                    if not history_resp.get("has_more") or not next_history_cursor:
                        break
                    history_cursor = next_history_cursor

            next_channels_cursor: str = (
                channels_resp.get("response_metadata", {}).get("next_cursor", "") or ""
            )
            if not next_channels_cursor:
                self._last_cursor = None
                break
            channels_cursor = next_channels_cursor
            self._last_cursor = channels_cursor

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
        """Expose three MCP tool specs for real-time Slack queries."""
        return [
            ToolSpec(
                name="slack_search_messages",
                description=(
                    "Search Slack messages using a query string. "
                    "Returns matching messages across all accessible channels."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query string",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of messages to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="communication",
            ),
            ToolSpec(
                name="slack_get_thread",
                description=(
                    "Retrieve all messages in a Slack thread by channel ID "
                    "and thread timestamp."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "channel_id": {
                            "type": "string",
                            "description": "Slack channel ID",
                        },
                        "thread_ts": {
                            "type": "string",
                            "description": (
                                "Thread timestamp (ts of the parent message)"
                            ),
                        },
                    },
                    "required": ["channel_id", "thread_ts"],
                },
                category="communication",
            ),
            ToolSpec(
                name="slack_list_channels",
                description=(
                    "List accessible Slack channels, optionally filtered by type."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "types": {
                            "type": "string",
                            "description": (
                                "Comma-separated channel types to include "
                                "(e.g. 'public_channel,private_channel')"
                            ),
                            "default": "public_channel,private_channel",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of channels to return",
                            "default": 100,
                        },
                    },
                    "required": [],
                },
                category="communication",
            ),
        ]
