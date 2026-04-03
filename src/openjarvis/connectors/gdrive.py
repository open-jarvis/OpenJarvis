"""Google Drive connector — bulk file sync via the Drive REST API v3.

Uses OAuth 2.0 tokens stored locally (see :mod:`openjarvis.connectors.oauth`).
All network calls are isolated in module-level functions (``_gdrive_api_*``)
to make them trivially mockable in tests.
"""

from __future__ import annotations

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
    run_oauth_flow,
    save_tokens,
)
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GDRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
_GDRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "gdrive.json")

# Map from Google Workspace MIME types to export MIME types
_EXPORT_MIME_MAP: Dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

# ---------------------------------------------------------------------------
# Module-level API functions (easy to patch in tests)
# ---------------------------------------------------------------------------


def _gdrive_api_list_files(
    token: str,
    *,
    page_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Call the Drive ``files.list`` endpoint.

    Parameters
    ----------
    token:
        OAuth access token.
    page_token:
        Pagination token from a previous response's ``nextPageToken``.

    Returns
    -------
    dict
        Raw API response containing ``files`` list and optional
        ``nextPageToken``.
    """
    _fields = "nextPageToken,files(id,name,mimeType,modifiedTime,owners,webViewLink)"
    params: Dict[str, Any] = {
        "fields": _fields,
        "pageSize": 100,
        "orderBy": "modifiedTime desc",
    }
    if page_token:
        params["pageToken"] = page_token

    resp = httpx.get(
        f"{_GDRIVE_API_BASE}/files",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _gdrive_api_export(token: str, file_id: str, mime_type: str) -> str:
    """Export a Google Workspace file as plain text or CSV.

    Parameters
    ----------
    token:
        OAuth access token.
    file_id:
        The Drive file ID to export.
    mime_type:
        The target MIME type for the export (e.g. ``"text/plain"``).

    Returns
    -------
    str
        Exported file content as a string.
    """
    resp = httpx.get(
        f"{_GDRIVE_API_BASE}/files/{file_id}/export",
        headers={"Authorization": f"Bearer {token}"},
        params={"mimeType": mime_type},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# GDriveConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("gdrive")
class GDriveConnector(BaseConnector):
    """Connector that syncs files from Google Drive via the REST API v3.

    Authentication is handled through Google OAuth 2.0.  Tokens are stored
    locally in a JSON credentials file.

    Parameters
    ----------
    credentials_path:
        Path to the JSON file where OAuth tokens are stored.  Defaults to
        ``~/.openjarvis/connectors/gdrive.json``.
    """

    connector_id = "gdrive"
    display_name = "Google Drive"
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
        """Return a Google OAuth consent URL requesting ``drive.readonly`` scope."""
        tokens = load_tokens(self._credentials_path)
        client_id = ""
        if tokens:
            client_id = tokens.get("client_id", "")
        if not client_id:
            return "https://console.cloud.google.com/apis/credentials"
        return build_google_auth_url(
            client_id=client_id,
            scopes=GOOGLE_ALL_SCOPES,
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
            # Save credentials immediately
            save_tokens(
                self._credentials_path,
                {
                    "client_id": client_id.strip(),
                    "client_secret": client_secret.strip(),
                },
            )
            # Run OAuth flow in background thread to avoid blocking
            import threading

            def _run() -> None:
                try:
                    run_oauth_flow(
                        client_id=client_id.strip(),
                        client_secret=client_secret.strip(),
                        scopes=GOOGLE_ALL_SCOPES,
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
        """Yield :class:`Document` objects for Google Drive files.

        Paginates through the files.list API.  Google Workspace files
        (Docs, Sheets, Slides) are exported as plain text or CSV.
        Non-exportable files are stored as metadata-only documents.

        Parameters
        ----------
        since:
            Not yet used (Drive API filtering is done server-side).
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
            list_resp = _gdrive_api_list_files(token, page_token=page_token)
            files: List[Dict[str, Any]] = list_resp.get("files", [])

            for file_meta in files:
                file_id: str = file_meta.get("id", "")
                if not file_id:
                    continue

                name: str = file_meta.get("name", "")
                mime_type: str = file_meta.get("mimeType", "")
                web_view_link: Optional[str] = file_meta.get("webViewLink")

                # Determine author from first owner
                owners: List[Dict[str, str]] = file_meta.get("owners", [])
                author: str = owners[0].get("displayName", "") if owners else ""

                # Export Google Workspace types; store metadata for others
                export_mime = _EXPORT_MIME_MAP.get(mime_type)
                if export_mime is not None:
                    try:
                        content = _gdrive_api_export(token, file_id, export_mime)
                    except Exception:  # noqa: BLE001
                        content = f"[File: {name}] ({mime_type})"
                else:
                    content = f"[File: {name}] ({mime_type})"

                doc = Document(
                    doc_id=f"gdrive:{file_id}",
                    source="gdrive",
                    doc_type="document",
                    content=content,
                    title=name,
                    author=author,
                    url=web_view_link,
                    metadata={
                        "file_id": file_id,
                        "mime_type": mime_type,
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
        """Expose three MCP tool specs for real-time Google Drive queries."""
        return [
            ToolSpec(
                name="gdrive_search_files",
                description=(
                    "Search Google Drive files using a query string. "
                    "Supports Drive search operators "
                    "(e.g. 'name contains \"report\" type:document')."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Drive search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of files to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="productivity",
            ),
            ToolSpec(
                name="gdrive_get_document",
                description=(
                    "Retrieve the full text content of a Google Drive"
                    " document by file ID."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "file_id": {
                            "type": "string",
                            "description": "Google Drive file ID",
                        },
                    },
                    "required": ["file_id"],
                },
                category="productivity",
            ),
            ToolSpec(
                name="gdrive_list_recent",
                description=(
                    "List recently modified Google Drive files, "
                    "optionally filtered by file type."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "file_type": {
                            "type": "string",
                            "description": (
                                "Filter by Google Workspace type: "
                                "'document', 'spreadsheet', or 'presentation'"
                            ),
                            "default": "",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of files to return",
                            "default": 20,
                        },
                    },
                    "required": [],
                },
                category="productivity",
            ),
        ]
