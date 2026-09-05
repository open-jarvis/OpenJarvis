"""Web search tool — You.com or Tavily, with a DuckDuckGo fallback.

Engine selection is explicit (``engine=`` or ``OPENJARVIS_WEB_SEARCH_ENGINE``)
rather than a chain of ``try``/``except`` layers. The default, ``"auto"``,
resolves to whichever engine the environment can actually serve, preferring an
API-backed engine over the DuckDuckGo HTML scrape:

* ``TAVILY_API_KEY`` set → Tavily (unchanged for existing installs)
* ``YOUDOTCOM_API_KEY`` set → You.com, keyed
* neither → You.com, keyless free tier (no signup, rate limited per IP)

The keyless tier is what makes a fresh install API-backed with zero config.
DuckDuckGo remains the last resort for every engine, and dropping to it is now
logged at WARNING with the reason, so a typo'd key no longer looks identical to
a working install with quieter results.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urljoin

from openjarvis import __version__
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.security.ssrf import check_ssrf
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


YOUCOM_KEYED_SEARCH_URL = "https://api.you.com/v1/search"
YOUCOM_KEYLESS_SEARCH_URL = "https://api.you.com/v1/agents/search"
YOUCOM_CONTENTS_URL = "https://api.you.com/v1/contents"
YOUCOM_API_KEY_ENV = "YOUDOTCOM_API_KEY"

ENGINE_ENV = "OPENJARVIS_WEB_SEARCH_ENGINE"
ENGINES = ("auto", "youcom", "tavily", "duckduckgo")
_MAX_FETCH_REDIRECTS = 5
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})

# Identifies OpenJarvis to You.com. The keyless tier carries no API key, so the
# User-Agent is the only attribution signal; sent to You.com hosts only.
YOUCOM_USER_AGENT = (
    f"openjarvis/{__version__} youdotcom-integration/open-jarvis-openjarvis"
)

# Keyless tier exhaustion (402) and per-IP throttling (429) both mean "get a
# key", which is a different remedy from a generic HTTP failure.
_KEYLESS_LIMIT_STATUSES = (402, 429)
YOUCOM_PLATFORM_URL = (
    "https://you.com/platform"
    "?utm_source=open-jarvis-openjarvis&utm_medium=oss_integration"
    "&utm_campaign=2026-09-oss-integrations&utm_content=error-message"
)
_KEY_UPGRADE_HINT = (
    f"You.com keyless free-tier limit reached. Set {YOUCOM_API_KEY_ENV} for "
    f"higher limits — a free key is available at {YOUCOM_PLATFORM_URL}"
)


class _WebSearchEngineError(RuntimeError):
    """An engine failed in a way that should be reported, not swallowed."""


@ToolRegistry.register("web_search")
class WebSearchTool(BaseTool):
    """Search the web via You.com or Tavily, falling back to DuckDuckGo."""

    tool_id = "web_search"
    is_local = False

    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = 5,
        *,
        engine: str | None = None,
        youcom_api_key: str | None = None,
    ):
        """Configure the search engine.

        ``api_key`` remains the Tavily key, positionally, for backwards
        compatibility. ``engine`` is one of :data:`ENGINES`; when omitted it
        comes from ``OPENJARVIS_WEB_SEARCH_ENGINE`` and defaults to ``"auto"``.
        An unknown engine name falls back to ``"auto"`` with a warning rather
        than raising, so a typo in the environment cannot break tool loading.
        """
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY")
        self._youcom_api_key = youcom_api_key or os.environ.get(YOUCOM_API_KEY_ENV)
        self._max_results = max_results

        requested = (engine or os.environ.get(ENGINE_ENV) or "auto").strip().lower()
        if requested not in ENGINES:
            logger.warning(
                "Unknown web search engine %r (expected one of %s); using 'auto'",
                requested,
                ", ".join(ENGINES),
            )
            requested = "auto"
        self._engine = requested

    def _resolve_engine(self) -> str:
        """Resolve ``auto`` to a concrete engine from what the env can serve.

        Tavily wins when its key is set so existing installs are unchanged.
        Otherwise You.com handles the query — keyed if a key is present,
        keyless if not, which is the zero-config API-backed path.
        """
        if self._engine != "auto":
            return self._engine
        if self._api_key:
            return "tavily"
        return "youcom"

    @property
    def spec(self) -> ToolSpec:
        engine = self._resolve_engine()
        return ToolSpec(
            name="web_search",
            description=(
                "Search the web for current information."
                " Returns relevant search results."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return.",
                    },
                },
                "required": ["query"],
            },
            category="search",
            metadata={
                # Kept for backwards compatibility: existing readers (Settings
                # UI, tools endpoint) expect a single Tavily key name here.
                "requires_api_key": "TAVILY_API_KEY",
                # web_search needs no key at all on the You.com keyless tier,
                # so the keys above are upgrades rather than prerequisites.
                "optional_api_keys": ["TAVILY_API_KEY", YOUCOM_API_KEY_ENV],
                "engine": engine,
                "engines": list(ENGINES),
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
        """Fetch a URL and return extracted text after checking each redirect."""
        import re as _re

        import httpx

        url = WebSearchTool._normalize_url(url)
        current_url = url.strip()
        for _ in range(_MAX_FETCH_REDIRECTS + 1):
            ssrf_error = check_ssrf(current_url)
            if ssrf_error:
                raise ValueError(ssrf_error)
            resp = httpx.get(
                current_url,
                follow_redirects=False,
                timeout=30.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; OpenJarvis/1.0; +https://github.com/openjarvis)"
                },
            )
            if resp.status_code not in _REDIRECT_STATUS_CODES:
                resp.raise_for_status()
                break
            location = resp.headers.get("location", "")
            if not location:
                resp.raise_for_status()
                break
            current_url = urljoin(str(resp.url), location)
        else:
            raise ValueError(
                f"URL exceeded the maximum of {_MAX_FETCH_REDIRECTS} redirects"
            )
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

    def _youcom_request(self, path_is_keyed: bool) -> tuple[str, dict[str, str]]:
        """Pick the You.com endpoint and its headers together.

        The keyless endpoint rejects an API key, and the keyed endpoint
        requires one, so URL and headers must be chosen in one step — a stale
        key sent to the keyless path 401s.
        """
        headers = {"Accept": "application/json", "User-Agent": YOUCOM_USER_AGENT}
        if path_is_keyed:
            headers["X-API-Key"] = self._youcom_api_key or ""
            return YOUCOM_KEYED_SEARCH_URL, headers
        return YOUCOM_KEYLESS_SEARCH_URL, headers

    @staticmethod
    def _format_youcom_results(payload: dict[str, Any]) -> tuple[str, int]:
        """Render a You.com search payload in the shared result format.

        Web results come before news. Snippets carry the page text the agent
        should synthesize from; ``description`` is the fallback when a result
        has none.
        """
        results = payload.get("results") or {}
        parts: list[str] = []
        count = 0
        for section in ("web", "news"):
            for item in results.get(section) or []:
                title = item.get("title") or "Untitled"
                url = item.get("url", "")
                snippets = item.get("snippets") or []
                content = (
                    "\n".join(snippets) if snippets else item.get("description", "")
                )
                parts.append(f"### {title}\nSource: {url}\nSummary: {content}")
                count += 1
        return "\n\n---\n\n".join(parts), count

    def _youcom_search(self, query: str, max_results: int) -> ToolResult:
        """Search via You.com, keyed when a key is set and keyless otherwise."""
        import httpx

        keyed = bool(self._youcom_api_key)
        url, headers = self._youcom_request(keyed)
        try:
            response = httpx.get(
                url,
                params={"query": query, "count": max_results},
                headers=headers,
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if not keyed and status in _KEYLESS_LIMIT_STATUSES:
                raise _WebSearchEngineError(_KEY_UPGRADE_HINT) from exc
            raise _WebSearchEngineError(
                f"You.com search failed with HTTP {status}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise _WebSearchEngineError(f"You.com search failed: {exc}") from exc

        formatted, count = self._format_youcom_results(payload)
        return ToolResult(
            tool_name="web_search",
            content=formatted or "No results found.",
            success=True,
            metadata={
                "num_results": count,
                "engine": "youcom",
                "youcom_tier": "keyed" if keyed else "keyless",
            },
        )

    def _youcom_extract(self, url: str) -> str | None:
        """Return You.com-extracted markdown for ``url``, or ``None``.

        The Contents API needs a key, so this is an upgrade over the regex HTML
        strip in :meth:`_fetch_url` rather than a replacement for it. Any
        failure returns ``None`` and the caller falls back to the local fetch.
        """
        if not self._youcom_api_key:
            return None

        import httpx

        try:
            response = httpx.post(
                YOUCOM_CONTENTS_URL,
                json={"urls": [url], "formats": ["markdown"]},
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": YOUCOM_USER_AGENT,
                    "X-API-Key": self._youcom_api_key,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "You.com Contents extraction failed for %s (%s); falling back to "
                "local HTML extraction",
                url,
                type(exc).__name__,
            )
            return None

        items = payload if isinstance(payload, list) else payload.get("results") or []
        for item in items:
            markdown = (item or {}).get("markdown")
            if markdown:
                return str(markdown)
        return None

    def _duckduckgo_search(self, query: str, max_results: int) -> str:
        """Search using DuckDuckGo as fallback."""
        from ddgs import DDGS

        ddgs = DDGS()
        raw_results = list(ddgs.text(query, max_results=max_results))
        results = []
        for r in raw_results:
            title = r.get("title", "Untitled")
            url = r.get("href", "")
            snippet = r.get("body", "")
            results.append(f"### {title}\nSource: {url}\nSummary: {snippet}")

        formatted = "\n\n---\n\n".join(results)
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
            if self._resolve_engine() == "youcom":
                ssrf_error = check_ssrf(self._normalize_url(url))
                if ssrf_error:
                    return ToolResult(
                        tool_name="web_search",
                        content=f"Failed to fetch URL: {ssrf_error}",
                        success=False,
                    )
                extracted = self._youcom_extract(url)
                if extracted:
                    return ToolResult(
                        tool_name="web_search",
                        content=extracted,
                        success=True,
                        metadata={
                            "url": url,
                            "mode": "fetch",
                            "extractor": "youcom_contents",
                        },
                    )
            try:
                content = self._fetch_url(url)
                return ToolResult(
                    tool_name="web_search",
                    content=content or "No content found at URL.",
                    success=True,
                    metadata={"url": url, "mode": "fetch", "extractor": "local"},
                )
            except Exception as exc:
                return ToolResult(
                    tool_name="web_search",
                    content=f"Failed to fetch URL: {exc}",
                    success=False,
                )

        max_results = params.get("max_results", self._max_results)
        engine = self._resolve_engine()

        if engine == "duckduckgo":
            return self._duckduckgo_result(query, max_results)

        try:
            if engine == "youcom":
                return self._youcom_search(query, max_results)
            return self._tavily_search(query, max_results)
        except _WebSearchEngineError as exc:
            reason = str(exc)
        except Exception as exc:  # engine SDKs raise their own error types
            reason = f"{type(exc).__name__}: {exc}"

        # Falling back is a degradation in result quality, so say so at WARNING
        # rather than DEBUG — a typo'd key used to look like a quiet install.
        logger.warning(
            "%s engine failed (%s); falling back to DuckDuckGo, which returns "
            "unranked scraped results",
            engine,
            reason,
        )
        return self._duckduckgo_result(
            query, max_results, fallback_from=engine, reason=reason
        )

    def _tavily_search(self, query: str, max_results: int) -> ToolResult:
        """Search via the Tavily API."""
        from tavily import TavilyClient

        client = TavilyClient(api_key=self._api_key)
        response = client.search(
            query,
            max_results=max_results,
            search_depth="advanced",
            include_usage=True,
        )
        results = response.get("results", [])
        formatted_parts = []
        for r in results:
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            content = r.get("content", "") or r.get("snippet", "")
            formatted_parts.append(f"### {title}\nSource: {url}\nSummary: {content}")

        formatted = "\n\n---\n\n".join(formatted_parts)
        return ToolResult(
            tool_name="web_search",
            content=formatted or "No results found.",
            success=True,
            metadata={
                "num_results": len(results),
                "engine": "tavily",
                "credits": (response.get("usage") or {}).get("credits"),
            },
        )

    def _duckduckgo_result(
        self,
        query: str,
        max_results: int,
        *,
        fallback_from: str | None = None,
        reason: str | None = None,
    ) -> ToolResult:
        """Run the DuckDuckGo scrape and record why it was used."""
        metadata: dict[str, Any] = {"engine": "duckduckgo"}
        if fallback_from:
            metadata["fallback_from"] = fallback_from
            metadata["degraded"] = True
            if reason:
                metadata["fallback_reason"] = reason

        try:
            formatted = self._duckduckgo_search(query, max_results)
            return ToolResult(
                tool_name="web_search",
                content=formatted or "No results found.",
                success=True,
                metadata=metadata,
            )
        except ImportError:
            return ToolResult(
                tool_name="web_search",
                content=(
                    "No search engine available: ddgs is not installed."
                    " Install with: pip install ddgs"
                ),
                success=False,
                metadata=metadata,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="web_search",
                content=f"Search error: {exc}",
                success=False,
                metadata=metadata,
            )


__all__ = ["WebSearchTool"]
