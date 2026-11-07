"""Tests for browser_axtree tool."""

from unittest.mock import MagicMock, PropertyMock, patch

from friday_ai.tools.browser_axtree import BrowserAXTreeTool


def _make_mock_page():
    page = MagicMock()
    page.accessibility.snapshot.return_value = {
        "role": "WebArea",
        "name": "Test Page",
        "children": [
            {"role": "heading", "name": "Welcome", "level": 1},
            {"role": "link", "name": "Click me", "url": "https://example.com"},
            {"role": "textbox", "name": "Search", "value": ""},
        ],
    }
    return page


def _make_mock_session(page=None):
    if page is None:
        page = _make_mock_page()
    session = MagicMock()
    type(session).page = PropertyMock(return_value=page)
    return session


class TestBrowserAXTreeTool:
    def test_instantiation(self) -> None:
        tool = BrowserAXTreeTool()
        assert tool.tool_id == "browser_axtree"
        assert tool.spec.name == "browser_axtree"

    def test_execute_returns_tree(self) -> None:
        session = _make_mock_session()
        with patch("friday_ai.tools.browser_axtree._session", session):
            tool = BrowserAXTreeTool()
            result = tool.execute()
        assert result.success is True
        assert "heading" in result.content
        assert "Welcome" in result.content

    def test_execute_includes_all_roles(self) -> None:
        session = _make_mock_session()
        with patch("friday_ai.tools.browser_axtree._session", session):
            tool = BrowserAXTreeTool()
            result = tool.execute()
        assert result.success is True
        assert "WebArea" in result.content
        assert "link" in result.content
        assert "textbox" in result.content

    def test_execute_includes_node_count_metadata(self) -> None:
        session = _make_mock_session()
        with patch("friday_ai.tools.browser_axtree._session", session):
            tool = BrowserAXTreeTool()
            result = tool.execute()
        assert result.success is True
        # 1 root + 3 children = 4 nodes
        assert result.metadata["node_count"] == 4

    def test_execute_max_depth(self) -> None:
        """When max_depth=1 only the root node should appear."""
        session = _make_mock_session()
        with patch("friday_ai.tools.browser_axtree._session", session):
            tool = BrowserAXTreeTool()
            result = tool.execute(max_depth=1)
        assert result.success is True
        assert "WebArea" in result.content
        # Children at depth 1 should not be present
        assert "heading" not in result.content

    def test_execute_empty_snapshot(self) -> None:
        page = MagicMock()
        page.accessibility.snapshot.return_value = None
        session = _make_mock_session(page)
        with patch("friday_ai.tools.browser_axtree._session", session):
            tool = BrowserAXTreeTool()
            result = tool.execute()
        assert result.success is False
        assert "No accessibility tree" in result.content

    def test_playwright_not_installed(self) -> None:
        session = MagicMock()
        type(session).page = PropertyMock(
            side_effect=ImportError("playwright not installed")
        )
        with patch("friday_ai.tools.browser_axtree._session", session):
            tool = BrowserAXTreeTool()
            result = tool.execute()
        assert result.success is False
        assert "playwright" in result.content.lower()

    def test_spec_category_and_capabilities(self) -> None:
        tool = BrowserAXTreeTool()
        assert tool.spec.category == "browser"
        assert "network:fetch" in tool.spec.required_capabilities

    def test_spec_has_max_depth_parameter(self) -> None:
        tool = BrowserAXTreeTool()
        props = tool.spec.parameters.get("properties", {})
        assert "max_depth" in props
        assert props["max_depth"]["type"] == "integer"

    def test_to_openai_function(self) -> None:
        tool = BrowserAXTreeTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "browser_axtree"

    def test_execute_snapshot_error(self) -> None:
        page = MagicMock()
        page.accessibility.snapshot.side_effect = Exception("Browser crashed")
        session = _make_mock_session(page)
        with patch("friday_ai.tools.browser_axtree._session", session):
            tool = BrowserAXTreeTool()
            result = tool.execute()
        assert result.success is False
        assert "AX tree extraction error" in result.content
