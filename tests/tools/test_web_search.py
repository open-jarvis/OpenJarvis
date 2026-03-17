"""Tests for the web search tool."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.web_search import WebSearchTool


class TestWebSearchTool:
    def test_spec_name_and_category(self):
        tool = WebSearchTool(api_key="test-key")
        assert tool.spec.name == "web_search"
        assert tool.spec.category == "search"

    def test_spec_requires_api_key_metadata(self):
        tool = WebSearchTool(api_key="test-key")
        assert tool.spec.metadata["requires_api_key"] == "TAVILY_API_KEY"

    def test_spec_parameters_require_query(self):
        tool = WebSearchTool(api_key="test-key")
        assert "query" in tool.spec.parameters["properties"]
        assert "query" in tool.spec.parameters["required"]

    def test_execute_no_query(self):
        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="")
        assert result.success is False
        assert "No query" in result.content

    def test_execute_no_query_param(self):
        tool = WebSearchTool(api_key="test-key")
        result = tool.execute()
        assert result.success is False
        assert "No query" in result.content

    def test_execute_no_api_key(self, monkeypatch):
        """When no API key, falls back to DuckDuckGo."""
        tool = WebSearchTool(api_key=None)
        with patch.dict("os.environ", {}, clear=True):
            tool._api_key = None
            monkeypatch.delitem(sys.modules, "tavily", raising=False)
            result = tool.execute(query="test query")
        assert result.success is True
        assert result.metadata["engine"] == "duckduckgo"

    def test_execute_mocked_tavily(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Result 1",
                    "url": "https://example.com/1",
                    "content": "Content about test.",
                },
                {
                    "title": "Result 2",
                    "url": "https://example.com/2",
                    "content": "More content.",
                },
            ]
        }
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client

        import builtins

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "tavily":
                return mock_tavily_module
            if name == "tavily.errors":
                mock_errors = MagicMock()
                mock_errors.UsageLimitExceededError = Exception
                return mock_errors
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="test query")
        assert result.success is True
        assert "Result 1" in result.content
        assert "Result 2" in result.content
        assert result.metadata["num_results"] == 2

    def test_execute_tavily_error(self, monkeypatch):
        """When Tavily errors (any error), falls back to DuckDuckGo."""
        import builtins
        from typing import Any

        original_import = builtins.__import__

        class TavilyError(Exception):
            def __init__(self, message: str):
                super().__init__(message)

        mock_client = MagicMock()
        mock_client.search.side_effect = TavilyError("API error")
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client

        def _mock_import(name: str, *args: Any, **kwargs: Any):
            if name == "tavily":
                return mock_tavily_module
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="test query")
        assert result.success is True
        assert result.metadata["engine"] == "duckduckgo"

    def test_execute_duckduckgo_fallback_format(self, monkeypatch):
        """DuckDuckGo fallback returns properly formatted results."""
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.side_effect = ImportError(
            "No module named 'tavily'"
        )
        monkeypatch.setitem(sys.modules, "tavily", mock_tavily_module)

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = [
            {
                "title": "DDG Result 1",
                "href": "https://example.com/1",
                "body": "Content 1",
            },
            {
                "title": "DDG Result 2",
                "href": "https://example.com/2",
                "body": "Content 2",
            },
        ]
        mock_ddgs_module = MagicMock()
        mock_ddgs_module.DDGS.return_value = mock_ddgs
        monkeypatch.setitem(sys.modules, "ddgs", mock_ddgs_module)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="test query")
        assert result.success is True
        assert "DDG Result 1" in result.content
        assert "DDG Result 2" in result.content
        assert "https://example.com/1" in result.content
        assert result.metadata["engine"] == "duckduckgo"

    def test_max_results_parameter(self, monkeypatch):
        import builtins

        original_import = builtins.__import__

        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client
        mock_errors = MagicMock()

        def _mock_import(name, *args, **kwargs):
            if name == "tavily":
                return mock_tavily_module
            if name == "tavily.errors":
                return mock_errors
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key", max_results=3)
        tool.execute(query="test", max_results=7)
        mock_client.search.assert_called_once_with("test", max_results=7)

    def test_to_openai_function(self):
        tool = WebSearchTool(api_key="test-key")
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "web_search"
        assert "query" in fn["function"]["parameters"]["properties"]

    def test_execute_import_error(self, monkeypatch):
        """When tavily-python not installed, falls back to DuckDuckGo."""
        monkeypatch.delitem(sys.modules, "tavily", raising=False)
        import builtins

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "tavily":
                raise ImportError("No module named 'tavily'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="test query")
        assert result.success is True
        assert result.metadata["engine"] == "duckduckgo"

    def test_empty_results(self, monkeypatch):
        import builtins

        original_import = builtins.__import__

        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client
        mock_errors = MagicMock()

        def _mock_import(name, *args, **kwargs):
            if name == "tavily":
                return mock_tavily_module
            if name == "tavily.errors":
                return mock_errors
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="obscure query")
        assert result.success is True
        assert result.content == "No results found."

    def test_tool_id(self):
        tool = WebSearchTool(api_key="test-key")
        assert tool.tool_id == "web_search"

    def test_registry_registration(self):
        ToolRegistry.register_value("web_search", WebSearchTool)
        assert ToolRegistry.contains("web_search")


# ---------------------------------------------------------------------------
# URL detection and fetching tests
# ---------------------------------------------------------------------------


class TestUrlDetection:
    def test_is_url_https(self):
        assert WebSearchTool._is_url("https://example.com") is True

    def test_is_url_http(self):
        assert WebSearchTool._is_url("http://example.com") is True

    def test_is_url_with_whitespace(self):
        assert WebSearchTool._is_url("  https://example.com  ") is True

    def test_is_url_plain_text(self):
        assert WebSearchTool._is_url("what are punic wars") is False

    def test_is_url_empty(self):
        assert WebSearchTool._is_url("") is False

    def test_extract_url_from_text(self):
        url = WebSearchTool._extract_url(
            "Summarize this: https://example.com/page please"
        )
        assert url == "https://example.com/page"

    def test_extract_url_none_when_absent(self):
        assert WebSearchTool._extract_url("no urls here") is None

    def test_extract_url_strips_trailing_punctuation(self):
        url = WebSearchTool._extract_url("See https://example.com/page.")
        assert url == "https://example.com/page"

    def test_extract_url_from_complex_text(self):
        url = WebSearchTool._extract_url(
            "Read https://arxiv.org/abs/2310.03714 and summarize"
        )
        assert url == "https://arxiv.org/abs/2310.03714"


class TestUrlNormalization:
    def test_arxiv_pdf_to_abs(self):
        url = WebSearchTool._normalize_url("https://arxiv.org/pdf/2310.03714")
        assert url == "https://arxiv.org/abs/2310.03714"

    def test_arxiv_pdf_with_extension(self):
        url = WebSearchTool._normalize_url("https://arxiv.org/pdf/2310.03714.pdf")
        assert url == "https://arxiv.org/abs/2310.03714"

    def test_non_arxiv_unchanged(self):
        url = WebSearchTool._normalize_url("https://example.com/page")
        assert url == "https://example.com/page"

    def test_arxiv_abs_unchanged(self):
        url = WebSearchTool._normalize_url("https://arxiv.org/abs/2310.03714")
        assert url == "https://arxiv.org/abs/2310.03714"


class TestUrlFetching:
    def _mock_ssrf(self, monkeypatch):
        """Stub out the SSRF check (requires Rust backend)."""
        import openjarvis.tools.web_search as _ws

        monkeypatch.setattr(_ws, "check_ssrf", lambda url: None)

    def test_fetch_url_success(self, monkeypatch):
        """Mocked HTTP GET returns HTML, stripped to text."""
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>Hello world</p></body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        content = WebSearchTool._fetch_url("https://example.com")
        assert "Hello world" in content

    def test_fetch_url_strips_scripts(self, monkeypatch):
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<html><script>var x=1;</script><body>Content</body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        content = WebSearchTool._fetch_url("https://example.com")
        assert "var x" not in content
        assert "Content" in content

    def test_fetch_url_truncates_long_content(self, monkeypatch):
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<p>" + "x" * 10000 + "</p>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        content = WebSearchTool._fetch_url("https://example.com", max_chars=100)
        assert len(content) < 200
        assert "[Content truncated]" in content

    def test_fetch_url_pdf_content_type(self, monkeypatch):
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "%PDF-1.4 binary data"
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        content = WebSearchTool._fetch_url("https://example.com/file.pdf")
        assert "PDF" in content
        assert "cannot be read" in content


class TestExecuteWithUrl:
    def _mock_ssrf(self, monkeypatch):
        """Stub out the SSRF check (requires Rust backend)."""
        import openjarvis.tools.web_search as _ws

        monkeypatch.setattr(_ws, "check_ssrf", lambda url: None)

    def test_execute_with_url_query(self, monkeypatch):
        """When query is a URL, fetch instead of search."""
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>Page content here</body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="https://example.com/article")
        assert result.success is True
        assert "Page content here" in result.content
        assert result.metadata.get("mode") == "fetch"

    def test_execute_with_embedded_url(self, monkeypatch):
        """When query contains a URL within text, detect and fetch it."""
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>Article text</body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="Summarize https://example.com/article please")
        assert result.success is True
        assert result.metadata.get("mode") == "fetch"

    def test_execute_url_ssrf_blocked(self, monkeypatch):
        """SSRF check rejects unsafe URLs before any HTTP request."""
        import openjarvis.tools.web_search as _ws

        monkeypatch.setattr(
            _ws,
            "check_ssrf",
            lambda url: "private IP blocked",
        )

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="http://169.254.169.254/metadata")
        assert result.success is False
        assert "private IP blocked" in result.content

    def test_execute_url_fetch_failure(self, monkeypatch):
        """URL fetch failure returns error result."""
        import httpx

        self._mock_ssrf(monkeypatch)
        monkeypatch.setattr(
            httpx,
            "get",
            MagicMock(side_effect=httpx.HTTPError("Connection failed")),
        )

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="https://example.com/broken")
        assert result.success is False
        assert "Failed to fetch URL" in result.content
