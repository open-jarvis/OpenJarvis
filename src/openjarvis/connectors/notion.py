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
    """Call the Notion ``/v1/search`` endpoint to list accessible pages and databases.

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


def _notion_api_query_database(
    token: str,
    database_id: str,
    *,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """Query rows belonging to a Notion database via ``/v1/databases/{id}/query``.

    Parameters
    ----------
    token:
        Notion integration token.
    database_id:
        Database UUID.
    cursor:
        Pagination cursor (``start_cursor``) from a previous query response.

    Returns
    -------
    dict
        Raw API response containing row pages in ``results`` and ``has_more``.
    """
    body: Dict[str, Any] = {
        "page_size": 100,
    }
    if cursor:
        body["start_cursor"] = cursor

    resp = httpx.post(
        f"{_NOTION_API_BASE}/databases/{database_id}/query",
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

        elif block_type == "child_database":
            title = block_data.get("title", "")
            if title:
                lines.append(f"## {title}")

        elif block_type == "child_page":
            title = block_data.get("title", "")
            if title:
                lines.append(f"[Page: {title}]")

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
    """Extract the plain-text title from a Notion page or database object."""
    # Notion databases store their title in a top-level "title" list.
    db_title_items: List[Dict[str, Any]] = page.get("title", [])
    if isinstance(db_title_items, list) and db_title_items:
        title_str = "".join(
            item.get("plain_text", "")
            for item in db_title_items
            if isinstance(item, dict)
        )
        if title_str.strip():
            return title_str.strip()

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


def _extract_property_value(prop_spec: Any) -> str:
    """Extract a human-readable string representation of a Notion property value."""
    if not isinstance(prop_spec, dict):
        return ""
    ptype = prop_spec.get("type")
    if ptype in ("title", "rich_text"):
        items = prop_spec.get(ptype, [])
        if isinstance(items, list):
            return "".join(
                x.get("plain_text", "") for x in items if isinstance(x, dict)
            ).strip()
    elif ptype == "status":
        status_obj = prop_spec.get("status")
        if isinstance(status_obj, dict):
            return status_obj.get("name", "")
    elif ptype == "select":
        sel = prop_spec.get("select")
        if isinstance(sel, dict):
            return sel.get("name", "")
    elif ptype == "multi_select":
        ms = prop_spec.get("multi_select", [])
        if isinstance(ms, list):
            return ", ".join(
                x.get("name", "") for x in ms if isinstance(x, dict) and x.get("name")
            )
    elif ptype == "date":
        d = prop_spec.get("date")
        if isinstance(d, dict):
            start = d.get("start", "")
            end = d.get("end")
            return f"{start} -> {end}" if end else start
    elif ptype == "checkbox":
        return "Yes" if prop_spec.get("checkbox") else "No"
    elif ptype == "number":
        num = prop_spec.get("number")
        return str(num) if num is not None else ""
    elif ptype == "url":
        return prop_spec.get("url") or ""
    elif ptype == "email":
        return prop_spec.get("email") or ""
    elif ptype == "phone_number":
        return prop_spec.get("phone_number") or ""
    elif ptype == "people":
        ppl = prop_spec.get("people", [])
        if isinstance(ppl, list):
            return ", ".join(
                x.get("name", "") for x in ppl if isinstance(x, dict) and x.get("name")
            )
    return ""


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
        """Yield :class:`Document` objects for Notion pages and databases.

        Paginates through ``/v1/search`` and fetches content for each page
        or database, rendering it to markdown.

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
            results: List[Dict[str, Any]] = search_resp.get("results", [])

            for item in results:
                item_id: str = item.get("id", "")
                if not item_id:
                    continue

                obj_type: str = item.get("object", "page")
                if obj_type not in ("page", "database"):
                    continue

                last_edited_str: str = item.get("last_edited_time", "")
                timestamp = _parse_iso_datetime(last_edited_str)

                # Apply since filter
                if since is not None:
                    # Make since timezone-aware for comparison if needed
                    since_aware = since
                    if since.tzinfo is None and timestamp.tzinfo is not None:
                        since_aware = since.replace(tzinfo=timezone.utc)
                    if timestamp < since_aware:
                        continue

                title = _extract_page_title(item)
                url: Optional[str] = item.get("url")

                if obj_type == "database":
                    lines: List[str] = [f"# {title}"]
                    desc_items: List[Dict[str, Any]] = item.get("description", [])
                    if desc_items:
                        desc = "".join(
                            x.get("plain_text", "")
                            for x in desc_items
                            if isinstance(x, dict)
                        ).strip()
                        if desc:
                            lines.append(desc)

                    # List database schema properties
                    props = item.get("properties", {})
                    if props:
                        prop_lines = ["## Properties"]
                        for prop_name, prop_spec in props.items():
                            p_type = (
                                prop_spec.get("type", "")
                                if isinstance(prop_spec, dict)
                                else ""
                            )
                            prop_lines.append(
                                f"- {prop_name} ({p_type})"
                                if p_type
                                else f"- {prop_name}"
                            )
                        lines.append("\n".join(prop_lines))

                    # Query database rows if available
                    try:
                        query_resp = _notion_api_query_database(token, item_id)
                        rows: List[Dict[str, Any]] = query_resp.get("results", [])
                        if rows:
                            row_lines = ["## Rows"]
                            for row in rows:
                                row_title = _extract_page_title(row)
                                row_details: List[str] = []
                                for p_name, p_data in row.get("properties", {}).items():
                                    if (
                                        isinstance(p_data, dict)
                                        and p_data.get("type") != "title"
                                    ):
                                        val = _extract_property_value(p_data)
                                        if val:
                                            row_details.append(f"{p_name}: {val}")
                                if row_details:
                                    row_lines.append(
                                        f"- **{row_title}** ({', '.join(row_details)})"
                                    )
                                else:
                                    row_lines.append(f"- {row_title}")
                            lines.append("\n".join(row_lines))
                    except Exception:
                        pass

                    content = "\n\n".join(lines)
                else:
                    blocks = _notion_api_get_blocks(token, item_id)
                    block_content = _render_blocks_to_markdown(blocks)
                    page_prop_details: List[str] = []
                    for p_name, p_data in item.get("properties", {}).items():
                        if isinstance(p_data, dict) and p_data.get("type") != "title":
                            val = _extract_property_value(p_data)
                            if val:
                                page_prop_details.append(f"- {p_name}: {val}")
                    if page_prop_details:
                        prop_sec = "## Properties\n" + "\n".join(page_prop_details)
                        content = (
                            f"{prop_sec}\n\n{block_content}".strip()
                            if block_content
                            else prop_sec
                        )
                    else:
                        content = block_content

                doc = Document(
                    doc_id=f"notion:{item_id}",
                    source="notion",
                    doc_type="document",
                    content=content,
                    title=title,
                    timestamp=timestamp,
                    url=url,
                    metadata={"page_id": item_id, "object": obj_type},
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
