"""Google Contacts connector — bulk contact sync via the People REST API v1.

Uses OAuth 2.0 tokens stored locally (see :mod:`openjarvis.connectors.oauth`).
All network calls are isolated in module-level functions (``_gcontacts_api_*``)
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

_GCONTACTS_API_BASE = "https://people.googleapis.com/v1"
_GCONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "gcontacts.json")

# ---------------------------------------------------------------------------
# Module-level API functions (easy to patch in tests)
# ---------------------------------------------------------------------------


def _gcontacts_api_list(
    token: str,
    *,
    page_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Call the People API ``people/me/connections`` endpoint.

    Parameters
    ----------
    token:
        OAuth access token.
    page_token:
        Pagination token from a previous response's ``nextPageToken``.

    Returns
    -------
    dict
        Raw API response containing a ``connections`` list and optional
        ``nextPageToken``.
    """
    params: Dict[str, Any] = {
        "personFields": "names,emailAddresses,phoneNumbers,organizations",
        "pageSize": 100,
    }
    if page_token:
        params["pageToken"] = page_token

    resp = httpx.get(
        f"{_GCONTACTS_API_BASE}/people/me/connections",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _format_contact(person: Dict[str, Any]) -> str:
    """Return a human-readable text representation of a contact.

    Parameters
    ----------
    person:
        Raw person resource dict from the People API.

    Returns
    -------
    str
        Multi-line formatted text suitable for indexing.
    """
    lines: List[str] = []

    # Name
    names: List[Dict[str, Any]] = person.get("names", [])
    display_name = names[0].get("displayName", "") if names else ""
    if display_name:
        lines.append(f"Name: {display_name}")

    # Email addresses
    email_addresses: List[Dict[str, Any]] = person.get("emailAddresses", [])
    for email_entry in email_addresses:
        value = email_entry.get("value", "")
        if value:
            lines.append(f"Email: {value}")

    # Phone numbers
    phone_numbers: List[Dict[str, Any]] = person.get("phoneNumbers", [])
    for phone_entry in phone_numbers:
        value = phone_entry.get("value", "")
        if value:
            lines.append(f"Phone: {value}")

    # Organizations
    organizations: List[Dict[str, Any]] = person.get("organizations", [])
    for org_entry in organizations:
        org_name = org_entry.get("name", "")
        title = org_entry.get("title", "")
        if org_name:
            lines.append(f"Organization: {org_name}")
        if title:
            lines.append(f"Title: {title}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GContactsConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("gcontacts")
class GContactsConnector(BaseConnector):
    """Connector that syncs contacts from Google Contacts via the People API v1.

    Authentication is handled through Google OAuth 2.0.  Tokens are stored
    locally in a JSON credentials file.

    Parameters
    ----------
    credentials_path:
        Path to the JSON file where OAuth tokens are stored.  Defaults to
        ``~/.openjarvis/connectors/gcontacts.json``.
    """

    connector_id = "gcontacts"
    display_name = "Google Contacts"
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
        """Return a Google OAuth consent URL requesting ``contacts.readonly`` scope."""
        tokens = load_tokens(self._credentials_path)
        client_id = ""
        if tokens:
            client_id = tokens.get("client_id", "")
        if not client_id:
            return "https://console.cloud.google.com/apis/credentials"
        return build_google_auth_url(
            client_id=client_id,
            scopes=[_GCONTACTS_SCOPE],
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
                        scopes=[_GCONTACTS_SCOPE],
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
        """Yield :class:`Document` objects for Google Contacts.

        Paginates through the people/me/connections endpoint and converts
        each person resource into a Document.

        Parameters
        ----------
        since:
            Not yet used (People API does not support server-side date filtering
            for connections).
        cursor:
            ``nextPageToken`` from a previous sync to resume pagination.
        """
        tokens = load_tokens(self._credentials_path)
        if not tokens:
            return

        token: str = tokens.get("access_token", tokens.get("token", ""))
        if not token:
            return

        page_token: Optional[str] = cursor
        synced = 0

        while True:
            list_resp = _gcontacts_api_list(token, page_token=page_token)
            connections: List[Dict[str, Any]] = list_resp.get("connections", [])

            for person in connections:
                resource_name: str = person.get("resourceName", "")
                if not resource_name:
                    continue

                names: List[Dict[str, Any]] = person.get("names", [])
                display_name = names[0].get("displayName", "") if names else ""

                email_addresses: List[Dict[str, Any]] = person.get("emailAddresses", [])
                primary_email = (
                    email_addresses[0].get("value", "") if email_addresses else ""
                )

                content = _format_contact(person)

                doc = Document(
                    doc_id=f"gcontacts:{resource_name}",
                    source="gcontacts",
                    doc_type="contact",
                    content=content,
                    title=display_name,
                    author=primary_email,
                    metadata={
                        "resource_name": resource_name,
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
        """Expose two MCP tool specs for real-time Google Contacts queries."""
        return [
            ToolSpec(
                name="contacts_find",
                description=(
                    "Search Google Contacts by name, email, or organization. "
                    "Returns matching contacts with their email addresses, "
                    "phone numbers, and organization details."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Search term to match against contact name, "
                                "email address, or organization"
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of contacts to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="communication",
            ),
            ToolSpec(
                name="contacts_get_info",
                description=(
                    "Retrieve full details for a specific Google Contact by "
                    "their resource name or email address. Returns all available "
                    "fields including phone numbers, organization, and title."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "identifier": {
                            "type": "string",
                            "description": (
                                "Contact resource name (e.g. 'people/c123') "
                                "or email address"
                            ),
                        },
                    },
                    "required": ["identifier"],
                },
                category="communication",
            ),
        ]
