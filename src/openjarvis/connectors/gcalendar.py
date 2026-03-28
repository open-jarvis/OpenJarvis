"""Google Calendar connector — event sync via the Calendar REST API v3.

Uses OAuth 2.0 tokens stored locally (see :mod:`openjarvis.connectors.oauth`).
All network calls are isolated in module-level functions (``_gcal_api_*``)
to make them trivially mockable in tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import (
    build_google_auth_url,
    delete_tokens,
    load_tokens,
    run_oauth_flow,
    save_tokens,
)
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GCAL_API_BASE = "https://www.googleapis.com/calendar/v3"
_GCAL_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "gcalendar.json")

# ---------------------------------------------------------------------------
# Module-level API functions (easy to patch in tests)
# ---------------------------------------------------------------------------


def _gcal_api_calendars_list(token: str) -> Dict[str, Any]:
    """Call the Calendar ``calendarList.list`` endpoint.

    Parameters
    ----------
    token:
        OAuth access token.

    Returns
    -------
    dict
        Raw API response containing an ``items`` list of calendar resources.
    """
    resp = httpx.get(
        f"{_GCAL_API_BASE}/users/me/calendarList",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _gcal_api_events_list(
    token: str,
    calendar_id: str,
    *,
    page_token: Optional[str] = None,
    time_min: Optional[str] = None,
) -> Dict[str, Any]:
    """Call the Calendar ``events.list`` endpoint for a single calendar.

    Parameters
    ----------
    token:
        OAuth access token.
    calendar_id:
        Calendar identifier (e.g. ``"primary"``).
    page_token:
        Pagination token from a previous response's ``nextPageToken``.
    time_min:
        Lower bound (exclusive) for an event's end time (RFC3339 timestamp).
        When omitted the API returns all events.

    Returns
    -------
    dict
        Raw API response containing an ``items`` list and optional
        ``nextPageToken``.
    """
    params: Dict[str, Any] = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 250,
    }
    if page_token:
        params["pageToken"] = page_token
    if time_min:
        params["timeMin"] = time_min

    resp = httpx.get(
        f"{_GCAL_API_BASE}/calendars/{calendar_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _format_event(event: Dict[str, Any]) -> str:
    """Return a human-readable text representation of a calendar event.

    Parameters
    ----------
    event:
        Raw event resource dict from the Calendar API.

    Returns
    -------
    str
        Multi-line formatted text suitable for indexing.
    """
    lines: List[str] = []

    summary = event.get("summary", "(No title)")
    lines.append(f"Title: {summary}")

    # When
    start = event.get("start", {})
    end = event.get("end", {})
    start_str = start.get("dateTime") or start.get("date", "")
    end_str = end.get("dateTime") or end.get("date", "")
    if start_str or end_str:
        lines.append(f"When: {start_str} – {end_str}")

    # Location
    location = event.get("location", "")
    if location:
        lines.append(f"Location: {location}")

    # Organizer
    organizer = event.get("organizer", {})
    organizer_name = organizer.get("displayName") or organizer.get("email", "")
    if organizer_name:
        lines.append(f"Organizer: {organizer_name}")

    # Attendees
    attendees: List[Dict[str, Any]] = event.get("attendees", [])
    if attendees:
        attendee_names = [a.get("displayName") or a.get("email", "") for a in attendees]
        lines.append(f"Attendees: {', '.join(attendee_names)}")

    # Description
    description = event.get("description", "")
    if description:
        lines.append(f"Description: {description}")

    return "\n".join(lines)


def _parse_event_timestamp(event: Dict[str, Any]) -> datetime:
    """Extract the start datetime from an event resource.

    Falls back to :func:`datetime.now` if the field is missing or unparseable.
    """
    start = event.get("start", {})
    date_time_str: str = start.get("dateTime", "")
    if not date_time_str:
        return datetime.now()
    try:
        # RFC3339 — Python 3.11+ fromisoformat handles the trailing 'Z'.
        # For older versions we replace 'Z' with '+00:00'.
        normalized = date_time_str.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return datetime.now()


# ---------------------------------------------------------------------------
# GCalendarConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("gcalendar")
class GCalendarConnector(BaseConnector):
    """Connector that syncs events from Google Calendar via the REST API v3.

    Authentication is handled through Google OAuth 2.0.  Tokens are stored
    locally in a JSON credentials file.

    Parameters
    ----------
    credentials_path:
        Path to the JSON file where OAuth tokens are stored.  Defaults to
        ``~/.openjarvis/connectors/gcalendar.json``.
    """

    connector_id = "gcalendar"
    display_name = "Google Calendar"
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
        """Return ``True`` if a credentials file with a valid access token exists."""
        tokens = load_tokens(self._credentials_path)
        if tokens is None:
            return False
        # Must have an actual access_token, not just a client_id
        return bool(tokens.get("access_token") or tokens.get("token"))

    def disconnect(self) -> None:
        """Delete the stored credentials file."""
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        """Return a Google OAuth consent URL requesting ``calendar.readonly`` scope."""
        tokens = load_tokens(self._credentials_path)
        client_id = ""
        if tokens:
            client_id = tokens.get("client_id", "")
        if not client_id:
            return "https://console.cloud.google.com/apis/credentials"
        return build_google_auth_url(
            client_id=client_id,
            scopes=[_GCAL_SCOPE],
        )

    def handle_callback(self, code: str) -> None:
        """Handle the OAuth callback.

        If *code* looks like a ``client_id:client_secret`` pair (containing
        ``.apps.googleusercontent.com``), store the credentials and trigger
        the full browser-based OAuth flow.  Otherwise treat it as a raw
        token / auth code.
        """
        code = code.strip()
        # If user pastes client_id:client_secret, store and run OAuth flow
        if ":" in code and ".apps.googleusercontent.com" in code:
            client_id, client_secret = code.split(":", 1)
            save_tokens(
                self._credentials_path,
                {
                    "client_id": client_id.strip(),
                    "client_secret": client_secret.strip(),
                },
            )
            import threading

            def _run() -> None:
                try:
                    run_oauth_flow(
                        client_id=client_id.strip(),
                        client_secret=client_secret.strip(),
                        scopes=[_GCAL_SCOPE],
                        credentials_path=self._credentials_path,
                    )
                except Exception:  # noqa: BLE001
                    pass

            threading.Thread(target=_run, daemon=True).start()
        else:
            # Raw token or auth code
            save_tokens(self._credentials_path, {"token": code})

    def sync(
        self,
        *,
        since: Optional[datetime] = None,  # noqa: ARG002 — reserved for future use
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        """Yield :class:`Document` objects for Google Calendar events.

        Fetches all calendars from the calendarList endpoint, then paginates
        through each calendar's events.

        Parameters
        ----------
        since:
            Not yet used (filtering is done server-side via ``timeMin``).
        cursor:
            ``nextPageToken`` from a previous sync to resume pagination.
        """
        tokens = load_tokens(self._credentials_path)
        if not tokens:
            return

        token: str = tokens.get("access_token", tokens.get("token", ""))
        if not token:
            return

        # Fetch list of calendars
        calendars_resp = _gcal_api_calendars_list(token)
        calendars: List[Dict[str, Any]] = calendars_resp.get("items", [])

        synced = 0

        for calendar in calendars:
            calendar_id: str = calendar.get("id", "")
            if not calendar_id:
                continue

            page_token: Optional[str] = cursor

            while True:
                events_resp = _gcal_api_events_list(
                    token, calendar_id, page_token=page_token
                )
                events: List[Dict[str, Any]] = events_resp.get("items", [])

                for event in events:
                    evt_id: str = event.get("id", "")
                    if not evt_id:
                        continue

                    summary: str = event.get("summary", "")
                    organizer: Dict[str, Any] = event.get("organizer", {})
                    organizer_email: str = organizer.get("email", "")
                    attendees: List[Dict[str, Any]] = event.get("attendees", [])
                    participant_emails: List[str] = [
                        a.get("email", "") for a in attendees if a.get("email")
                    ]
                    timestamp = _parse_event_timestamp(event)
                    html_link: Optional[str] = event.get("htmlLink")

                    content = _format_event(event)

                    doc = Document(
                        doc_id=f"gcalendar:{evt_id}",
                        source="gcalendar",
                        doc_type="event",
                        content=content,
                        title=summary,
                        author=organizer_email,
                        participants=participant_emails,
                        timestamp=timestamp,
                        url=html_link,
                        metadata={
                            "calendar_id": calendar_id,
                            "event_id": evt_id,
                        },
                    )
                    synced += 1
                    yield doc

                next_page: Optional[str] = events_resp.get("nextPageToken")
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
        """Expose three MCP tool specs for real-time Google Calendar queries."""
        return [
            ToolSpec(
                name="calendar_get_events_today",
                description=(
                    "Retrieve all Google Calendar events scheduled for today. "
                    "Returns a list of events with title, time, location, "
                    "and attendees."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "calendar_id": {
                            "type": "string",
                            "description": (
                                "Calendar ID to query. Defaults to 'primary'."
                            ),
                            "default": "primary",
                        },
                    },
                    "required": [],
                },
                category="productivity",
            ),
            ToolSpec(
                name="calendar_search_events",
                description=(
                    "Search Google Calendar events by keyword. "
                    "Matches against event titles, descriptions, and locations."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search term to match against event fields",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of events to return",
                            "default": 20,
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": (
                                "Calendar ID to search. Defaults to 'primary'."
                            ),
                            "default": "primary",
                        },
                    },
                    "required": ["query"],
                },
                category="productivity",
            ),
            ToolSpec(
                name="calendar_next_meeting",
                description=(
                    "Find the next upcoming meeting on the user's Google Calendar. "
                    "Returns title, start time, location, and attendees."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "calendar_id": {
                            "type": "string",
                            "description": (
                                "Calendar ID to query. Defaults to 'primary'."
                            ),
                            "default": "primary",
                        },
                    },
                    "required": [],
                },
                category="productivity",
            ),
        ]
