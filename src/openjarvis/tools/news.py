"""News tool — recent headlines for a topic or general top stories.

Uses Google News RSS by default (free, no API key), so it works out of the box.
If ``NEWSAPI_KEY`` is set, NewsAPI.org is used instead for richer results.
"""

from __future__ import annotations

import logging
import os
from typing import Any, List
from xml.etree import ElementTree as ET

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_RSS_SEARCH = "https://news.google.com/rss/search"
_RSS_TOP = "https://news.google.com/rss"
_NEWSAPI_EVERYTHING = "https://newsapi.org/v2/everything"
_NEWSAPI_TOP = "https://newsapi.org/v2/top-headlines"
_TIMEOUT = 15.0
_DEFAULT_RESULTS = 5
_MAX_RESULTS = 20
_UA = "Mozilla/5.0 (compatible; OpenJarvis/1.0; +https://github.com/openjarvis)"


@ToolRegistry.register("news")
class NewsTool(BaseTool):
    """Fetch recent news headlines for a query or general top stories."""

    tool_id = "news"
    is_local = False

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("NEWSAPI_KEY")

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="news",
            description=(
                "Get recent news headlines. Provide a query to search a topic,"
                " or omit it for general top stories. No API key required."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Topic to search (e.g. 'AI regulation')."
                            " Leave empty for top headlines."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum headlines to return (default 5).",
                    },
                },
                "required": [],
            },
            category="information",
            metadata={"provider": "google-news-rss", "optional_api_key": "NEWSAPI_KEY"},
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query", "")).strip()
        try:
            max_results = int(params.get("max_results", _DEFAULT_RESULTS) or _DEFAULT_RESULTS)
        except (TypeError, ValueError):
            max_results = _DEFAULT_RESULTS
        max_results = max(1, min(max_results, _MAX_RESULTS))

        try:
            import httpx
        except ImportError:
            return ToolResult(
                tool_name="news",
                content="httpx is not installed. Install with: pip install httpx",
                success=False,
            )

        try:
            with httpx.Client(
                timeout=_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _UA},
            ) as client:
                if self._api_key:
                    items = self._fetch_newsapi(client, query, max_results)
                else:
                    items = self._fetch_rss(client, query, max_results)
        except Exception as exc:
            logger.debug("news fetch failed: %s", exc)
            return ToolResult(
                tool_name="news",
                content=f"News lookup failed: {exc}",
                success=False,
            )

        if not items:
            return ToolResult(
                tool_name="news",
                content="No news found.",
                success=True,
                metadata={"query": query, "count": 0},
            )

        heading = f"Top news for '{query}':" if query else "Top headlines:"
        body = "\n\n".join(items)
        return ToolResult(
            tool_name="news",
            content=f"{heading}\n\n{body}",
            success=True,
            metadata={
                "query": query,
                "count": len(items),
                "engine": "newsapi" if self._api_key else "google_rss",
            },
        )

    @staticmethod
    def _fetch_rss(client: Any, query: str, max_results: int) -> List[str]:
        if query:
            resp = client.get(
                _RSS_SEARCH,
                params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            )
        else:
            resp = client.get(
                _RSS_TOP, params={"hl": "en-US", "gl": "US", "ceid": "US:en"}
            )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items: List[str] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            source = ""
            src_el = item.find("source")
            if src_el is not None and src_el.text:
                source = src_el.text.strip()
            pub = (item.findtext("pubDate") or "").strip()
            if not title:
                continue
            parts = [f"- {title}"]
            meta = " | ".join(p for p in (source, pub) if p)
            if meta:
                parts.append(f"  {meta}")
            if link:
                parts.append(f"  {link}")
            items.append("\n".join(parts))
            if len(items) >= max_results:
                break
        return items

    def _fetch_newsapi(self, client: Any, query: str, max_results: int) -> List[str]:
        if query:
            resp = client.get(
                _NEWSAPI_EVERYTHING,
                params={
                    "q": query,
                    "pageSize": max_results,
                    "sortBy": "publishedAt",
                    "language": "en",
                    "apiKey": self._api_key,
                },
            )
        else:
            resp = client.get(
                _NEWSAPI_TOP,
                params={
                    "country": "us",
                    "pageSize": max_results,
                    "apiKey": self._api_key,
                },
            )
        resp.raise_for_status()
        articles = resp.json().get("articles") or []
        items: List[str] = []
        for art in articles[:max_results]:
            title = (art.get("title") or "").strip()
            if not title:
                continue
            source = (art.get("source") or {}).get("name", "")
            pub = art.get("publishedAt", "")
            url = art.get("url", "")
            parts = [f"- {title}"]
            meta = " | ".join(p for p in (source, pub) if p)
            if meta:
                parts.append(f"  {meta}")
            if url:
                parts.append(f"  {url}")
            items.append("\n".join(parts))
        return items


__all__ = ["NewsTool"]
