"""Tests for the web search tool."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.web_search import WebSearchTool


@pytest.fixture(autouse=True)
def _no_ambient_serply_key(monkeypatch):
    """Keep the Serply env out of every test in this module.

    Tests here clear the Tavily and You.com keys case by case, so a third
    engine key read from the ambient environment would flip ``auto`` and turn
    the suite red on a machine that happens to have one set, which is the
    failure mode reported in #972. Tests that want the key set it themselves.
    """
    monkeypatch.delenv("SERPLY_API_KEY", raising=False)
    monkeypatch.delenv("SERPLY_PROXY_LOCATION", raising=False)


@pytest.fixture(autouse=True)
def _no_ambient_firecrawl_key(monkeypatch):
    """Same guard as above for the Firecrawl env, for the same reason (#972)."""
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_URL", raising=False)


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
        """With no API key at all, queries go to the You.com keyless tier.

        This is the behavior change in #923: the zero-config path used to be
        the DuckDuckGo HTML scrape, which is unranked and rate limited.
        """
        import httpx

        captured = {}

        def _get(url, **kwargs):
            captured["url"] = url
            resp = MagicMock()
            resp.json.return_value = {
                "results": {
                    "web": [
                        {
                            "url": "https://example.com",
                            "title": "T",
                            "snippets": ["S"],
                        }
                    ]
                }
            }
            resp.raise_for_status = MagicMock()
            return resp

        with patch.dict("os.environ", {}, clear=True):
            monkeypatch.setattr(httpx, "get", _get)
            monkeypatch.delitem(sys.modules, "tavily", raising=False)
            tool = WebSearchTool(api_key=None)
            tool._api_key = None
            result = tool.execute(query="test query")

        assert result.success is True
        assert result.metadata["engine"] == "youcom"
        assert captured["url"] == "https://api.you.com/v1/agents/search"

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
        mock_client.search.assert_called_once_with(
            "test", max_results=7, search_depth="advanced", include_usage=True
        )

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

    def test_tavily_results_use_labeled_content_format(self, monkeypatch):
        """Regression for #390: results expose page CONTENT under labeled
        Source/Summary headings (so agents synthesize content, not echo
        URLs), and Tavily is queried with search_depth='advanced'."""
        import builtins

        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Result 1",
                    "url": "https://example.com/1",
                    "content": "Content about test.",
                },
            ]
        }
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client
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
        # Labeled structure with the page content surfaced.
        assert "### Result 1" in result.content
        assert "Source: https://example.com/1" in result.content
        assert "Summary: Content about test." in result.content
        # search_depth='advanced' is what pulls richer content from Tavily.
        _, kwargs = mock_client.search.call_args
        assert kwargs.get("search_depth") == "advanced"

    def test_tavily_falls_back_to_snippet_when_no_content(self, monkeypatch):
        """When a Tavily result lacks 'content', the 'snippet' field is used
        for the Summary rather than rendering an empty summary."""
        import builtins

        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Snippet Only",
                    "url": "https://example.com/s",
                    "snippet": "Fallback snippet text.",
                },
            ]
        }
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client
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
        assert "Summary: Fallback snippet text." in result.content


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
        monkeypatch.setattr(httpx.Client, "get", MagicMock(return_value=mock_resp))

        content = WebSearchTool._fetch_url("https://example.com")
        assert "Hello world" in content

    def test_fetch_url_strips_scripts(self, monkeypatch):
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<html><script>var x=1;</script><body>Content</body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx.Client, "get", MagicMock(return_value=mock_resp))

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
        monkeypatch.setattr(httpx.Client, "get", MagicMock(return_value=mock_resp))

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
        monkeypatch.setattr(httpx.Client, "get", MagicMock(return_value=mock_resp))

        content = WebSearchTool._fetch_url("https://example.com/file.pdf")
        assert "PDF" in content
        assert "cannot be read" in content


