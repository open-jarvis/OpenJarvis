"""Granola connector — syncs meeting notes via the Granola public API.

Uses an API key (Bearer token) stored locally.  All network calls are
isolated in module-level functions (``_granola_api_*``) to make them
trivially mockable in tests.

Users create an API key in the Granola desktop app under
Settings → API (requires Business or Enterprise plan).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

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

_GRANOLA_API_BASE = "https://public-api.granola.ai"
_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "granola.json")

# ---------------------------------------------------------------------------
# Module-level API functions (easy to patch in tests)
# ---------------------------------------------------------------------------


def _granola_api_list_notes(
    api_key: str,
    *,
    cursor: Optional[str] = None,
    created_after: Optional[str] = None,
) -> Dict[str, Any]:
    """Call the Granola ``GET /v1/notes`` endpoint.

    Parameters
    ----------
    api_key:
        Granola API key (Bearer token).
    cursor:
        Pagination cursor from a previous response.
    created_after:
        ISO 8601 datetime string; only notes created after this time are
        returned.

    Returns
    -------
    dict
        Raw API response containing ``notes`` list, ``hasMore`` flag, and
        optional ``cursor``.
    """
    params: Dict[str, Any] = {"page_size": 30}
    if cursor:
        params["cursor"] = cursor
    if created_after:
        params["created_after"] = created_after

    resp = httpx.get(
        f"{_GRANOLA_API_BASE}/v1/notes",
        headers={"Authorization": f"Bearer {api_key}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


class GranolaKeyError(ValueError):
    """Raised when a Granola API key is missing or rejected by the API.

    Surfaced through the ``/connect`` endpoint as an HTTP 400 so the user
    sees why the key was refused instead of a silent failed sync later.
    """


def _granola_api_validate_key(api_key: str) -> None:
    """Verify an API key with a minimal ``GET /v1/notes?limit=1`` probe.

    Raises :class:`GranolaKeyError` when the key is empty or the API
    responds 401/403, so an invalid key never overwrites a working
    credential on disk. Other HTTP errors propagate via ``raise_for_status``.
    """
    if not api_key:
        raise GranolaKeyError("Granola API key is empty.")
    try:
        resp = httpx.get(
            f"{_GRANOLA_API_BASE}/v1/notes",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"limit": 1},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise GranolaKeyError(
            f"Could not reach Granola to verify the key: {exc}"
        ) from exc
    if resp.status_code in (401, 403):
        raise GranolaKeyError(
            "Invalid API key. Check your key in Granola Settings → API."
        )
    resp.raise_for_status()


def _granola_api_get_note(api_key: str, note_id: str) -> Dict[str, Any]:
    """Fetch a single Granola note by ID (includes transcript).

    Parameters
    ----------
    api_key:
        Granola API key (Bearer token).
    note_id:
        Note ID matching pattern ``not_[a-zA-Z0-9]{14}``.

    Returns
    -------
    dict
        Raw API response for the note resource including summary and
        transcript.
    """
    resp = httpx.get(
        f"{_GRANOLA_API_BASE}/v1/notes/{note_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"include": "transcript"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Content formatting helper
# ---------------------------------------------------------------------------


def _format_note_content(note: Dict[str, Any]) -> str:
    """Build a markdown string combining the note summary and transcript.

    Parameters
    ----------
    note:
        Full note object as returned by :func:`_granola_api_get_note`.

    Returns
    -------
    str
        Formatted markdown with ``## Summary`` and ``## Transcript`` sections.
    """
    parts: List[str] = []

    # Summary section
    summary_markdown: str = (note.get("summary", {}) or {}).get("markdown", "")
    parts.append("## Summary")
    parts.append(summary_markdown)

    # Transcript section
    transcript: List[Dict[str, Any]] = note.get("transcript") or []
    parts.append("")
    parts.append("## Transcript")
    if transcript:
        for turn in transcript:
            raw_speaker = turn.get("speaker", "unknown")
            # API may return speaker as dict {"source": "microphone"}
            if isinstance(raw_speaker, dict):
                speaker = raw_speaker.get("source", "unknown")
            else:
                speaker = str(raw_speaker)
            text: str = turn.get("text", "")
            parts.append(f"**{speaker}:** {text}")
    # (empty transcript → section header with no turns is fine)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# ISO datetime parser
# ---------------------------------------------------------------------------


def _parse_iso_datetime(dt_str: str) -> datetime:
    """Parse an ISO 8601 datetime string into a :class:`~datetime.datetime`.

    Falls back to UTC now if the string is missing or unparseable.
    """
    if not dt_str:
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# GranolaConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("granola")
class GranolaConnector(BaseConnector):
    """Connector that syncs meeting notes from Granola via the public REST API.

    Authentication uses an API key created in the Granola desktop app
    (Settings → API, requires Business or Enterprise plan).  The key is
    stored locally in a JSON credentials file.

    Parameters
    ----------
    api_key:
        Granola API key.  If provided, it takes priority over any stored
        credentials file.
    credentials_path:
        Path to the JSON file where the API key is stored.  Defaults to
        ``~/.openjarvis/connectors/granola.json``.
    """

    connector_id = "granola"
    display_name = "Granola"
    auth_type = "oauth"  # API key, same credential-storage pattern as OAuth

    def __init__(
        self,
        api_key: str = "",
        credentials_path: str = "",
    ) -> None:
        self._api_key: str = api_key
        self._credentials_path: str = credentials_path or _DEFAULT_CREDENTIALS_PATH
        self._items_synced: int = 0
        self._items_total: int = 0
        self._last_sync: Optional[datetime] = None
        self._last_cursor: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal key resolution
    # ------------------------------------------------------------------

    def _resolve_api_key(self) -> str:
        """Return the active API key — direct > credentials file."""
        if self._api_key:
            return self._api_key
        tokens = load_tokens(self._credentials_path)
        if tokens:
            return tokens.get("token", "")
        return ""

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return ``True`` if a valid API key is available."""
        return bool(self._resolve_api_key())

    def disconnect(self) -> None:
        """Clear the in-memory API key and delete the stored credentials file."""
        self._api_key = ""
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        """Return the URL where users can create a Granola API key.

        Users must open the Granola desktop app and navigate to
        Settings → API to generate their key.
        """
        return (
            "https://www.granola.ai — open the Granola desktop app and go to "
            "Settings → API to create your API key "
            "(Business or Enterprise plan required)."
        )

    def handle_callback(self, code: str) -> None:
        """Validate and persist the API key.

        The *code* parameter holds the raw API key string provided by the
        user. The key is verified with a live ``GET /v1/notes?limit=1``
        probe *before* it is written, so an invalid key can never overwrite
        a working credential on disk (raises :class:`GranolaKeyError` on a
        401/403).
        """
        _granola_api_validate_key(code)
        save_tokens(self._credentials_path, {"token": code})

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        """Yield :class:`Document` objects for Granola meeting notes.

        Paginates through ``GET /v1/notes`` and fetches each note's full
        content (summary + transcript) via ``GET /v1/notes/{id}``.

        Parameters
        ----------
        since:
            If provided, only notes created after this datetime are returned
            (passed as ``created_after`` to the API).
        cursor:
            Pagination cursor from a previous sync to resume paginating.
        """
        api_key = self._resolve_api_key()
        if not api_key:
            return

        # Convert since to ISO string if provided.
        # Granola API requires ISO 8601 with Z suffix (not +00:00).
        created_after: Optional[str] = None
        if since is not None:
            if since.tzinfo is not None:
                since = since.replace(tzinfo=None)
            created_after = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        page_cursor: Optional[str] = cursor
        synced = 0

        while True:
            list_resp = _granola_api_list_notes(
                api_key,
                cursor=page_cursor,
                created_after=created_after,
            )
            notes: List[Dict[str, Any]] = list_resp.get("notes", [])
            logger.info("Granola: Found %d notes on this page", len(notes))

            for note_summary in notes:
                note_id: str = note_summary.get("id", "")
                if not note_id:
                    continue

                # Fetch full note with transcript
                note = _granola_api_get_note(api_key, note_id)

                title: str = note.get("title", "")
                owner: Dict[str, Any] = note.get("owner") or {}
                author: str = (owner.get("email") or "").lower()

                attendees: List[Dict[str, Any]] = note.get("attendees") or []
                participants: List[str] = [
                    (a.get("email") or "").lower() for a in attendees if a.get("email")
                ]
                participants_raw: List[str] = [
                    a.get("name") or a.get("email") or ""
                    for a in attendees
                    if a.get("name") or a.get("email")
                ]

                created_at_str: str = note.get("created_at", "")
                timestamp = _parse_iso_datetime(created_at_str)

                content = _format_note_content(note)

                cal_event: Dict[str, Any] = note.get("calendar_event") or {}
                channel: str = cal_event.get("event_title") or "meeting"

                # ``web_url`` (e.g. https://notes.granola.ai/d/{uuid}) is the
                # only reliable way to deep-link to a Granola note — the API
                # ``note_id`` and the web UUID are different, so we must store
                # what the API gives us here.
                web_url: Optional[str] = note.get("web_url") or None

                doc = Document(
                    doc_id=f"granola:{note_id}",
                    source="granola",
                    doc_type="document",
                    content=content,
                    title=title,
                    author=author,
                    participants=participants,
                    participants_raw=participants_raw,
                    channel=channel,
                    thread_id=note_id,
                    timestamp=timestamp,
                    url=web_url,
                    metadata={
                        "note_id": note_id,
                        "owner_name": owner.get("name", ""),
                        "updated_at": note.get("updated_at", ""),
                    },
                )
                synced += 1
                yield doc

            has_more: bool = list_resp.get("hasMore", False)
            if not has_more:
                self._last_cursor = None
                break
            page_cursor = list_resp.get("cursor")
            self._last_cursor = page_cursor

        self._items_synced = synced
        self._last_sync = datetime.now(tz=timezone.utc)
        logger.info("Granola: Sync complete, %d notes total", synced)

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
        """Expose two MCP tool specs for real-time Granola queries."""
        return [
            ToolSpec(
                name="granola_search_notes",
                description=(
                    "Search Granola meeting notes by keyword or topic. "
                    "Returns matching note titles, attendees, and summaries."
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
                            "description": "Maximum number of notes to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="knowledge",
            ),
            ToolSpec(
                name="granola_get_note",
                description=(
                    "Retrieve the full content of a Granola meeting note by its ID, "
                    "including the summary and transcript."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "note_id": {
                            "type": "string",
                            "description": "Granola note ID (e.g. not_abc12345678901)",
                        },
                    },
                    "required": ["note_id"],
                },
                category="knowledge",
            ),
        ]
