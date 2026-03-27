"""Notion connector — syncs pages via the Notion REST API.

Uses a Notion internal integration token stored locally.  All network calls
are isolated in module-level functions (``_notion_api_*``) to make them
trivially mockable in tests.

Users create an internal integration at https://www.notion.so/my-integrations
and paste the generated token to authenticate.
"""

from __future__ import annotations

from datetime import datetime, timezone
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

_NOTION_API_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "notion.json")

# ---------------------------------------------------------------------------
# Module-level API functions (easy to patch in tests)
# ---------------------------------------------------------------------------


def _notion_headers(token: str) -> Dict[str, str]:
    """Build the standard Notion API request headers."""
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _notion_api_search(
    token: str,
    *,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """Call the Notion ``/v1/search`` endpoint to list accessible pages.

    Parameters
    ----------
    token:
        Notion integration token.
    cursor:
        Pagination cursor (``start_cursor``) from a previous response.

    Returns
    -------
    dict
        Raw API response containing ``results`` list and ``has_more`` flag.
    """
    body: Dict[str, Any] = {
        "filter": {"property": "object", "value": "page"},
        "page_size": 100,
    }
    if cursor:
        body["start_cursor"] = cursor

    resp = httpx.post(
        f"{_NOTION_API_BASE}/search",
        headers=_notion_headers(token),
        json=body,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _notion_api_get_blocks(token: str, block_id: str) -> List[Dict[str, Any]]:
    """Fetch child blocks for a page (or block) by ID.

    Parameters
    ----------
    token:
        Notion integration token.
    block_id:
        Page or block UUID.

    Returns
    -------
    list[dict]
        List of block objects from the API ``results`` field.
    """
    resp = httpx.get(
        f"{_NOTION_API_BASE}/blocks/{block_id}/children",
        headers=_notion_headers(token),
        params={"page_size": 100},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


# ---------------------------------------------------------------------------
# Block-to-markdown renderer
# ---------------------------------------------------------------------------


def _extract_rich_text(block_data: Dict[str, Any]) -> str:
    """Concatenate plain_text from all rich_text entries in *block_data*."""
    rich_text: List[Dict[str, Any]] = block_data.get("rich_text", [])
    return "".join(entry.get("plain_text", "") for entry in rich_text)


def _render_blocks_to_markdown(blocks: List[Dict[str, Any]]) -> str:
    """Convert a list of Notion block objects to a markdown string.

    Supported block types:
    - ``paragraph`` → plain text
    - ``heading_1`` → ``# text``
    - ``heading_2`` → ``## text``
    - ``heading_3`` → ``### text``
    - ``bulleted_list_item`` → ``- text``
    - ``numbered_list_item`` → ``1. text``
    - ``to_do`` → ``- [ ] text`` or ``- [x] text``
    - ``code`` → fenced code block
    - ``quote`` → ``> text``
    - ``divider`` → ``---``
    - ``toggle`` → rendered as plain heading + content
    - Everything else → extract rich_text if available, skip otherwise
    """
    lines: List[str] = []

    for block in blocks:
        block_type: str = block.get("type", "")
        block_data: Dict[str, Any] = block.get(block_type, {})

        if block_type == "paragraph":
            text = _extract_rich_text(block_data)
            lines.append(text)

        elif block_type == "heading_1":
            text = _extract_rich_text(block_data)
            lines.append(f"# {text}")

        elif block_type == "heading_2":
            text = _extract_rich_text(block_data)
            lines.append(f"## {text}")

        elif block_type == "heading_3":
            text = _extract_rich_text(block_data)
            lines.append(f"### {text}")

        elif block_type == "bulleted_list_item":
            text = _extract_rich_text(block_data)
            lines.append(f"- {text}")

        elif block_type == "numbered_list_item":
            text = _extract_rich_text(block_data)
            lines.append(f"1. {text}")

        elif block_type == "to_do":
            text = _extract_rich_text(block_data)
            checked: bool = block_data.get("checked", False)
            checkbox = "x" if checked else " "
            lines.append(f"- [{checkbox}] {text}")

        elif block_type == "code":
            text = _extract_rich_text(block_data)
            language: str = block_data.get("language", "")
            lines.append(f"```{language}")
            lines.append(text)
            lines.append("```")

        elif block_type == "quote":
            text = _extract_rich_text(block_data)
            lines.append(f"> {text}")

        elif block_type == "divider":
            lines.append("---")

        elif block_type == "toggle":
            text = _extract_rich_text(block_data)
            lines.append(text)

        else:
            # Generic fallback: extract rich_text if the block data has it
            if "rich_text" in block_data:
                text = _extract_rich_text(block_data)
                if text:
                    lines.append(text)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Title extractor
# ---------------------------------------------------------------------------


def _extract_page_title(page: Dict[str, Any]) -> str:
    """Extract the plain-text title from a Notion page object."""
    properties: Dict[str, Any] = page.get("properties", {})

    # The title property can be named "title", "Name", or any custom name.
    # Notion always marks the title property with type "title".
    for _prop_name, prop_value in properties.items():
        if not isinstance(prop_value, dict):
            continue
        title_items: List[Dict[str, Any]] = prop_value.get("title", [])
        if title_items:
            return "".join(item.get("plain_text", "") for item in title_items)

    return "(Untitled)"


def _parse_iso_datetime(dt_str: str) -> datetime:
    """Parse an ISO 8601 datetime string (as returned by Notion) into a datetime."""
    if not dt_str:
        return datetime.now(tz=timezone.utc)
    try:
        # Python 3.11+ handles 'Z' directly; for 3.10 replace manually.
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# NotionConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("notion")
class NotionConnector(BaseConnector):
    """Connector that syncs pages from Notion via the REST API.

    Authentication uses a Notion internal integration token.  Users create
    an integration at https://www.notion.so/my-integrations and paste the
    generated secret token.

    Parameters
    ----------
    token:
        Notion integration token.  If provided, it takes priority over any
        stored credentials file.
    credentials_path:
        Path to the JSON file where the token is stored.  Defaults to
        ``~/.openjarvis/connectors/notion.json``.
    """

    connector_id = "notion"
    display_name = "Notion"
    auth_type = "oauth"  # token-based, same pattern as OAuth connectors

    def __init__(
        self,
        token: str = "",
        credentials_path: str = "",
    ) -> None:
        self._token: str = token
        self._credentials_path: str = credentials_path or _DEFAULT_CREDENTIALS_PATH
        self._items_synced: int = 0
        self._items_total: int = 0
        self._last_sync: Optional[datetime] = None
        self._last_cursor: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal token resolution
    # ------------------------------------------------------------------

    def _resolve_token(self) -> str:
        """Return the active token — direct > file."""
        if self._token:
            return self._token
        tokens = load_tokens(self._credentials_path)
        if tokens:
            return tokens.get("token", "")
        return ""

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return ``True`` if a valid token is available."""
        return bool(self._resolve_token())

    def disconnect(self) -> None:
        """Clear the in-memory token and delete the stored credentials file."""
        self._token = ""
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        """Return the URL where users can create a Notion integration token."""
        return "https://www.notion.so/my-integrations"

    def handle_callback(self, code: str) -> None:
        """Persist the integration token to the credentials file.

        The *code* parameter holds the raw token string (pasted by the user).
        """
        save_tokens(self._credentials_path, {"token": code})

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        """Yield :class:`Document` objects for Notion pages.

        Paginates through ``/v1/search`` and fetches block content for each
        page, rendering it to markdown.

        Parameters
        ----------
        since:
            If provided, skip pages whose ``last_edited_time`` is before this
            datetime.
        cursor:
            ``next_cursor`` from a previous sync to resume pagination.
        """
        token = self._resolve_token()
        if not token:
            return

        page_cursor: Optional[str] = cursor
        synced = 0

        while True:
            search_resp = _notion_api_search(token, cursor=page_cursor)
            pages: List[Dict[str, Any]] = search_resp.get("results", [])

            for page in pages:
                page_id: str = page.get("id", "")
                if not page_id:
                    continue

                last_edited_str: str = page.get("last_edited_time", "")
                timestamp = _parse_iso_datetime(last_edited_str)

                # Apply since filter
                if since is not None:
                    # Make since timezone-aware for comparison if needed
                    since_aware = since
                    if since.tzinfo is None and timestamp.tzinfo is not None:
                        since_aware = since.replace(tzinfo=timezone.utc)
                    if timestamp < since_aware:
                        continue

                title = _extract_page_title(page)
                url: Optional[str] = page.get("url")

                blocks = _notion_api_get_blocks(token, page_id)
                content = _render_blocks_to_markdown(blocks)

                doc = Document(
                    doc_id=f"notion:{page_id}",
                    source="notion",
                    doc_type="document",
                    content=content,
                    title=title,
                    timestamp=timestamp,
                    url=url,
                    metadata={"page_id": page_id},
                )
                synced += 1
                yield doc

            has_more: bool = search_resp.get("has_more", False)
            if not has_more:
                self._last_cursor = None
                break
            page_cursor = search_resp.get("next_cursor")
            self._last_cursor = page_cursor

        self._items_synced = synced
        self._last_sync = datetime.now(tz=timezone.utc)

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
        """Expose two MCP tool specs for real-time Notion queries."""
        return [
            ToolSpec(
                name="notion_search_pages",
                description=(
                    "Search Notion pages accessible to the integration by keyword. "
                    "Returns matching page titles and URLs."
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
                            "description": "Maximum number of pages to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="knowledge",
            ),
            ToolSpec(
                name="notion_get_page",
                description=(
                    "Retrieve the full markdown content of a Notion page by its ID."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "page_id": {
                            "type": "string",
                            "description": "Notion page UUID",
                        },
                    },
                    "required": ["page_id"],
                },
                category="knowledge",
            ),
        ]