class TestFetchRedirectSession:
    @pytest.fixture(autouse=True)
    def _guard(self, monkeypatch):
        import openjarvis.tools.web_search as web_search

        guard = MagicMock(return_value=None)
        monkeypatch.setattr(web_search, "check_ssrf", guard)
        return guard

    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    def test_redirect_keeps_cookie_and_closes_client(self, monkeypatch, status):
        """Keep the actual client lifecycle so a fresh client per hop fails."""
        import httpx

        requests = []
        closed = []
        exit_transport = httpx.HTTPTransport.__exit__

        def close_transport(transport, *args):
            closed.append(transport)
            return exit_transport(transport, *args)

        def handler(transport, request):
            requests.append(request)
            if request.url.path == "/start":
                return httpx.Response(
                    status,
                    headers={
                        "location": "/article",
                        "set-cookie": "session=redirect; Path=/; Secure",
                    },
                )
            if request.headers.get("cookie") != "session=redirect":
                return httpx.Response(403)
            return httpx.Response(200, text="article with redirect cookie")

        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handler)
        monkeypatch.setattr(httpx.HTTPTransport, "__exit__", close_transport)

        assert WebSearchTool._fetch_url("https://public.example/start") == (
            "article with redirect cookie"
        )
        assert len(requests) == 2
        assert closed

    @pytest.mark.parametrize(
        "destination",
        ["https://other.example/article", "http://public.example/article"],
    )
    def test_cookie_is_scoped_to_host_and_fetch(self, monkeypatch, destination):
        import httpx

        requests = []

        def handler(transport, request):
            requests.append(request)
            if request.url.path == "/start":
                return httpx.Response(
                    302,
                    headers={
                        "location": destination,
                        "set-cookie": "session=private; Path=/; Secure",
                    },
                )
            return httpx.Response(200, text="article")

        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handler)

        assert WebSearchTool._fetch_url("https://public.example/start") == "article"
        assert WebSearchTool._fetch_url("https://public.example/article") == "article"
        assert [request.headers.get("cookie") for request in requests] == [
            None,
            None,
            None,
        ]

    def test_private_redirect_with_cookie_is_never_requested(self, monkeypatch, _guard):
        import httpx

        requests = []

        def handler(transport, request):
            requests.append(request)
            return httpx.Response(
                302,
                headers={
                    "location": "http://127.0.0.1/admin",
                    "set-cookie": "session=private; Path=/",
                },
            )

        _guard.side_effect = [None, "private IP blocked"]
        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handler)

        with pytest.raises(ValueError, match="private IP blocked"):
            WebSearchTool._fetch_url("https://public.example/start")
        assert len(requests) == 1
        assert [call.args[0] for call in _guard.call_args_list] == [
            "https://public.example/start",
            "http://127.0.0.1/admin",
        ]

    @pytest.mark.parametrize("redirects", [5, 6])
    def test_redirect_limit(self, monkeypatch, _guard, redirects):
        import httpx

        requests = []

        def handler(transport, request):
            requests.append(request)
            hop = int(request.url.path.removeprefix("/"))
            if hop < redirects:
                return httpx.Response(302, headers={"location": f"/{hop + 1}"})
            return httpx.Response(200, text="article")

        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handler)

        if redirects == 5:
            assert WebSearchTool._fetch_url("https://public.example/0") == "article"
        else:
            with pytest.raises(ValueError, match="maximum of 5 redirects"):
                WebSearchTool._fetch_url("https://public.example/0")
        assert len(requests) == 6
        assert _guard.call_count == 6


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
        monkeypatch.setattr(httpx.Client, "get", MagicMock(return_value=mock_resp))

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
        monkeypatch.setattr(httpx.Client, "get", MagicMock(return_value=mock_resp))

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
            httpx.Client,
            "get",
            MagicMock(side_effect=httpx.HTTPError("Connection failed")),
        )

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="https://example.com/broken")
        assert result.success is False
        assert "Failed to fetch URL" in result.content

    def test_url_redirect_to_private_ip_is_blocked(self, monkeypatch):
        """Every URL redirect hop must be checked for SSRF."""
        import httpx

        import openjarvis.tools.web_search as _ws

        requests = []

        def handler(request):
            requests.append(str(request.url))
            if request.url.host == "public.example.com":
                return httpx.Response(
                    302,
                    headers={"location": "http://127.0.0.1/admin"},
                    request=request,
                )
            return httpx.Response(
                200,
                text="internal response",
                headers={"content-type": "text/html"},
                request=request,
            )

        guard = MagicMock(
            side_effect=[None, None, "URL resolves to private IP: 127.0.0.1"]
        )
        monkeypatch.setattr(
            httpx.HTTPTransport,
            "handle_request",
            lambda self, request: handler(request),
        )
        monkeypatch.setattr(_ws, "check_ssrf", guard)
        result = WebSearchTool(engine="youcom").execute(
            query="https://public.example.com/start"
        )

        assert result.success is False
        assert "127.0.0.1" in result.content
        assert requests == ["https://public.example.com/start"]
        assert [call.args[0] for call in guard.call_args_list] == [
            "https://public.example.com/start",
            "https://public.example.com/start",
            "http://127.0.0.1/admin",
        ]

    def test_url_public_redirect_is_followed_after_ssrf_check(self, monkeypatch):
        """Public relative redirects still work when checked hop by hop."""
        import httpx

        import openjarvis.tools.web_search as _ws

        requests = []

        def handler(request):
            requests.append(str(request.url))
            if request.url.path == "/start":
                return httpx.Response(
                    302,
                    headers={"location": "/article"},
                    request=request,
                )
            return httpx.Response(
                200,
                text="public article",
                headers={"content-type": "text/html"},
                request=request,
            )

        guard = MagicMock(return_value=None)
        monkeypatch.setattr(
            httpx.HTTPTransport,
            "handle_request",
            lambda self, request: handler(request),
        )
        monkeypatch.setattr(_ws, "check_ssrf", guard)
        result = WebSearchTool(engine="youcom").execute(
            query="https://public.example.com/start"
        )

        assert result.success is True
        assert result.content == "public article"
        assert requests == [
            "https://public.example.com/start",
            "https://public.example.com/article",
        ]
        assert [call.args[0] for call in guard.call_args_list] == [
            "https://public.example.com/start",
            "https://public.example.com/start",
            "https://public.example.com/article",
        ]


