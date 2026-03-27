"""Tests for NotionConnector — Notion API sync connector.

All Notion API calls are mocked; no network access is required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry

# ---------------------------------------------------------------------------
# Fake API payloads
# ---------------------------------------------------------------------------

_SEARCH_RESPONSE = {
    "results": [
        {
            "id": "page1",
            "object": "page",
            "properties": {"title": {"title": [{"plain_text": "Meeting Notes"}]}},
            "last_edited_time": "2024-03-15T10:00:00.000Z",
            "url": "https://notion.so/page1",
        },
        {
            "id": "page2",
            "object": "page",
            "properties": {"title": {"title": [{"plain_text": "Project Plan"}]}},
            "last_edited_time": "2024-03-16T11:00:00.000Z",
            "url": "https://notion.so/page2",
        },
    ],
    "has_more": False,
}

_BLOCKS_RESPONSE = [
    {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello world"}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Section"}]}},
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def connector(tmp_path: Path):
    """NotionConnector pointing at a tmp credentials path (no file yet)."""
    from openjarvis.connectors.notion import NotionConnector  # noqa: PLC0415

    creds_path = str(tmp_path / "notion.json")
    return NotionConnector(credentials_path=creds_path)


# ---------------------------------------------------------------------------
# Test 1 — not connected without a token or credentials file
# ---------------------------------------------------------------------------


def test_not_connected_without_token(connector) -> None:
    """is_connected() returns False when no token and no credentials file exist."""
    assert connector.is_connected() is False


# ---------------------------------------------------------------------------
# Test 2 — connected when token is provided directly
# ---------------------------------------------------------------------------


def test_connected_with_token() -> None:
    """is_connected() returns True when a token is passed directly."""
    from openjarvis.connectors.notion import NotionConnector  # noqa: PLC0415

    conn = NotionConnector(token="ntn_fake")
    assert conn.is_connected() is True


# ---------------------------------------------------------------------------
# Test 3 — auth_url references notion.so
# ---------------------------------------------------------------------------


def test_auth_url(connector) -> None:
    """auth_url() returns a URL pointing users to the Notion integrations page."""
    url = connector.auth_url()
    assert "notion.so" in url


# ---------------------------------------------------------------------------
# Test 4 — sync yields documents with correct fields (mocked API)
# ---------------------------------------------------------------------------


@patch("openjarvis.connectors.notion._notion_api_search")
@patch("openjarvis.connectors.notion._notion_api_get_blocks")
def test_sync_yields_documents(
    mock_blocks,
    mock_search,
    connector,
    tmp_path: Path,
) -> None:
    """sync() yields one Document per page with correct metadata."""
    # Write fake credentials so is_connected() returns True
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "ntn_fake"}), encoding="utf-8")

    mock_search.return_value = _SEARCH_RESPONSE
    mock_blocks.return_value = _BLOCKS_RESPONSE

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 2

    # --- Page 1 ---
    doc1 = next(d for d in docs if d.doc_id == "notion:page1")
    assert doc1.source == "notion"
    assert doc1.doc_type == "document"
    assert doc1.title == "Meeting Notes"
    assert doc1.url == "https://notion.so/page1"
    assert "Hello world" in doc1.content
    assert "## Section" in doc1.content

    # --- Page 2 ---
    doc2 = next(d for d in docs if d.doc_id == "notion:page2")
    assert doc2.title == "Project Plan"
    assert doc2.url == "https://notion.so/page2"

    # Verify the API was called correctly
    mock_search.assert_called_once()
    assert mock_blocks.call_count == 2


# ---------------------------------------------------------------------------
# Test 5 — render_blocks_to_markdown handles various block types
# ---------------------------------------------------------------------------


def test_render_blocks_to_markdown() -> None:
    """_render_blocks_to_markdown converts each block type to the correct markdown."""
    from openjarvis.connectors.notion import _render_blocks_to_markdown  # noqa: PLC0415

    blocks = [
        {
            "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": "Para text"}]},
        },
        {
            "type": "heading_1",
            "heading_1": {"rich_text": [{"plain_text": "H1 Title"}]},
        },
        {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "H2 Title"}]},
        },
        {"type": "heading_3", "heading_3": {"rich_text": [{"plain_text": "H3 Title"}]}},
        {
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"plain_text": "Bullet point"}]},
        },
        {
            "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": [{"plain_text": "Numbered item"}]},
        },
        {
            "type": "to_do",
            "to_do": {
                "rich_text": [{"plain_text": "Unchecked task"}],
                "checked": False,
            },
        },
        {
            "type": "to_do",
            "to_do": {"rich_text": [{"plain_text": "Checked task"}], "checked": True},
        },
        {
            "type": "code",
            "code": {
                "rich_text": [{"plain_text": "print('hello')"}],
                "language": "python",
            },
        },
        {"type": "quote", "quote": {"rich_text": [{"plain_text": "A wise saying"}]}},
        {"type": "divider"},
    ]

    result = _render_blocks_to_markdown(blocks)

    assert "Para text" in result
    assert "# H1 Title" in result
    assert "## H2 Title" in result
    assert "### H3 Title" in result
    assert "- Bullet point" in result
    assert "1. Numbered item" in result
    assert "- [ ] Unchecked task" in result
    assert "- [x] Checked task" in result
    assert "```" in result
    assert "print('hello')" in result
    assert "> A wise saying" in result
    assert "---" in result


# ---------------------------------------------------------------------------
# Test 6 — disconnect removes the credentials file
# ---------------------------------------------------------------------------


def test_disconnect(connector, tmp_path: Path) -> None:
    """disconnect() deletes the credentials file."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "ntn_fake"}), encoding="utf-8")
    assert connector.is_connected() is True

    connector.disconnect()

    assert not creds_path.exists()
    assert connector.is_connected() is False


# ---------------------------------------------------------------------------
# Test 7 — mcp_tools returns the two expected tool specs
# ---------------------------------------------------------------------------


def test_mcp_tools(connector) -> None:
    """mcp_tools() returns exactly 2 tools with the required names."""
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert len(tools) == 2
    assert "notion_search_pages" in names
    assert "notion_get_page" in names


# ---------------------------------------------------------------------------
# Test 8 — ConnectorRegistry contains "notion" after import
# ---------------------------------------------------------------------------


def test_registry() -> None:
    """NotionConnector can be registered and retrieved via ConnectorRegistry."""
    from openjarvis.connectors.notion import NotionConnector  # noqa: PLC0415

    ConnectorRegistry.register_value("notion", NotionConnector)
    assert ConnectorRegistry.contains("notion")
    cls = ConnectorRegistry.get("notion")
    assert cls.connector_id == "notion"
