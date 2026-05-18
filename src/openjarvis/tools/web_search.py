"""Web search tool — SearXNG (optional), Tavily API, DuckDuckGo fallback."""

from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.security.ssrf import check_ssrf
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_GROUNDING_REMINDER = (
    "\n\n---\nGrounding: Summarize only what appears in the snippets above. "
    "Do not invent headlines, names, or events. If results are empty, vague, "
    "or off-topic, say so. For a specific site, use a query like "
    "``site:example.com keywords`` or pass the page ``https://...`` URL as the "
    "query to fetch extracted text."
)


@ToolRegistry.register("web_search")
class WebSearchTool(BaseTool):
    """Search the web via Tavily API."""

    tool_id = "web_search"
    is_local = False

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY")
        self._max_results = max_results

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search",
            description=(
                "Search the web (SearXNG, Tavily, or DuckDuckGo). "
                "You MUST call this tool with a concrete ``query`` before "
                "answering questions about current events — do not answer from "
                "memory alone. "
                "For one site use ``site:example.com keywords`` or paste a "
                "full ``https://...`` URL as ``query`` to fetch page text. "
                "In your reply, stick to titles and snippets returned here."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query or full https URL to fetch. "
                            "Use site:domain for one portal."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return.",
                    },
                },
                "required": ["query"],
            },
            category="search",
            metadata={
                "requires_api_key": "TAVILY_API_KEY",
                "optional": "SEARXNG_URL or [tools] searxng_url",
                "fallback": "duckduckgo",
            },
        )

    @staticmethod
    def _is_url(text: str) -> bool:
        """Check if text is a URL."""
        stripped = text.strip()
        return stripped.startswith("http://") or stripped.startswith("https://")

    @staticmethod
    def _extract_url(text: str) -> str | None:
        """Extract the first URL from text, if any."""
        import re as _re

        match = _re.search(r"https?://[^\s,;\"'<>]+", text)
        return match.group(0).rstrip(".,;)") if match else None

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Convert known PDF URLs to their HTML equivalents."""
        import re as _re

        # arxiv: /pdf/ID → /abs/ID (abstract page with full metadata)
        m = _re.match(r"(https?://arxiv\.org)/pdf/(.+?)(?:\.pdf)?$", url)
        if m:
            return f"{m.group(1)}/abs/{m.group(2)}"
        return url

    @staticmethod
    def _fetch_url(url: str, max_chars: int = 6000) -> str:
        """Fetch a URL and return extracted text content."""
        import re as _re

        import httpx

        url = WebSearchTool._normalize_url(url)
        ssrf_error = check_ssrf(url)
        if ssrf_error:
            raise ValueError(ssrf_error)
        resp = httpx.get(
            url.strip(),
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; OpenJarvis/1.0; +https://github.com/openjarvis)"
            },
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/pdf" in content_type:
            return (
                "[This URL points to a PDF file which"
                f" cannot be read directly. URL: {url}]"
            )
        html = resp.text
        # Strip script/style tags and their contents
        html = _re.sub(
            r"<(script|style)[^>]*>.*?</\1>",
            "",
            html,
            flags=_re.DOTALL | _re.IGNORECASE,
        )
        # Strip HTML tags
        text = _re.sub(r"<[^>]+>", " ", html)
        # Collapse whitespace
        text = _re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[Content truncated]"
        return text

    def _duckduckgo_search(self, query: str, max_results: int) -> str:
        """Search using DuckDuckGo as fallback."""
        from ddgs import DDGS

        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=max_results))
        formatted = "\n\n".join(
            f"**{r.get('title', 'Untitled')}**\n"
            f"{r.get('href', '')}\n{r.get('body', '')}"
            for r in results
        )
        return formatted

    def _searxng_base_url(self) -> str:
        """Resolve SearXNG base URL: env overrides ``[tools].searxng_url``."""
        for key in ("SEARXNG_URL", "OPENJARVIS_SEARXNG_URL"):
            v = (os.environ.get(key) or "").strip()
            if v:
                return v.rstrip("/")
        try:
            from openjarvis.core.config import load_config

            u = (load_config().tools.searxng_url or "").strip()
            return u.rstrip("/")
        except Exception:
            return ""

    def _searxng_language(self) -> str:
        """BCP 47 language for SearXNG (e.g. pl, en). Env overrides config."""
        for key in ("SEARXNG_LANGUAGE", "OPENJARVIS_SEARXNG_LANGUAGE"):
            v = (os.environ.get(key) or "").strip()
            if v:
                return v
        try:
            from openjarvis.core.config import load_config

            return (load_config().tools.searxng_language or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _with_grounding(body: str) -> str:
        """Append anti-hallucination hint for the model (observation text)."""
        text = (body or "").strip()
        if not text:
            return body
        return text + _GROUNDING_REMINDER

    def _searxng_search(self, base_url: str, query: str, max_results: int) -> str:
        """Query a SearXNG instance (``GET /search?format=json``)."""
        import httpx

        qparams: dict[str, str] = {
            "q": query,
            "format": "json",
            "categories": "general",
        }
        lang = self._searxng_language()
        if lang:
            qparams["language"] = lang
        params = urllib.parse.urlencode(qparams)
        url = f"{base_url.rstrip('/')}/search?{params}"
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; OpenJarvis/1.0; +https://github.com/open-jarvis)"
            },
        )
        resp.raise_for_status()
        data = resp.json()
        results = list(data.get("results") or [])[:max_results]
        formatted = "\n\n".join(
            f"**{r.get('title', 'Untitled')}**\n"
            f"{r.get('url', '')}\n{r.get('content', '')}"
            for r in results
        )
        return formatted

    def execute(self, **params: Any) -> ToolResult:
        query = params.get("query", "")
        if not query:
            return ToolResult(
                tool_name="web_search",
                content="No query provided.",
                success=False,
            )

        # If the query contains a URL, fetch it directly instead of searching
        url = self._extract_url(query) if not self._is_url(query) else query.strip()
        if url:
            try:
                content = self._fetch_url(url)
                return ToolResult(
                    tool_name="web_search",
                    content=self._with_grounding(content or "No content found at URL."),
                    success=True,
                    metadata={"url": url, "mode": "fetch"},
                )
            except Exception as exc:
                return ToolResult(
                    tool_name="web_search",
                    content=f"Failed to fetch URL: {exc}",
                    success=False,
                )

        max_results = params.get("max_results", self._max_results)

        searx_base = self._searxng_base_url()
        if searx_base:
            try:
                formatted = self._searxng_search(searx_base, query, max_results)
                return ToolResult(
                    tool_name="web_search",
                    content=self._with_grounding(
                        formatted or "No results found.",
                    ),
                    success=True,
                    metadata={"engine": "searxng", "base_url": searx_base},
                )
            except Exception as exc:
                logger.debug("SearXNG error (%s), falling back", type(exc).__name__)

        try:
            from tavily import TavilyClient

            client = TavilyClient(api_key=self._api_key)
            response = client.search(query, max_results=max_results)
            results = response.get("results", [])
            formatted = "\n\n".join(
                f"**{r.get('title', 'Untitled')}**\n"
                f"{r.get('url', '')}\n{r.get('content', '')}"
                for r in results
            )
            return ToolResult(
                tool_name="web_search",
                content=self._with_grounding(formatted or "No results found."),
                success=True,
                metadata={"num_results": len(results), "engine": "tavily"},
            )
        except Exception as exc:
            logger.debug(
                "Tavily error (%s), falling back to DuckDuckGo", type(exc).__name__
            )

        try:
            formatted = self._duckduckgo_search(query, max_results)
            return ToolResult(
                tool_name="web_search",
                content=self._with_grounding(formatted or "No results found."),
                success=True,
                metadata={"engine": "duckduckgo"},
            )
        except ImportError:
            return ToolResult(
                tool_name="web_search",
                content=(
                    "tavily-python not installed and ddgs not available."
                    " Install with: pip install tavily-python ddgs"
                ),
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="web_search",
                content=f"Search error: {exc}",
                success=False,
            )


__all__ = ["WebSearchTool"]
