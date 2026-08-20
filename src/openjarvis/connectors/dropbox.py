"""Dropbox connector — bulk file sync via the Dropbox API v2.

Uses OAuth Bearer tokens stored locally.
All network calls are isolated in module-level functions (``_dropbox_api_*``)
to make them trivially mockable in tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import delete_tokens, load_tokens, save_tokens
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DROPBOX_API_BASE = "https://api.dropboxapi.com/2"
_DROPBOX_CONTENT_BASE = "https://content.dropboxapi.com/2"
_DROPBOX_AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
_DROPBOX_SCOPES = ["files.metadata.read", "files.content.read"]
_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "dropbox.json")

# File extensions whose content can be downloaded and stored as text
_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".htm",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".rst",
    ".sh",
    ".log",
}

# ---------------------------------------------------------------------------
# Module-level API functions (easy to patch in tests)
# ---------------------------------------------------------------------------


def _dropbox_api_list_folder(
    token: str,
    *,
    path: str = "",
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """Call the Dropbox ``files/list_folder`` (or ``/continue``) endpoint.

    Parameters
    ----------
    token:
        OAuth Bearer access token.
    path:
        Dropbox path to list.  Use ``""`` (empty string) for the root.
    cursor:
        Pagination cursor from a previous response; if provided, calls
        ``files/list_folder/continue`` instead.

    Returns
    -------
    dict
        Raw API response containing ``entries``, ``cursor``, and
        ``has_more``.
    """
    if cursor is not None:
        resp = httpx.post(
            f"{_DROPBOX_API_BASE}/files/list_folder/continue",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"cursor": cursor},
            timeout=30.0,
        )
    else:
        resp = httpx.post(
            f"{_DROPBOX_API_BASE}/files/list_folder",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"path": path, "recursive": True},
            timeout=30.0,
        )
    resp.raise_for_status()
    return resp.json()


def _dropbox_api_download(token: str, path: str) -> str:
    """Download a file from Dropbox and return its content as a string.

    Parameters
    ----------
    token:
        OAuth Bearer access token.
    path:
        Dropbox path of the file to download.

    Returns
    -------
    str
        File content decoded as UTF-8.
    """
    import json as _json

    resp = httpx.post(
        f"{_DROPBOX_CONTENT_BASE}/files/download",
        headers={
            "Authorization": f"Bearer {token}",
            "Dropbox-API-Arg": _json.dumps({"path": path}),
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# DropboxConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("dropbox")
class DropboxConnector(BaseConnector):
    """Connector that syncs files from Dropbox via the REST API v2.

    Authentication is handled through Dropbox OAuth 2.0.  Tokens are stored
    locally in a JSON credentials file.

    Parameters
    ----------
    credentials_path:
        Path to the JSON file where OAuth tokens are stored.  Defaults to
        ``~/.openjarvis/connectors/dropbox.json``.
    """

    connector_id = "dropbox"
    display_name = "Dropbox"
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
        """Return a Dropbox OAuth consent URL requesting file access scopes."""
        from urllib.parse import urlencode

        params = {
            "client_id": "",  # placeholder — real client_id from config
            "response_type": "code",
            "token_access_type": "offline",
            "scope": " ".join(_DROPBOX_SCOPES),
        }
        return f"{_DROPBOX_AUTH_URL}?{urlencode(params)}"

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
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        """Yield :class:`Document` objects for Dropbox files.

        Lists all files recursively.  Text-extractable files (.txt, .md,
        .csv, .py, etc.) are downloaded and stored with their content.
        Other files are stored as metadata-only documents.

        Parameters
        ----------
        since:
            Not yet used (reserved for future incremental sync).
        cursor:
            Dropbox list_folder cursor from a previous sync to resume
            pagination.
        """
        tokens = load_tokens(self._credentials_path)
        if not tokens:
            return

        token: str = tokens.get("token", tokens.get("access_token", ""))
        if not token:
            return

        list_cursor: Optional[str] = cursor
        synced = 0
        entries_seen: int = 0

        while True:
            list_resp = _dropbox_api_list_folder(token, path="", cursor=list_cursor)
            entries: List[Dict[str, Any]] = list_resp.get("entries", [])
            entries_seen += len(entries)

            for entry in entries:
                tag: str = entry.get(".tag", "")
                if tag != "file":
                    # Skip folders / deleted entries
                    continue

                name: str = entry.get("name", "")
                path_lower: str = entry.get("path_lower", "")
                server_modified: str = entry.get("server_modified", "")
                size: int = entry.get("size", 0)

                # Parse timestamp
                try:
                    timestamp = datetime.strptime(
                        server_modified, "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=__import__("datetime").timezone.utc)
                except (ValueError, AttributeError):
                    timestamp = datetime.now()

                # Determine whether the file is text-extractable
                suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if suffix in _TEXT_EXTENSIONS:
                    try:
                        content = _dropbox_api_download(token, path_lower)
                    except Exception:  # noqa: BLE001
                        content = f"[File: {name}]"
                else:
                    content = f"[File: {name}]"

                doc = Document(
                    doc_id=f"dropbox:{path_lower}",
                    source="dropbox",
                    doc_type="document",
                    content=content,
                    title=name,
                    timestamp=timestamp,
                    metadata={
                        "path": path_lower,
                        "size": size,
                    },
                )
                synced += 1
                yield doc

            has_more: bool = list_resp.get("has_more", False)
            next_cursor: Optional[str] = list_resp.get("cursor")
            if not has_more:
                self._last_cursor = next_cursor
                break
            list_cursor = next_cursor

        self._items_synced = synced
        self._items_total = entries_seen
        self._last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        """Return sync progress from the most recent :meth:`sync` call."""
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            items_total=self._items_total,
            last_sync=self._last_sync,
            cursor=self._last_cursor,
        )

    # ------------------------------------------------------------------
    # MCP tools
    # ------------------------------------------------------------------

    def mcp_tools(self) -> List[ToolSpec]:
        """Expose three MCP tool specs for real-time Dropbox queries."""
        return [
            ToolSpec(
                name="dropbox_search_files",
                description=(
                    "Search Dropbox files by filename or content keyword. "
                    "Returns matching files with path and metadata."
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
                            "description": "Maximum number of files to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="productivity",
            ),
            ToolSpec(
                name="dropbox_get_file",
                description=(
                    "Retrieve the full text content of a Dropbox file by its path."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Dropbox file path (e.g. '/notes.md')",
                        },
                    },
                    "required": ["path"],
                },
                category="productivity",
            ),
            ToolSpec(
                name="dropbox_list_recent",
                description=(
                    "List recently modified Dropbox files, "
                    "optionally filtered by file extension."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "extension": {
                            "type": "string",
                            "description": (
                                "Filter by file extension (e.g. '.md', '.txt'). "
                                "Leave empty to list all types."
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
