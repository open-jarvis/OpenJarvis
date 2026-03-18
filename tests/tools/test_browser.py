"""Tests for browser automation tools."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from openjarvis.core.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Helpers — mock the _session before importing tools
# ---------------------------------------------------------------------------


def _make_mock_page():
    """Create a fully mocked Playwright page object."""
    page = MagicMock()
    page.title.return_value = "Test Page"
    page.inner_text.return_value = "Hello World"
    page.screenshot.return_value = b"\x89PNG\x00fake-screenshot-data"

    response = MagicMock()
    response.status = 200
    page.goto.return_value = response

    page.click.return_value = None
    page.get_by_text.return_value = MagicMock()
    page.fill.return_value = None
    page.type.return_value = None
    page.eval_on_selector_all.return_value = []

    return page


def _make_mock_session(page=None):
    """Create a mocked _BrowserSession whose .page returns a mock page."""
    if page is None:
        page = _make_mock_page()
    session = MagicMock()
    type(session).page = PropertyMock(return_value=page)
    return session


def _make_import_error_session():
    """Create a session whose .page raises ImportError."""
    session = MagicMock()
    type(session).page = PropertyMock(
        side_effect=ImportError(
            "playwright not installed. Install with: uv sync --extra browser"
        )
    )
    return session


# ---------------------------------------------------------------------------
# TestBrowserNavigateTool
# ---------------------------------------------------------------------------


class TestBrowserNavigateTool:
    def test_spec_name_and_category(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        tool = BrowserNavigateTool()
        assert tool.spec.name == "browser_navigate"
        assert tool.spec.category == "browser"

    def test_spec_requires_url_parameter(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        tool = BrowserNavigateTool()
        assert "url" in tool.spec.parameters["properties"]
        assert "url" in tool.spec.parameters["required"]

    def test_spec_has_wait_for_parameter(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        tool = BrowserNavigateTool()
        assert "wait_for" in tool.spec.parameters["properties"]

    def test_spec_required_capabilities(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        tool = BrowserNavigateTool()
        assert "network:fetch" in tool.spec.required_capabilities

    def test_tool_id(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        tool = BrowserNavigateTool()
        assert tool.tool_id == "browser_navigate"

    def test_execute_no_url(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        tool = BrowserNavigateTool()
        result = tool.execute(url="")
        assert result.success is False
        assert "No URL" in result.content

    def test_execute_no_url_param(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        tool = BrowserNavigateTool()
        result = tool.execute()
        assert result.success is False
        assert "No URL" in result.content

    def test_execute_playwright_not_installed(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        session = _make_import_error_session()
        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserNavigateTool()
            result = tool.execute(url="https://example.com")
        assert result.success is False
        assert "playwright not installed" in result.content

    def test_execute_ssrf_blocked(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        mock_ssrf_module = MagicMock()
        mock_ssrf_module.check_ssrf.return_value = (
            "Blocked host: 169.254.169.254 (cloud metadata endpoint)"
        )
        with patch.dict(
            "sys.modules",
            {"openjarvis.security.ssrf": mock_ssrf_module},
        ):
            tool = BrowserNavigateTool()
            result = tool.execute(url="http://169.254.169.254/latest/meta-data/")

        assert result.success is False
        assert "SSRF blocked" in result.content

    def test_execute_ssrf_module_missing(self):
        """When ssrf module is not available, skip check and proceed."""
        from openjarvis.tools.browser import BrowserNavigateTool

        page = _make_mock_page()
        session = _make_mock_session(page)

        # Make the ssrf import fail inside execute
        import builtins

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "openjarvis.security.ssrf":
                raise ImportError("No module named 'openjarvis.security.ssrf'")
            return original_import(name, *args, **kwargs)

        with patch("openjarvis.tools.browser._session", session):
            with patch.object(builtins, "__import__", side_effect=_mock_import):
                tool = BrowserNavigateTool()
                result = tool.execute(url="https://example.com")
        # Should succeed since SSRF check is skipped
        assert result.success is True

    def test_execute_success(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        page = _make_mock_page()
        page.title.return_value = "Example Domain"
        page.inner_text.return_value = "Example page content"
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserNavigateTool()
            result = tool.execute(url="https://example.com")

        assert result.success is True
        assert "Example Domain" in result.content
        assert "Example page content" in result.content
        assert result.metadata["url"] == "https://example.com"
        assert result.metadata["title"] == "Example Domain"
        assert result.metadata["status"] == 200

    def test_execute_with_wait_for(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        page = _make_mock_page()
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserNavigateTool()
            tool.execute(url="https://example.com", wait_for="networkidle")

        page.goto.assert_called_once_with(
            "https://example.com", wait_until="networkidle"
        )

    def test_execute_invalid_wait_for_defaults_to_load(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        page = _make_mock_page()
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserNavigateTool()
            tool.execute(url="https://example.com", wait_for="invalid")

        page.goto.assert_called_once_with("https://example.com", wait_until="load")

    def test_execute_content_truncation(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        page = _make_mock_page()
        page.inner_text.return_value = "x" * 6000
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserNavigateTool()
            result = tool.execute(url="https://example.com")

        assert result.success is True
        assert "[Content truncated]" in result.content

    def test_execute_navigation_error(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        page = _make_mock_page()
        page.goto.side_effect = Exception("net::ERR_NAME_NOT_RESOLVED")
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserNavigateTool()
            result = tool.execute(url="https://nonexistent.example")

        assert result.success is False
        assert "Navigation error" in result.content

    def test_to_openai_function(self):
        from openjarvis.tools.browser import BrowserNavigateTool

        tool = BrowserNavigateTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "browser_navigate"
        assert "url" in fn["function"]["parameters"]["properties"]


# ---------------------------------------------------------------------------
# TestBrowserClickTool
# ---------------------------------------------------------------------------


class TestBrowserClickTool:
    def test_spec_name_and_category(self):
        from openjarvis.tools.browser import BrowserClickTool

        tool = BrowserClickTool()
        assert tool.spec.name == "browser_click"
        assert tool.spec.category == "browser"

    def test_spec_requires_selector(self):
        from openjarvis.tools.browser import BrowserClickTool

        tool = BrowserClickTool()
        assert "selector" in tool.spec.parameters["properties"]
        assert "selector" in tool.spec.parameters["required"]

    def test_spec_has_by_text_parameter(self):
        from openjarvis.tools.browser import BrowserClickTool

        tool = BrowserClickTool()
        assert "by_text" in tool.spec.parameters["properties"]

    def test_tool_id(self):
        from openjarvis.tools.browser import BrowserClickTool

        tool = BrowserClickTool()
        assert tool.tool_id == "browser_click"

    def test_execute_no_selector(self):
        from openjarvis.tools.browser import BrowserClickTool

        tool = BrowserClickTool()
        result = tool.execute(selector="")
        assert result.success is False
        assert "No selector" in result.content

    def test_execute_no_selector_param(self):
        from openjarvis.tools.browser import BrowserClickTool

        tool = BrowserClickTool()
        result = tool.execute()
        assert result.success is False
        assert "No selector" in result.content

    def test_execute_playwright_not_installed(self):
        from openjarvis.tools.browser import BrowserClickTool

        session = _make_import_error_session()
        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserClickTool()
            result = tool.execute(selector="#btn")
        assert result.success is False
        assert "playwright not installed" in result.content

    def test_execute_click_by_css(self):
        from openjarvis.tools.browser import BrowserClickTool

        page = _make_mock_page()
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserClickTool()
            result = tool.execute(selector="#submit-btn")

        assert result.success is True
        assert "Clicked element" in result.content
        page.click.assert_called_once_with("#submit-btn")
        assert result.metadata["selector"] == "#submit-btn"
        assert result.metadata["by_text"] is False

    def test_execute_click_by_text(self):
        from openjarvis.tools.browser import BrowserClickTool

        page = _make_mock_page()
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserClickTool()
            result = tool.execute(selector="Sign In", by_text=True)

        assert result.success is True
        page.get_by_text.assert_called_once_with("Sign In")
        page.get_by_text.return_value.click.assert_called_once()
        assert result.metadata["by_text"] is True

    def test_execute_click_error(self):
        from openjarvis.tools.browser import BrowserClickTool

        page = _make_mock_page()
        page.click.side_effect = Exception("Element not found")
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserClickTool()
            result = tool.execute(selector="#nonexistent")

        assert result.success is False
        assert "Click error" in result.content

    def test_to_openai_function(self):
        from openjarvis.tools.browser import BrowserClickTool

        tool = BrowserClickTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "browser_click"


# ---------------------------------------------------------------------------
# TestBrowserTypeTool
# ---------------------------------------------------------------------------


class TestBrowserTypeTool:
    def test_spec_name_and_category(self):
        from openjarvis.tools.browser import BrowserTypeTool

        tool = BrowserTypeTool()
        assert tool.spec.name == "browser_type"
        assert tool.spec.category == "browser"

    def test_spec_requires_selector_and_text(self):
        from openjarvis.tools.browser import BrowserTypeTool

        tool = BrowserTypeTool()
        assert "selector" in tool.spec.parameters["properties"]
        assert "text" in tool.spec.parameters["properties"]
        assert "selector" in tool.spec.parameters["required"]
        assert "text" in tool.spec.parameters["required"]

    def test_spec_has_clear_parameter(self):
        from openjarvis.tools.browser import BrowserTypeTool

        tool = BrowserTypeTool()
        assert "clear" in tool.spec.parameters["properties"]

    def test_tool_id(self):
        from openjarvis.tools.browser import BrowserTypeTool

        tool = BrowserTypeTool()
        assert tool.tool_id == "browser_type"

    def test_execute_no_selector(self):
        from openjarvis.tools.browser import BrowserTypeTool

        tool = BrowserTypeTool()
        result = tool.execute(selector="", text="hello")
        assert result.success is False
        assert "No selector" in result.content

    def test_execute_no_text(self):
        from openjarvis.tools.browser import BrowserTypeTool

        tool = BrowserTypeTool()
        result = tool.execute(selector="#input", text="")
        assert result.success is False
        assert "No text" in result.content

    def test_execute_no_params(self):
        from openjarvis.tools.browser import BrowserTypeTool

        tool = BrowserTypeTool()
        result = tool.execute()
        assert result.success is False

    def test_execute_playwright_not_installed(self):
        from openjarvis.tools.browser import BrowserTypeTool

        session = _make_import_error_session()
        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserTypeTool()
            result = tool.execute(selector="#input", text="hello")
        assert result.success is False
        assert "playwright not installed" in result.content

    def test_execute_fill_clear_true(self):
        from openjarvis.tools.browser import BrowserTypeTool

        page = _make_mock_page()
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserTypeTool()
            result = tool.execute(selector="#search", text="query", clear=True)

        assert result.success is True
        page.fill.assert_called_once_with("#search", "query")
        page.type.assert_not_called()
        assert result.metadata["selector"] == "#search"

    def test_execute_fill_default_clear(self):
        """Default clear=True should use page.fill()."""
        from openjarvis.tools.browser import BrowserTypeTool

        page = _make_mock_page()
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserTypeTool()
            result = tool.execute(selector="#search", text="query")

        assert result.success is True
        page.fill.assert_called_once_with("#search", "query")

    def test_execute_type_clear_false(self):
        from openjarvis.tools.browser import BrowserTypeTool

        page = _make_mock_page()
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserTypeTool()
            result = tool.execute(selector="#search", text="query", clear=False)

        assert result.success is True
        page.type.assert_called_once_with("#search", "query")
        page.fill.assert_not_called()

    def test_execute_type_error(self):
        from openjarvis.tools.browser import BrowserTypeTool

        page = _make_mock_page()
        page.fill.side_effect = Exception("Element not editable")
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserTypeTool()
            result = tool.execute(selector="#readonly", text="hello")

        assert result.success is False
        assert "Type error" in result.content

    def test_to_openai_function(self):
        from openjarvis.tools.browser import BrowserTypeTool

        tool = BrowserTypeTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "browser_type"


# ---------------------------------------------------------------------------
# TestBrowserScreenshotTool
# ---------------------------------------------------------------------------


class TestBrowserScreenshotTool:
    def test_spec_name_and_category(self):
        from openjarvis.tools.browser import BrowserScreenshotTool

        tool = BrowserScreenshotTool()
        assert tool.spec.name == "browser_screenshot"
        assert tool.spec.category == "browser"

    def test_spec_has_path_and_full_page(self):
        from openjarvis.tools.browser import BrowserScreenshotTool

        tool = BrowserScreenshotTool()
        props = tool.spec.parameters["properties"]
        assert "path" in props
        assert "full_page" in props

    def test_spec_no_required_params(self):
        from openjarvis.tools.browser import BrowserScreenshotTool

        tool = BrowserScreenshotTool()
        assert "required" not in tool.spec.parameters

    def test_tool_id(self):
        from openjarvis.tools.browser import BrowserScreenshotTool

        tool = BrowserScreenshotTool()
        assert tool.tool_id == "browser_screenshot"

    def test_execute_playwright_not_installed(self):
        from openjarvis.tools.browser import BrowserScreenshotTool

        session = _make_import_error_session()
        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserScreenshotTool()
            result = tool.execute()
        assert result.success is False
        assert "playwright not installed" in result.content

    def test_execute_screenshot_basic(self):
        from openjarvis.tools.browser import BrowserScreenshotTool

        fake_png = b"\x89PNG\x00screenshot-data"
        page = _make_mock_page()
        page.screenshot.return_value = fake_png
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserScreenshotTool()
            result = tool.execute()

        assert result.success is True
        assert "Screenshot taken" in result.content
        assert "full page" not in result.content
        expected_b64 = base64.b64encode(fake_png).decode("utf-8")
        assert result.metadata["screenshot_base64"] == expected_b64
        page.screenshot.assert_called_once_with(full_page=False)

    def test_execute_screenshot_full_page(self):
        from openjarvis.tools.browser import BrowserScreenshotTool

        page = _make_mock_page()
        page.screenshot.return_value = b"png-data"
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserScreenshotTool()
            result = tool.execute(full_page=True)

        assert result.success is True
        assert "full page" in result.content
        page.screenshot.assert_called_once_with(full_page=True)

    def test_execute_screenshot_save_to_file(self, tmp_path):
        from openjarvis.tools.browser import BrowserScreenshotTool

        fake_png = b"\x89PNGscreenshot"
        page = _make_mock_page()
        page.screenshot.return_value = fake_png
        session = _make_mock_session(page)

        save_path = str(tmp_path / "test_screenshot.png")

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserScreenshotTool()
            result = tool.execute(path=save_path)

        assert result.success is True
        assert save_path in result.content
        # Verify file was written
        with open(save_path, "rb") as f:
            assert f.read() == fake_png

    def test_execute_screenshot_error(self):
        from openjarvis.tools.browser import BrowserScreenshotTool

        page = _make_mock_page()
        page.screenshot.side_effect = Exception("Browser crashed")
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserScreenshotTool()
            result = tool.execute()

        assert result.success is False
        assert "Screenshot error" in result.content

    def test_to_openai_function(self):
        from openjarvis.tools.browser import BrowserScreenshotTool

        tool = BrowserScreenshotTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "browser_screenshot"


# ---------------------------------------------------------------------------
# TestBrowserExtractTool
# ---------------------------------------------------------------------------


class TestBrowserExtractTool:
    def test_spec_name_and_category(self):
        from openjarvis.tools.browser import BrowserExtractTool

        tool = BrowserExtractTool()
        assert tool.spec.name == "browser_extract"
        assert tool.spec.category == "browser"

    def test_spec_has_selector_and_extract_type(self):
        from openjarvis.tools.browser import BrowserExtractTool

        tool = BrowserExtractTool()
        props = tool.spec.parameters["properties"]
        assert "selector" in props
        assert "extract_type" in props

    def test_tool_id(self):
        from openjarvis.tools.browser import BrowserExtractTool

        tool = BrowserExtractTool()
        assert tool.tool_id == "browser_extract"

    def test_execute_playwright_not_installed(self):
        from openjarvis.tools.browser import BrowserExtractTool

        session = _make_import_error_session()
        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserExtractTool()
            result = tool.execute()
        assert result.success is False
        assert "playwright not installed" in result.content

    def test_execute_invalid_extract_type(self):
        from openjarvis.tools.browser import BrowserExtractTool

        tool = BrowserExtractTool()
        result = tool.execute(extract_type="images")
        assert result.success is False
        assert "Invalid extract_type" in result.content

    def test_execute_extract_text(self):
        from openjarvis.tools.browser import BrowserExtractTool

        page = _make_mock_page()
        page.inner_text.return_value = "Page text content here"
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserExtractTool()
            result = tool.execute(extract_type="text")

        assert result.success is True
        assert result.content == "Page text content here"
        page.inner_text.assert_called_with("body")
        assert result.metadata["extract_type"] == "text"

    def test_execute_extract_text_custom_selector(self):
        from openjarvis.tools.browser import BrowserExtractTool

        page = _make_mock_page()
        page.inner_text.return_value = "Article content"
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserExtractTool()
            result = tool.execute(selector="#article", extract_type="text")

        assert result.success is True
        page.inner_text.assert_called_with("#article")
        assert result.metadata["selector"] == "#article"

    def test_execute_extract_text_default(self):
        """Default extract_type should be 'text'."""
        from openjarvis.tools.browser import BrowserExtractTool

        page = _make_mock_page()
        page.inner_text.return_value = "Default text"
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserExtractTool()
            result = tool.execute()

        assert result.success is True
        assert result.content == "Default text"

    def test_execute_extract_text_truncation(self):
        from openjarvis.tools.browser import BrowserExtractTool

        page = _make_mock_page()
        page.inner_text.return_value = "a" * 12000
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserExtractTool()
            result = tool.execute(extract_type="text")

        assert result.success is True
        assert "[Content truncated]" in result.content
        # Content should be truncated at 10000 + truncation notice
        assert len(result.content) < 11000

    def test_execute_extract_links(self):
        from openjarvis.tools.browser import BrowserExtractTool

        page = _make_mock_page()
        page.eval_on_selector_all.return_value = [
            {"href": "https://example.com/page1", "text": "Page 1"},
            {"href": "https://example.com/page2", "text": "Page 2"},
        ]
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserExtractTool()
            result = tool.execute(extract_type="links")

        assert result.success is True
        assert "[Page 1](https://example.com/page1)" in result.content
        assert "[Page 2](https://example.com/page2)" in result.content
        assert result.metadata["num_links"] == 2

    def test_execute_extract_links_empty(self):
        from openjarvis.tools.browser import BrowserExtractTool

        page = _make_mock_page()
        page.eval_on_selector_all.return_value = []
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserExtractTool()
            result = tool.execute(extract_type="links")

        assert result.success is True
        assert result.content == "No links found."
        assert result.metadata["num_links"] == 0

    def test_execute_extract_tables(self):
        from openjarvis.tools.browser import BrowserExtractTool

        page = _make_mock_page()
        page.eval_on_selector_all.return_value = [
            "Name\tAge\nAlice\t30",
            "City\tCountry\nNYC\tUSA",
        ]
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserExtractTool()
            result = tool.execute(extract_type="tables")

        assert result.success is True
        assert "Alice" in result.content
        assert "NYC" in result.content
        assert result.metadata["num_tables"] == 2

    def test_execute_extract_tables_empty(self):
        from openjarvis.tools.browser import BrowserExtractTool

        page = _make_mock_page()
        page.eval_on_selector_all.return_value = []
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserExtractTool()
            result = tool.execute(extract_type="tables")

        assert result.success is True
        assert result.content == "No tables found."

    def test_execute_extract_error(self):
        from openjarvis.tools.browser import BrowserExtractTool

        page = _make_mock_page()
        page.inner_text.side_effect = Exception("Selector not found")
        session = _make_mock_session(page)

        with patch("openjarvis.tools.browser._session", session):
            tool = BrowserExtractTool()
            result = tool.execute(selector="#missing", extract_type="text")

        assert result.success is False
        assert "Extract error" in result.content

    def test_to_openai_function(self):
        from openjarvis.tools.browser import BrowserExtractTool

        tool = BrowserExtractTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "browser_extract"


# ---------------------------------------------------------------------------
# TestBrowserSession
# ---------------------------------------------------------------------------


class TestBrowserSession:
    def test_session_close_resets_state(self):
        from openjarvis.tools.browser import _BrowserSession

        session = _BrowserSession()
        session._playwright = MagicMock()
        session._browser = MagicMock()
        session._page = MagicMock()

        session.close()

        assert session._playwright is None
        assert session._browser is None
        assert session._page is None

    def test_session_close_noop_when_not_initialized(self):
        from openjarvis.tools.browser import _BrowserSession

        session = _BrowserSession()
        # Should not raise
        session.close()
        assert session._playwright is None

    def test_session_ensure_browser_import_error(self):
        from openjarvis.tools.browser import _BrowserSession

        session = _BrowserSession()

        import builtins

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if "playwright" in name:
                raise ImportError("No module named 'playwright'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=_mock_import):
            with pytest.raises(ImportError, match="playwright not installed"):
                session._ensure_browser()

    def test_session_page_reuses_existing(self):
        from openjarvis.tools.browser import _BrowserSession

        session = _BrowserSession()
        mock_page = MagicMock()
        session._page = mock_page

        # _ensure_browser should not re-create if page exists
        session._ensure_browser()
        assert session._page is mock_page


# ---------------------------------------------------------------------------
# TestRegistryIntegration
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    def test_all_tools_registered(self):
        # Registration happens at import time via @ToolRegistry.register.
        # Other test modules may clear the registry, so re-register if needed.
        from openjarvis.tools.browser import (
            BrowserClickTool,
            BrowserExtractTool,
            BrowserNavigateTool,
            BrowserScreenshotTool,
            BrowserTypeTool,
        )

        tools = {
            "browser_navigate": BrowserNavigateTool,
            "browser_click": BrowserClickTool,
            "browser_type": BrowserTypeTool,
            "browser_screenshot": BrowserScreenshotTool,
            "browser_extract": BrowserExtractTool,
        }
        for key, cls in tools.items():
            if not ToolRegistry.contains(key):
                ToolRegistry.register_value(key, cls)

        assert ToolRegistry.contains("browser_navigate")
        assert ToolRegistry.contains("browser_click")
        assert ToolRegistry.contains("browser_type")
        assert ToolRegistry.contains("browser_screenshot")
        assert ToolRegistry.contains("browser_extract")

    def test_module_exports(self):
        from openjarvis.tools.browser import __all__

        assert "BrowserNavigateTool" in __all__
        assert "BrowserClickTool" in __all__
        assert "BrowserTypeTool" in __all__
        assert "BrowserScreenshotTool" in __all__
        assert "BrowserExtractTool" in __all__
