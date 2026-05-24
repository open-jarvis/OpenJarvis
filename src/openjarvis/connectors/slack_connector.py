"""Slack connector — bulk channel message sync via the Slack Web API.

Uses a Slack **user** OAuth token (``xoxp-...``) stored locally so the
sync sees everything the user can see — including their 1:1 DMs and
multi-person DMs with other humans. A bot token (``xoxb-``) cannot see
user-to-user DMs (Slack platform constraint), so this connector
explicitly rejects bot tokens with a clear error at connect time.

All network calls are isolated in module-level functions
(``_slack_api_*``) to make them trivially mockable in tests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlencode

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import delete_tokens, load_tokens, save_tokens
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SLACK_API_BASE = "https://slack.com/api"
_SLACK_AUTH_ENDPOINT = "https://slack.com/oauth/v2/authorize"
# User Token Scopes — Slack distinguishes user_scope (xoxp-) from scope
# (xoxb-) on the OAuth authorize URL. We only request user scopes; passed
# via ``user_scope`` so the install grants a User OAuth Token.
_SLACK_USER_SCOPES = (
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
    # Include every conversation type the bot can list — public + private
    # channels, multi-person DMs, and 1:1 DMs — so a "connect and sync"
    # flow indexes everything the token has access to without the user
    # picking channels (matches Gmail's connect-and-go behavior).
    params: Dict[str, str] = {
        "types": "public_channel,private_channel,mpim,im",
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


def _slack_api_auth_test(token: str) -> Dict[str, Any]:
    """Call the Slack ``auth.test`` endpoint.

    Returns workspace context (``team_id``, ``team``, ``url``) used to
    construct message permalinks — the workspace subdomain isn't carried
    by any other endpoint we already call.
    """
    return _slack_api_with_retry("auth.test", token)


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


class SlackTokenError(ValueError):
    """Raised when the stored Slack token isn't a usable user token.

    Surfaced via :class:`SyncStatus.error` so the UI can render the actual
    reason (e.g. ``xoxb-`` bot token rejected) instead of an empty sync.
    """


_USER_TOKEN_PREFIX = "xoxp-"
_BOT_TOKEN_PREFIX = "xoxb-"


def _validate_user_token(token: str) -> None:
    """Raise :class:`SlackTokenError` unless *token* looks like a user token.

    Slack user tokens start with ``xoxp-``. We refuse ``xoxb-`` bot tokens
    explicitly because a bot can only see DMs *to/from itself* — paste a
    bot token and your sync silently misses every human-to-human DM. The
    error message tells the user exactly which token type to provide and
    where to find it.
    """
    if not token:
        raise SlackTokenError("Slack token is empty.")
    if token.startswith(_BOT_TOKEN_PREFIX):
        raise SlackTokenError(
            "Bot tokens (xoxb-) can't read DMs. "
            "Use a User OAuth Token (xoxp-) instead."
        )
    if not token.startswith(_USER_TOKEN_PREFIX):
        raise SlackTokenError(
            "Invalid token format. Expected a Slack User OAuth Token "
            "starting with xoxp-"
        )


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


def _team_domain_from_auth(auth_resp: Dict[str, Any]) -> str:
    """Derive the workspace subdomain ('acme' from 'https://acme.slack.com/').

    Falls back to the ``team_id`` so doc_ids stay non-empty when the
    workspace ``url`` is missing — losing the workspace breaks permalinks
    but lets ingestion continue.
    """
    workspace_url: str = (auth_resp.get("url") or "").rstrip("/")
    if workspace_url:
        host = workspace_url.split("//", 1)[-1].split("/", 1)[0]
        suffix = ".slack.com"
        if host.endswith(suffix):
            return host[: -len(suffix)]
    return auth_resp.get("team_id", "") or ""


def _slack_archive_url(team_domain: str, channel_id: str, ts: str) -> str:
    """Build a Slack message permalink for ``team_domain``/``channel``/``ts``.

    With a workspace subdomain the link resolves directly; without one we
    fall back to ``slack.com/archives/...`` which Slack redirects only for
    logged-in members of that workspace.
    """
    ts_clean = ts.replace(".", "")
    if team_domain:
        return f"https://{team_domain}.slack.com/archives/{channel_id}/p{ts_clean}"
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
        # Surfaced via sync_status().error so the UI can render the actual
        # failure reason (typically a bot-token-rejection) instead of a
        # silent "synced 0 messages".
        self._last_error: Optional[str] = None

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
        """Return a Slack OAuth consent URL requesting user-token scopes.

        Uses ``user_scope`` (not ``scope``) so the install grants a User
        OAuth Token (``xoxp-``) — bot tokens (``xoxb-``) can't see human-
        to-human DMs and are rejected by :func:`handle_callback`.
        """
        params = {
            "client_id": "",  # placeholder — real client_id from config
            "user_scope": _SLACK_USER_SCOPES,
            "redirect_uri": "http://localhost:8789/callback",
        }
        return f"{_SLACK_AUTH_ENDPOINT}?{urlencode(params)}"

    def handle_callback(self, code: str) -> None:
        """Validate and persist a supplied User OAuth Token.

        The connector ``/connect`` endpoint funnels manually-pasted tokens
        through this method (the parameter is named ``code`` for OAuth-flow
        compatibility). The token is checked two ways before it is allowed
        to touch disk, so an invalid credential never overwrites a working
        one:

        1. **Shape** — must start with ``xoxp-`` (``xoxb-`` bot tokens and
           any other prefix are rejected via :func:`_validate_user_token`).
        2. **Liveness** — a live ``auth.test`` call must return ``ok`` so an
           expired or revoked token is caught at connect time.
        """
        _validate_user_token(code)

        # Verify the token actually works against Slack before persisting.
        try:
            auth_resp = _slack_api_auth_test(code)
        except Exception as exc:  # noqa: BLE001 — surface as a token error
            raise SlackTokenError(
                f"Could not verify the Slack token (auth.test failed: {exc})."
            ) from exc
        if not auth_resp.get("ok", False):
            err = str(auth_resp.get("error", "auth_failed"))
            raise SlackTokenError(
                f"Slack rejected the token (auth.test: {err}). "
                "Check that it is a current User OAuth Token."
            )

        save_tokens(self._credentials_path, {"token": code})
        self._last_error = None

    def sync(
        self,
        *,
        since: Optional[datetime] = None,  # noqa: ARG002 — reserved for future use
        cursor: Optional[str] = None,  # noqa: ARG002 — reserved for future use
    ) -> Iterator[Document]:
        """Yield :class:`Document` objects for every accessible Slack message.

        With a user OAuth token (``xoxp-``) the listing returned by
        ``conversations.list`` already reflects what the user can see —
        no ``conversations.join`` step, no membership filtering. We
        enumerate every conversation first (so the per-type count can
        be logged up front), then stream history for each one.

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

        # Reject bot tokens up front so the user sees the actual reason
        # for an empty sync instead of every API call coming back
        # missing_scope / 0 messages.
        try:
            _validate_user_token(token)
        except SlackTokenError as exc:
            self._last_error = str(exc)
            logger.warning("Slack sync rejected token: %s", exc)
            return

        # Step 0: resolve workspace context — the subdomain is needed for
        # message permalinks and is the only piece of state that doesn't
        # come back from conversations.history. Done once per sync.
        try:
            auth_resp = _slack_api_auth_test(token)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Slack auth.test failed: %s", exc)
            auth_resp = {}
        if not auth_resp.get("ok", True):
            err = str(auth_resp.get("error", "auth_failed"))
            self._last_error = f"Slack auth.test failed: {err}"
            logger.warning("Slack auth.test returned not-ok: %s", err)
            return

        team_domain: str = _team_domain_from_auth(auth_resp)
        team_id: str = auth_resp.get("team_id", "") or ""
        workspace_name: str = auth_resp.get("team", "") or ""
        workspace_url: str = auth_resp.get("url", "") or ""

        # Step 1: build user map (so DMs render with peer names, not IDs)
        users_resp = _slack_api_users_list(token)
        members: List[Dict[str, Any]] = users_resp.get("members", [])
        user_map = _build_user_map(members)

        # Step 2: enumerate every conversation up front so we can log a
        # per-type summary before fetching history. Pagination over
        # conversations.list is cheap relative to history fetch and gives
        # the user (and the logs) immediate signal about what the token
        # can actually see.
        all_channels: List[Dict[str, Any]] = []
        channels_cursor = ""
        while True:
            channels_resp = _slack_api_conversations_list(
                token, cursor=channels_cursor
            )
            if not channels_resp.get("ok", True):
                err = str(channels_resp.get("error", "list_failed"))
                self._last_error = f"Slack conversations.list failed: {err}"
                logger.warning("Slack conversations.list returned not-ok: %s", err)
                return
            all_channels.extend(channels_resp.get("channels", []))
            channels_cursor = (
                channels_resp.get("response_metadata", {}).get("next_cursor", "")
                or ""
            )
            if not channels_cursor:
                break

        counts = {"public_channel": 0, "private_channel": 0, "im": 0, "mpim": 0}
        for c in all_channels:
            if c.get("is_im"):
                counts["im"] += 1
            elif c.get("is_mpim"):
                counts["mpim"] += 1
            elif c.get("is_private"):
                counts["private_channel"] += 1
            else:
                counts["public_channel"] += 1
        logger.info(
            "Slack: Found %d public channels, %d private channels, "
            "%d DMs, %d group DMs",
            counts["public_channel"],
            counts["private_channel"],
            counts["im"],
            counts["mpim"],
        )

        # Step 3: fetch history per channel and yield Documents.
        synced = 0
        for channel in all_channels:
            chan_id: str = channel.get("id", "")
            is_private: bool = channel.get("is_private", False)
            is_im: bool = channel.get("is_im", False)
            is_mpim: bool = channel.get("is_mpim", False)
            if not chan_id:
                continue

            # Display name: IMs have no ``name`` field — render as
            # ``dm-<peer-name>`` so result chips show something readable.
            raw_name: str = channel.get("name", "") or ""
            if is_im:
                peer_id: str = channel.get("user", "") or ""
                peer_info = user_map.get(peer_id, {})
                peer_label = peer_info.get("name") or peer_id or "user"
                chan_name = f"dm-{peer_label}"
            else:
                chan_name = raw_name or chan_id

            channel_type = (
                "im"
                if is_im
                else "mpim"
                if is_mpim
                else "private_channel"
                if is_private
                else "public_channel"
            )

            history_cursor = ""
            while True:
                try:
                    history_resp = _slack_api_conversations_history(
                        token, chan_id, cursor=history_cursor
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Slack history fetch failed for %s (%s): %s",
                        chan_name,
                        chan_id,
                        exc,
                    )
                    break
                if not history_resp.get("ok", True):
                    # User token shouldn't hit not_in_channel, but if a
                    # scope was revoked mid-sync we skip the channel rather
                    # than abort the whole sync.
                    logger.debug(
                        "Slack history not-ok for %s (%s): %s",
                        chan_name,
                        chan_id,
                        history_resp.get("error"),
                    )
                    break
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
                    author_name: str = user_info.get("name", user_id)
                    author_email: str = user_info.get("email", "")

                    timestamp = _ts_to_datetime(ts)
                    url = _slack_archive_url(team_domain, chan_id, ts)

                    # v1 schema participants: lowercase email when we have
                    # one, else the display name — matches the Gmail
                    # connector's contract (one identity per participant)
                    # so cross-source queries work.
                    canonical = (author_email or author_name).lower()
                    participants = [canonical] if canonical else []
                    participants_raw = [user_id] if user_id else []

                    # Encode workspace into doc_id so research_loop can
                    # rebuild a workspace-qualified permalink from
                    # source + document_id alone.
                    doc_id = f"slack:{team_domain}:{chan_id}:{ts}"

                    # Channel rows get ``#name``; DM rows get
                    # ``DM with <peer>`` (more useful than ``#dm-alice``
                    # in result chips).
                    if is_im:
                        title = f"DM with {chan_name.removeprefix('dm-')}"
                    else:
                        title = f"#{chan_name}"

                    doc = Document(
                        doc_id=doc_id,
                        source="slack",
                        doc_type="message",
                        content=text,
                        title=title,
                        author=author_email or author_name,
                        participants=participants,
                        participants_raw=participants_raw,
                        timestamp=timestamp,
                        thread_id=thread_ts,
                        channel=chan_name,
                        url=url,
                        metadata={
                            "channel_id": chan_id,
                            "channel_name": chan_name,
                            "channel_type": channel_type,
                            "user_id": user_id,
                            "ts": ts,
                            "team_id": team_id,
                            "team_domain": team_domain,
                            "workspace_name": workspace_name,
                            "workspace_url": workspace_url,
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

        self._items_synced = synced
        self._last_sync = datetime.now()
        self._last_cursor = None
        self._last_error = None

    def sync_status(self) -> SyncStatus:
        """Return sync progress from the most recent :meth:`sync` call."""
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            last_sync=self._last_sync,
            cursor=self._last_cursor,
            error=self._last_error,
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