# ---------------------------------------------------------------------------
# Engine selection and the You.com engine (#923)
# ---------------------------------------------------------------------------


class TestEngineSelection:
    def test_auto_prefers_tavily_when_its_key_is_set(self, monkeypatch):
        """Existing installs are unchanged: a Tavily key still means Tavily."""
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        monkeypatch.delenv("OPENJARVIS_WEB_SEARCH_ENGINE", raising=False)
        assert WebSearchTool()._resolve_engine() == "tavily"

    def test_auto_uses_youcom_without_any_key(self, monkeypatch):
        """The zero-config path is API-backed rather than the DDG scrape."""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        monkeypatch.delenv("OPENJARVIS_WEB_SEARCH_ENGINE", raising=False)
        assert WebSearchTool()._resolve_engine() == "youcom"

    def test_auto_prefers_serply_over_the_keyless_tier(self, monkeypatch):
        """A Serply key only ever wins over having no key at all."""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        monkeypatch.delenv("OPENJARVIS_WEB_SEARCH_ENGINE", raising=False)
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")
        assert WebSearchTool()._resolve_engine() == "serply"

    def test_serply_never_displaces_an_existing_keyed_engine(self, monkeypatch):
        """Adding a Serply key must not change where an install already goes."""
        monkeypatch.delenv("OPENJARVIS_WEB_SEARCH_ENGINE", raising=False)
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")

        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-key")
        assert WebSearchTool()._resolve_engine() == "tavily"

        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert WebSearchTool()._resolve_engine() == "youcom"

    def test_auto_prefers_firecrawl_over_the_keyless_tier(self, monkeypatch):
        """A Firecrawl key only ever wins over having no key at all."""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        monkeypatch.delenv("OPENJARVIS_WEB_SEARCH_ENGINE", raising=False)
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        assert WebSearchTool()._resolve_engine() == "firecrawl"

    def test_firecrawl_never_displaces_an_existing_keyed_engine(self, monkeypatch):
        """Adding a Firecrawl key must not change where an install already goes."""
        monkeypatch.delenv("OPENJARVIS_WEB_SEARCH_ENGINE", raising=False)
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")

        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-key")
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")
        assert WebSearchTool()._resolve_engine() == "tavily"

        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert WebSearchTool()._resolve_engine() == "youcom"

        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        assert WebSearchTool()._resolve_engine() == "serply"

    def test_auto_uses_a_keyless_self_hosted_firecrawl(self, monkeypatch):
        """Self-hosted instances usually run without auth, so pointing
        FIRECRAWL_API_URL away from the hosted API is enough to opt in."""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        monkeypatch.delenv("OPENJARVIS_WEB_SEARCH_ENGINE", raising=False)
        monkeypatch.setenv("FIRECRAWL_API_URL", "http://localhost:3002")
        assert WebSearchTool()._resolve_engine() == "firecrawl"

    def test_explicit_engine_overrides_key_presence(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        assert WebSearchTool(engine="youcom")._resolve_engine() == "youcom"
        assert WebSearchTool(engine="duckduckgo")._resolve_engine() == "duckduckgo"

    def test_engine_read_from_environment(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        monkeypatch.setenv("OPENJARVIS_WEB_SEARCH_ENGINE", "youcom")
        assert WebSearchTool()._resolve_engine() == "youcom"

    def test_unknown_engine_falls_back_to_auto(self, monkeypatch, caplog):
        """A typo in the env must not break tool loading."""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.setenv("OPENJARVIS_WEB_SEARCH_ENGINE", "yuo.com")
        with caplog.at_level("WARNING"):
            tool = WebSearchTool()
        assert tool._resolve_engine() == "youcom"
        assert "Unknown web search engine" in caplog.text

    def test_spec_reports_engine_and_optional_keys(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        monkeypatch.delenv("OPENJARVIS_WEB_SEARCH_ENGINE", raising=False)
        spec = WebSearchTool().spec
        assert spec.metadata["engine"] == "youcom"
        assert "YOUDOTCOM_API_KEY" in spec.metadata["optional_api_keys"]
        assert "SERPLY_API_KEY" in spec.metadata["optional_api_keys"]
        assert "serply" in spec.metadata["engines"]
        assert "FIRECRAWL_API_KEY" in spec.metadata["optional_api_keys"]
        assert "firecrawl" in spec.metadata["engines"]
        # Backwards compatible for readers of the old single-key field.
        assert spec.metadata["requires_api_key"] == "TAVILY_API_KEY"


class TestYouComSearch:
    """The You.com engine, exercised against mocked HTTP."""

    PAYLOAD = {
        "results": {
            "web": [
                {
                    "url": "https://example.com/a",
                    "title": "Result A",
                    "description": "Desc A",
                    "snippets": ["Snippet A1", "Snippet A2"],
                },
                {
                    "url": "https://example.com/b",
                    "title": "Result B",
                    "description": "Desc B only",
                },
            ],
            "news": [
                {
                    "url": "https://example.com/n",
                    "title": "News N",
                    "snippets": ["Snippet N"],
                }
            ],
        },
        "metadata": {"query": "test"},
    }

    def _mock_get(self, monkeypatch, payload=None, status=200):
        import httpx

        calls = {}

        def _get(url, **kwargs):
            calls["url"] = url
            calls["params"] = kwargs.get("params")
            calls["headers"] = kwargs.get("headers")
            resp = MagicMock()
            resp.status_code = status
            resp.json.return_value = payload if payload is not None else self.PAYLOAD
            if status >= 400:
                resp.text = "error body"
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    f"HTTP {status}", request=MagicMock(), response=resp
                )
            else:
                resp.raise_for_status = MagicMock()
            return resp

        monkeypatch.setattr(httpx, "get", _get)
        return calls

    def test_keyless_endpoint_and_no_key_header(self, monkeypatch):
        """A stale key must never reach the keyless path — it 401s there."""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        calls = self._mock_get(monkeypatch)

        result = WebSearchTool(engine="youcom").execute(query="test query")

        assert result.success is True
        assert calls["url"] == "https://api.you.com/v1/agents/search"
        assert "X-API-Key" not in calls["headers"]
        assert result.metadata["youcom_tier"] == "keyless"

    def test_keyed_endpoint_when_key_is_set(self, monkeypatch):
        monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-key")
        calls = self._mock_get(monkeypatch)

        result = WebSearchTool(engine="youcom").execute(query="test query")

        assert calls["url"] == "https://api.you.com/v1/search"
        assert calls["headers"]["X-API-Key"] == "ydc-key"
        assert result.metadata["youcom_tier"] == "keyed"

    def test_sends_attribution_user_agent(self, monkeypatch):
        """Keyless traffic carries no key, so the User-Agent is the only
        signal identifying OpenJarvis to You.com."""
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        calls = self._mock_get(monkeypatch)

        WebSearchTool(engine="youcom").execute(query="test query")

        assert (
            "youdotcom-integration/open-jarvis-openjarvis"
            in (calls["headers"]["User-Agent"])
        )

    def test_result_format_matches_tavily(self, monkeypatch):
        """Same labeled Source/Summary shape agents already parse (#390)."""
        self._mock_get(monkeypatch)

        result = WebSearchTool(engine="youcom").execute(query="test query")

        assert "### Result A" in result.content
        assert "Source: https://example.com/a" in result.content
        assert "Summary: Snippet A1\nSnippet A2" in result.content
        # description is the fallback when a result carries no snippets
        assert "Summary: Desc B only" in result.content
        # news results are included after web results
        assert "### News N" in result.content
        assert result.metadata["num_results"] == 3

    def test_max_results_passed_as_count(self, monkeypatch):
        calls = self._mock_get(monkeypatch)
        WebSearchTool(engine="youcom", max_results=3).execute(query="q", max_results=7)
        assert calls["params"] == {"query": "q", "count": 7}

    def test_empty_results(self, monkeypatch):
        self._mock_get(monkeypatch, payload={"results": {}})
        result = WebSearchTool(engine="youcom").execute(query="q")
        assert result.success is True
        assert result.content == "No results found."

    def test_keyless_limit_falls_back_with_upgrade_hint(self, monkeypatch):
        """402/429 on the keyless tier means 'get a key', and the reason has
        to reach the caller instead of vanishing into a debug log."""
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        self._mock_get(monkeypatch, status=402)

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = [
            {"title": "DDG", "href": "https://example.com", "body": "b"}
        ]
        mock_module = MagicMock()
        mock_module.DDGS.return_value = mock_ddgs
        monkeypatch.setitem(sys.modules, "ddgs", mock_module)

        result = WebSearchTool(engine="youcom").execute(query="q")

        assert result.success is True
        assert result.metadata["engine"] == "duckduckgo"
        assert result.metadata["fallback_from"] == "youcom"
        assert result.metadata["degraded"] is True
        assert "YOUDOTCOM_API_KEY" in result.metadata["fallback_reason"]

    def test_keyed_http_error_reports_status_not_upgrade_hint(self, monkeypatch):
        """With a key set, a failure is not a free-tier limit."""
        monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-key")
        self._mock_get(monkeypatch, status=500)

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = []
        mock_module = MagicMock()
        mock_module.DDGS.return_value = mock_ddgs
        monkeypatch.setitem(sys.modules, "ddgs", mock_module)

        result = WebSearchTool(engine="youcom").execute(query="q")

        assert "HTTP 500" in result.metadata["fallback_reason"]
        assert "YOUDOTCOM_API_KEY" not in result.metadata["fallback_reason"]


class TestSerplySearch:
    """The Serply engine, exercised against mocked HTTP."""

    PAYLOAD = {
        "results": [
            {
                "title": "Result A",
                "link": "https://example.com/a",
                "description": "Desc A",
                "position": 1,
                "realPosition": 1,
            },
            {
                "title": "Result B",
                "link": "https://example.com/b",
                "description": "Desc B",
                "position": 2,
                "realPosition": 2,
            },
        ],
        "answers": [],
        "knowledge_graph": {},
        "related_questions": [],
    }

    def _mock_get(self, monkeypatch, payload=None, status=200):
        import httpx

        calls = {}

        def _get(url, **kwargs):
            calls["url"] = url
            calls["params"] = kwargs.get("params")
            calls["headers"] = kwargs.get("headers")
            resp = MagicMock()
            resp.status_code = status
            resp.json.return_value = payload if payload is not None else self.PAYLOAD
            if status >= 400:
                resp.text = "error body"
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    f"HTTP {status}", request=MagicMock(), response=resp
                )
            else:
                resp.raise_for_status = MagicMock()
            return resp

        monkeypatch.setattr(httpx, "get", _get)
        return calls

    def test_endpoint_and_key_header(self, monkeypatch):
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")
        calls = self._mock_get(monkeypatch)

        result = WebSearchTool(engine="serply").execute(query="test query")

        assert result.success is True
        assert calls["url"] == "https://api.serply.io/v1/search"
        assert calls["headers"]["X-Api-Key"] == "srp-x"
        assert result.metadata["engine"] == "serply"

    def test_result_format_matches_the_other_engines(self, monkeypatch):
        """Same labeled Source/Summary shape agents already parse (#390)."""
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")
        self._mock_get(monkeypatch)

        result = WebSearchTool(engine="serply").execute(query="test query")

        assert "### Result A" in result.content
        assert "Source: https://example.com/a" in result.content
        assert "Summary: Desc A" in result.content
        assert "### Result B" in result.content
        assert result.metadata["num_results"] == 2

    def test_max_results_passed_as_num(self, monkeypatch):
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")
        calls = self._mock_get(monkeypatch)
        WebSearchTool(engine="serply", max_results=3).execute(query="q", max_results=7)
        assert calls["params"] == {"q": "q", "num": 7}

    def test_query_reaches_the_api_unmodified(self, monkeypatch):
        """The point of a SERP proxy is that Google's operators survive, so
        nothing here may rewrite, quote or strip the query."""
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")
        calls = self._mock_get(monkeypatch)

        query = "transformer inference site:arxiv.org after:2026-01-01"
        WebSearchTool(engine="serply").execute(query=query)

        assert calls["params"]["q"] == query

    def test_empty_results(self, monkeypatch):
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")
        self._mock_get(monkeypatch, payload={"results": []})
        result = WebSearchTool(engine="serply").execute(query="q")
        assert result.success is True
        assert result.content == "No results found."

    def test_no_proxy_location_header_by_default(self, monkeypatch):
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")
        calls = self._mock_get(monkeypatch)

        result = WebSearchTool(engine="serply").execute(query="q")

        assert "X-Proxy-Location" not in calls["headers"]
        assert "serply_location" not in result.metadata

    def test_proxy_location_header_when_configured(self, monkeypatch):
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")
        monkeypatch.setenv("SERPLY_PROXY_LOCATION", "DE")
        calls = self._mock_get(monkeypatch)

        result = WebSearchTool(engine="serply").execute(query="q")

        assert calls["headers"]["X-Proxy-Location"] == "DE"
        assert result.metadata["serply_location"] == "DE"

    def test_rejected_key_names_the_env_var(self, monkeypatch):
        """A 401 is a credential problem, and the fallback reason has to say
        which variable to fix rather than just 'HTTP 401'."""
        monkeypatch.setenv("SERPLY_API_KEY", "srp-bad")
        self._mock_get(monkeypatch, status=401)

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = []
        mock_module = MagicMock()
        mock_module.DDGS.return_value = mock_ddgs
        monkeypatch.setitem(sys.modules, "ddgs", mock_module)

        result = WebSearchTool(engine="serply").execute(query="q")

        assert result.metadata["fallback_from"] == "serply"
        assert result.metadata["degraded"] is True
        assert "SERPLY_API_KEY" in result.metadata["fallback_reason"]

    def test_other_http_error_reports_the_status(self, monkeypatch):
        monkeypatch.setenv("SERPLY_API_KEY", "srp-x")
        self._mock_get(monkeypatch, status=500)

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = []
        mock_module = MagicMock()
        mock_module.DDGS.return_value = mock_ddgs
        monkeypatch.setitem(sys.modules, "ddgs", mock_module)

        result = WebSearchTool(engine="serply").execute(query="q")

        assert "HTTP 500" in result.metadata["fallback_reason"]
        assert "SERPLY_API_KEY" not in result.metadata["fallback_reason"]


class TestFirecrawlSearch:
    """The Firecrawl engine, exercised against mocked HTTP."""

    PAYLOAD = {
        "success": True,
        "data": {
            "web": [
                {
                    "title": "Result A",
                    "url": "https://example.com/a",
                    "description": "Desc A",
                    "position": 1,
                },
                {
                    "title": "Result B",
                    "url": "https://example.com/b",
                    "description": "Desc B",
                    "position": 2,
                },
            ]
        },
    }

    def _mock_post(self, monkeypatch, payload=None, status=200):
        import httpx

        calls = {}

        def _post(url, **kwargs):
            calls["url"] = url
            calls["json"] = kwargs.get("json")
            calls["headers"] = kwargs.get("headers")
            resp = MagicMock()
            resp.status_code = status
            resp.json.return_value = payload if payload is not None else self.PAYLOAD
            if status >= 400:
                resp.text = "error body"
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    f"HTTP {status}", request=MagicMock(), response=resp
                )
            else:
                resp.raise_for_status = MagicMock()
            return resp

        monkeypatch.setattr(httpx, "post", _post)
        return calls

    def _mock_ddgs(self, monkeypatch):
        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = []
        mock_module = MagicMock()
        mock_module.DDGS.return_value = mock_ddgs
        monkeypatch.setitem(sys.modules, "ddgs", mock_module)

    def test_endpoint_auth_and_origin(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        calls = self._mock_post(monkeypatch)

        result = WebSearchTool(engine="firecrawl").execute(query="test query")

        assert result.success is True
        assert calls["url"] == "https://api.firecrawl.dev/v2/search"
        assert calls["headers"]["Authorization"] == "Bearer fc-test"
        assert calls["json"]["origin"] == "openjarvis"
        assert result.metadata["engine"] == "firecrawl"

    def test_result_format_matches_the_other_engines(self, monkeypatch):
        """Same labeled Source/Summary shape agents already parse (#390)."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        self._mock_post(monkeypatch)

        result = WebSearchTool(engine="firecrawl").execute(query="test query")

        assert "### Result A" in result.content
        assert "Source: https://example.com/a" in result.content
        assert "Summary: Desc A" in result.content
        assert "### Result B" in result.content
        assert result.metadata["num_results"] == 2

    def test_max_results_passed_as_limit(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        calls = self._mock_post(monkeypatch)
        WebSearchTool(engine="firecrawl", max_results=3).execute(
            query="q", max_results=7
        )
        assert calls["json"] == {"query": "q", "limit": 7, "origin": "openjarvis"}

    def test_self_hosted_api_url(self, monkeypatch):
        """FIRECRAWL_API_URL points search at a self-hosted instance."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        monkeypatch.setenv("FIRECRAWL_API_URL", "http://localhost:3002/")
        calls = self._mock_post(monkeypatch)

        WebSearchTool(engine="firecrawl").execute(query="q")

        assert calls["url"] == "http://localhost:3002/v2/search"

    def test_keyless_self_hosted_sends_no_auth_header(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_URL", "http://localhost:3002")
        calls = self._mock_post(monkeypatch)

        result = WebSearchTool(engine="firecrawl").execute(query="q")

        assert result.metadata["engine"] == "firecrawl"
        assert "Authorization" not in calls["headers"]

    def test_long_descriptions_are_capped(self, monkeypatch):
        """Descriptions can carry thousands of characters of page text; five
        of them must still fit a small model's context."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        payload = {
            "data": {
                "web": [
                    {
                        "title": "Long",
                        "url": "https://e.com",
                        "description": "x" * 10000,
                    }
                ]
            }
        }
        self._mock_post(monkeypatch, payload=payload)

        result = WebSearchTool(engine="firecrawl").execute(query="q")

        assert "x" * 500 + "…" in result.content
        assert "x" * 501 not in result.content

    def test_credits_are_reported(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        self._mock_post(monkeypatch, payload={**self.PAYLOAD, "creditsUsed": 2})
        result = WebSearchTool(engine="firecrawl").execute(query="q")
        assert result.metadata["credits"] == 2

    def test_missing_key_is_named_without_a_request(self, monkeypatch):
        """An explicit firecrawl engine with no key against the hosted API
        should say the key is missing, not that it was rejected."""
        import httpx

        monkeypatch.setattr(
            httpx, "post", MagicMock(side_effect=AssertionError("must not be called"))
        )
        self._mock_ddgs(monkeypatch)

        result = WebSearchTool(engine="firecrawl").execute(query="q")

        assert result.metadata["fallback_reason"] == "FIRECRAWL_API_KEY is not set"

    def test_empty_results(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        self._mock_post(monkeypatch, payload={"success": True, "data": {"web": []}})
        result = WebSearchTool(engine="firecrawl").execute(query="q")
        assert result.success is True
        assert result.content == "No results found."

    def test_rejected_key_names_the_env_var(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-bad")
        self._mock_post(monkeypatch, status=401)
        self._mock_ddgs(monkeypatch)

        result = WebSearchTool(engine="firecrawl").execute(query="q")

        assert result.metadata["fallback_from"] == "firecrawl"
        assert result.metadata["degraded"] is True
        assert "FIRECRAWL_API_KEY" in result.metadata["fallback_reason"]

    def test_exhausted_credits_point_to_the_key_page(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        self._mock_post(monkeypatch, status=402)
        self._mock_ddgs(monkeypatch)

        result = WebSearchTool(engine="firecrawl").execute(query="q")

        reason = result.metadata["fallback_reason"]
        assert "credits" in reason
        assert "firecrawl.dev/app/api-keys" in reason

    def test_rate_limit_is_named(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        self._mock_post(monkeypatch, status=429)
        self._mock_ddgs(monkeypatch)

        result = WebSearchTool(engine="firecrawl").execute(query="q")

        assert "rate limit" in result.metadata["fallback_reason"]

    def test_other_http_error_reports_the_status(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        self._mock_post(monkeypatch, status=500)
        self._mock_ddgs(monkeypatch)

        result = WebSearchTool(engine="firecrawl").execute(query="q")

        assert "HTTP 500" in result.metadata["fallback_reason"]
        assert "FIRECRAWL_API_KEY" not in result.metadata["fallback_reason"]


class TestFirecrawlScrapeExtraction:
    def _mock_ssrf(self, monkeypatch):
        import openjarvis.tools.web_search as _ws

        monkeypatch.setattr(_ws, "check_ssrf", lambda url: None)

    def _mock_scrape(self, monkeypatch, markdown):
        import httpx

        resp = MagicMock()
        resp.json.return_value = {"success": True, "data": {"markdown": markdown}}
        resp.raise_for_status = MagicMock()
        post = MagicMock(return_value=resp)
        monkeypatch.setattr(httpx, "post", post)
        return post

    def test_scrape_used_for_url_queries(self, monkeypatch):
        """URL queries come back as markdown instead of the regex HTML strip."""
        self._mock_ssrf(monkeypatch)
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        post = self._mock_scrape(monkeypatch, "# Heading\n\nBody text.")

        result = WebSearchTool(engine="firecrawl").execute(
            query="https://example.com/a.pdf"
        )

        assert result.success is True
        assert result.content == "# Heading\n\nBody text."
        assert result.metadata["extractor"] == "firecrawl_scrape"
        assert post.call_args.args[0] == "https://api.firecrawl.dev/v2/scrape"
        assert post.call_args.kwargs["json"] == {
            "url": "https://example.com/a.pdf",
            "formats": ["markdown"],
            "onlyMainContent": True,
            "parsers": [{"type": "pdf", "maxPages": 3}],
            "timeout": 45000,
            "origin": "openjarvis",
        }

    def test_scrape_output_is_truncated_like_the_local_fetch(self, monkeypatch):
        """A long PDF must not flood a small model's context."""
        self._mock_ssrf(monkeypatch)
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        self._mock_scrape(monkeypatch, "x" * 10000)

        result = WebSearchTool(engine="firecrawl").execute(
            query="https://example.com/a"
        )

        assert result.content.startswith("x" * 6000)
        assert result.content.endswith("[Content truncated]")
        assert len(result.content) < 6100

    def test_keyless_self_hosted_scrape(self, monkeypatch):
        self._mock_ssrf(monkeypatch)
        monkeypatch.setenv("FIRECRAWL_API_URL", "http://localhost:3002")
        post = self._mock_scrape(monkeypatch, "# Self-hosted")

        result = WebSearchTool(engine="firecrawl").execute(
            query="https://example.com/a"
        )

        assert result.content == "# Self-hosted"
        assert post.call_args.args[0] == "http://localhost:3002/v2/scrape"
        assert "Authorization" not in post.call_args.kwargs["headers"]

    def test_url_query_without_key_uses_local_fetch(self, monkeypatch):
        """Explicit firecrawl with no key and the hosted URL never calls the
        API for URL queries; the local fetch handles them as before."""
        self._mock_ssrf(monkeypatch)
        import httpx

        monkeypatch.setattr(
            httpx, "post", MagicMock(side_effect=AssertionError("must not be called"))
        )
        resp = MagicMock()
        resp.text = "<html><body>Local text</body></html>"
        resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx.Client, "get", MagicMock(return_value=resp))

        result = WebSearchTool(engine="firecrawl").execute(
            query="https://example.com/a"
        )

        assert result.metadata["extractor"] == "local"

    def test_scrape_failure_falls_back_to_local_fetch(self, monkeypatch):
        self._mock_ssrf(monkeypatch)
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        import httpx

        monkeypatch.setattr(
            httpx, "post", MagicMock(side_effect=httpx.ConnectError("down"))
        )
        resp = MagicMock()
        resp.text = "<html><body>Local text</body></html>"
        resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx.Client, "get", MagicMock(return_value=resp))

        result = WebSearchTool(engine="firecrawl").execute(
            query="https://example.com/a"
        )

        assert result.success is True
        assert "Local text" in result.content
        assert result.metadata["extractor"] == "local"

    def test_url_branch_ssrf_blocked_before_scrape_call(self, monkeypatch):
        """The scrape upgrade must not become an SSRF bypass."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        import openjarvis.tools.web_search as _ws

        monkeypatch.setattr(_ws, "check_ssrf", lambda url: "private IP blocked")
        import httpx

        monkeypatch.setattr(
            httpx, "post", MagicMock(side_effect=AssertionError("must not be called"))
        )

        result = WebSearchTool(engine="firecrawl").execute(
            query="http://169.254.169.254/metadata"
        )

        assert result.success is False
        assert "private IP blocked" in result.content


class TestFallbackVisibility:
    def test_fallback_is_logged_at_warning(self, monkeypatch, caplog):
        """Regression for the silent-degradation half of #923: a typo'd key
        used to look identical to a working install with quieter results."""
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        import httpx

        def _boom(*args, **kwargs):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx, "get", _boom)

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = []
        mock_module = MagicMock()
        mock_module.DDGS.return_value = mock_ddgs
        monkeypatch.setitem(sys.modules, "ddgs", mock_module)

        with caplog.at_level("WARNING"):
            result = WebSearchTool(engine="youcom").execute(query="q")

        assert "falling back to DuckDuckGo" in caplog.text
        assert result.metadata["degraded"] is True

    def test_duckduckgo_engine_is_not_marked_degraded(self, monkeypatch):
        """Choosing DDG deliberately is not a degradation."""
        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = [
            {"title": "DDG", "href": "https://example.com", "body": "b"}
        ]
        mock_module = MagicMock()
        mock_module.DDGS.return_value = mock_ddgs
        monkeypatch.setitem(sys.modules, "ddgs", mock_module)

        result = WebSearchTool(engine="duckduckgo").execute(query="q")

        assert result.metadata["engine"] == "duckduckgo"
        assert "degraded" not in result.metadata

    def test_missing_ddgs_reports_only_ddgs(self, monkeypatch):
        """The old message named tavily-python even when Tavily was not in
        play; the remaining hard requirement is ddgs."""
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        import httpx

        monkeypatch.setattr(
            httpx, "get", MagicMock(side_effect=httpx.ConnectError("down"))
        )
        monkeypatch.delitem(sys.modules, "ddgs", raising=False)
        import builtins

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "ddgs":
                raise ImportError("No module named 'ddgs'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        result = WebSearchTool(engine="youcom").execute(query="q")

        assert result.success is False
        assert "ddgs" in result.content


class TestYouComContentsExtraction:
    def _mock_ssrf(self, monkeypatch):
        import openjarvis.tools.web_search as _ws

        monkeypatch.setattr(_ws, "check_ssrf", lambda url: None)

    def test_contents_used_for_url_queries_when_keyed(self, monkeypatch):
        """The URL branch upgrades from the regex HTML strip to extracted
        markdown when a key is available."""
        self._mock_ssrf(monkeypatch)
        monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-key")
        import httpx

        resp = MagicMock()
        resp.json.return_value = [
            {"url": "https://example.com/a", "markdown": "# Heading\n\nBody text."}
        ]
        resp.raise_for_status = MagicMock()
        post = MagicMock(return_value=resp)
        monkeypatch.setattr(httpx, "post", post)

        result = WebSearchTool(engine="youcom").execute(query="https://example.com/a")

        assert result.success is True
        assert result.content == "# Heading\n\nBody text."
        assert result.metadata["extractor"] == "youcom_contents"
        assert post.call_args.kwargs["json"]["formats"] == ["markdown"]

    def test_keyless_url_query_uses_local_fetch(self, monkeypatch):
        """Contents needs a key, so keyless installs keep the local fetch."""
        self._mock_ssrf(monkeypatch)
        monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
        import httpx

        resp = MagicMock()
        resp.text = "<html><body>Local text</body></html>"
        resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx.Client, "get", MagicMock(return_value=resp))
        monkeypatch.setattr(
            httpx, "post", MagicMock(side_effect=AssertionError("must not be called"))
        )

        result = WebSearchTool(engine="youcom").execute(query="https://example.com/a")

        assert "Local text" in result.content
        assert result.metadata["extractor"] == "local"

    def test_contents_failure_falls_back_to_local_fetch(self, monkeypatch):
        self._mock_ssrf(monkeypatch)
        monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-key")
        import httpx

        monkeypatch.setattr(
            httpx, "post", MagicMock(side_effect=httpx.ConnectError("down"))
        )
        resp = MagicMock()
        resp.text = "<html><body>Local text</body></html>"
        resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx.Client, "get", MagicMock(return_value=resp))

        result = WebSearchTool(engine="youcom").execute(query="https://example.com/a")

        assert result.success is True
        assert "Local text" in result.content
        assert result.metadata["extractor"] == "local"

    def test_url_branch_ssrf_blocked_before_contents_call(self, monkeypatch):
        """The Contents upgrade must not become an SSRF bypass."""
        monkeypatch.setenv("YOUDOTCOM_API_KEY", "ydc-key")
        import openjarvis.tools.web_search as _ws

        monkeypatch.setattr(_ws, "check_ssrf", lambda url: "private IP blocked")
        import httpx

        monkeypatch.setattr(
            httpx, "post", MagicMock(side_effect=AssertionError("must not be called"))
        )

        result = WebSearchTool(engine="youcom").execute(
            query="http://169.254.169.254/metadata"
        )

        assert result.success is False
        assert "private IP blocked" in result.content
