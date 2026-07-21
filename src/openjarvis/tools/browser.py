"""Browser automation tools — Playwright-based web interaction."""

from __future__ import annotations

import base64
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


class _BrowserSession:
    """Manages a shared Playwright browser session (lazy init)."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None

    def _ensure_browser(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError(
                "playwright not installed. Install with: uv sync --extra browser"
            )
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._page = self._browser.new_page()

    @property
    def page(self):
        self._ensure_browser()
        return self._page

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._playwright = self._browser = self._page = None


_session = _BrowserSession()


# ---------------------------------------------------------------------------
# Tool 1: BrowserNavigateTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("browser_navigate")
class BrowserNavigateTool(BaseTool):
    """Navigate to a URL in the browser."""

    tool_id = "browser_navigate"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_navigate",
            description=(
                "Navigate to a URL in the browser."
                " Returns the page title and text content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to navigate to.",
                    },
                    "wait_for": {
                        "type": "string",
                        "description": (
                            "Wait condition: 'load', 'domcontentloaded',"
                            " or 'networkidle'. Default: 'load'."
                        ),
                    },
                },
                "required": ["url"],
            },
            category="browser",
            required_capabilities=["network:fetch"],
        )

    def execute(self, **params: Any) -> ToolResult:
        url = params.get("url", "")
        if not url:
            return ToolResult(
                tool_name="browser_navigate",
                content="No URL provided.",
                success=False,
            )

        wait_for = params.get("wait_for", "load")
        if wait_for not in ("load", "domcontentloaded", "networkidle"):
            wait_for = "load"

        # SSRF check — never skipped. check_ssrf falls back to a pure-Python
        # implementation when the Rust backend is unavailable, so an
        # uncompiled extension must not silently disable SSRF protection.
        from openjarvis.security.ssrf import check_ssrf

        ssrf_error = check_ssrf(url)
        if ssrf_error:
            return ToolResult(
                tool_name="browser_navigate",
                content=f"SSRF blocked: {ssrf_error}",
                success=False,
            )

        try:
            page = _session.page
            response = page.goto(url, wait_until=wait_for)
            title = page.title()
            text_content = page.inner_text("body")
            if len(text_content) > 5000:
                text_content = text_content[:5000] + "\n\n[Content truncated]"

            status = response.status if response else None
            return ToolResult(
                tool_name="browser_navigate",
                content=f"Title: {title}\n\n{text_content}",
                success=True,
                metadata={"url": url, "title": title, "status": status},
            )
        except ImportError:
            return ToolResult(
                tool_name="browser_navigate",
                content=(
                    "playwright not installed. Install with: uv sync --extra browser"
                ),
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="browser_navigate",
                content=f"Navigation error: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Tool 2: BrowserClickTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("browser_click")
class BrowserClickTool(BaseTool):
    """Click an element on the page."""

    tool_id = "browser_click"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_click",
            description=(
                "Click an element on the current page. Pass the text you see"
                " on the element (button label, link title), a CSS selector,"
                " or a short description like 'first video result'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": (
                            "Visible text of the element, a CSS selector, or"
                            " a short description (e.g. 'first video result')."
                        ),
                    },
                    "by_text": {
                        "type": "boolean",
                        "description": (
                            "If true, click by text content"
                            " instead of CSS selector. Default: false."
                        ),
                    },
                },
                "required": ["selector"],
            },
            category="browser",
        )

    # Filler words stripped from natural-language descriptions before
    # keyword matching ("the first video result" -> "video").
    _DESC_STOPWORDS = frozenset(
        "the a an first second third last top main big red blue green"
        " result results item element link button option entry row".split()
    )
    _ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3, "last": -1}

    def execute(self, **params: Any) -> ToolResult:
        # Models routinely name this param `target`, `text`, `element` or
        # `query` instead of `selector`; rejecting those costs the whole
        # workflow, so accept the common aliases.
        selector = str(
            params.get("selector")
            or params.get("target")
            or params.get("text")
            or params.get("element")
            or params.get("query")
            or ""
        ).strip()
        if not selector:
            return ToolResult(
                tool_name="browser_click",
                content=(
                    "No selector provided. Pass the visible text of the"
                    " element or a CSS selector."
                ),
                success=False,
            )

        by_text = params.get("by_text", False)

        try:
            page = _session.page
            strategy = self._resolve_and_click(page, selector, by_text)
            return ToolResult(
                tool_name="browser_click",
                content=f"Clicked element: {selector}",
                success=True,
                metadata={
                    "selector": selector,
                    "by_text": by_text,
                    "strategy": strategy,
                },
            )
        except ImportError:
            return ToolResult(
                tool_name="browser_click",
                content=(
                    "playwright not installed. Install with: uv sync --extra browser"
                ),
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="browser_click",
                content=f"Click error: {exc}",
                success=False,
            )

    def _resolve_and_click(self, page: Any, selector: str, by_text: bool) -> str:
        """Resolve *selector* through a strategy ladder and click it.

        LLMs pass anything from precise CSS to plain descriptions like
        "first video result". Strategies from most to least precise: CSS,
        exact text, fuzzy text, YouTube results video title, role-based
        keyword match. Existence is checked with ``count()`` (instant, no
        actionability wait) so bad strategies cost milliseconds; only a
        strategy that actually matched gets a real click timeout. Searches
        the main frame first, then child iframes (consent dialogs and ad
        overlays live there). Returns the name of the winning strategy;
        raises with a list of visible clickable elements when nothing
        matched, so the model can retry sensibly.
        """
        import re

        words = [w for w in re.split(r"\W+", selector.lower()) if w]
        nth = next((self._ORDINALS[w] for w in words if w in self._ORDINALS), 0)

        def candidates(frame: Any) -> list:
            cands = []
            if not by_text:
                cands.append(("css", frame.locator(selector)))
            cands.append(("text-exact", frame.get_by_text(selector, exact=True)))
            cands.append(
                ("text-fuzzy", frame.get_by_text(re.compile(re.escape(selector), re.I)))
            )
            # YouTube search results: "first video result" must click a
            # video title, not the "Videos" filter chip — so this outranks
            # the generic role-based keyword match below.
            try:
                url = frame.url or ""
            except Exception:
                url = ""
            if "youtube." in url and ("video" in words or "result" in words):
                cands.append(("youtube-result", frame.locator("a#video-title")))
            keywords = [w for w in words if w not in self._DESC_STOPWORDS]
            if keywords:
                pat = re.compile(".*".join(re.escape(k) for k in keywords), re.I)
                for role in ("link", "button"):
                    cands.append((f"role-{role}", frame.get_by_role(role, name=pat)))
            return [(n, loc.nth(nth) if nth else loc.first) for n, loc in cands]

        last_error: Exception | None = None
        for index, frame in enumerate(page.frames):
            for strategy, locator in candidates(frame):
                try:
                    if locator.count() == 0:
                        continue
                except Exception:
                    continue  # e.g. selector isn't valid CSS — next rung
                try:
                    locator.click(timeout=8000 if index == 0 else 4000)
                    return strategy
                except Exception as exc:
                    last_error = exc
                    continue

        hint = ""
        try:
            texts = page.evaluate(
                """(limit) => Array.from(
                    document.querySelectorAll('a, button, [role=button], [role=link]')
                ).map(e => (e.innerText || e.getAttribute('aria-label') || '').trim())
                 .filter(t => t && t.length < 80)
                 .filter((t, i, arr) => arr.indexOf(t) === i)
                 .slice(0, limit)""",
                15,
            )
            if texts:
                hint = " Visible clickable elements: " + "; ".join(texts)
        except Exception:
            pass
        detail = f" Last error: {last_error}" if last_error else ""
        raise RuntimeError(
            f"No element matched '{selector}' in the main page or its"
            f" {len(page.frames) - 1} iframe(s).{hint}{detail}"
        )


# ---------------------------------------------------------------------------
# Tool 3: BrowserTypeTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("browser_type")
class BrowserTypeTool(BaseTool):
    """Type text into a form field."""

    tool_id = "browser_type"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_type",
            description=(
                "Type text into a form field on the current page."
                " Can clear the field first or append to existing content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the input field.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type into the field.",
                    },
                    "clear": {
                        "type": "boolean",
                        "description": (
                            "If true, clear the field before typing. Default: true."
                        ),
                    },
                },
                "required": ["selector", "text"],
            },
            category="browser",
        )

    def execute(self, **params: Any) -> ToolResult:
        selector = params.get("selector", "")
        text = params.get("text", "")

        if not selector:
            return ToolResult(
                tool_name="browser_type",
                content="No selector provided.",
                success=False,
            )
        if not text:
            return ToolResult(
                tool_name="browser_type",
                content="No text provided.",
                success=False,
            )

        clear = params.get("clear", True)

        try:
            page = _session.page
            if clear:
                page.fill(selector, text)
            else:
                page.type(selector, text)

            return ToolResult(
                tool_name="browser_type",
                content=f"Typed text into: {selector}",
                success=True,
                metadata={"selector": selector},
            )
        except ImportError:
            return ToolResult(
                tool_name="browser_type",
                content=(
                    "playwright not installed. Install with: uv sync --extra browser"
                ),
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="browser_type",
                content=f"Type error: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Tool 4: BrowserScreenshotTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("browser_screenshot")
class BrowserScreenshotTool(BaseTool):
    """Take a screenshot of the current page."""

    tool_id = "browser_screenshot"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_screenshot",
            description=(
                "Take a screenshot of the current browser page."
                " Returns the screenshot as base64-encoded data."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Optional file path to save the screenshot.",
                    },
                    "full_page": {
                        "type": "boolean",
                        "description": (
                            "If true, capture the full scrollable page. Default: false."
                        ),
                    },
                },
            },
            category="browser",
        )

    def execute(self, **params: Any) -> ToolResult:
        path = params.get("path")
        full_page = params.get("full_page", False)

        try:
            page = _session.page
            screenshot_bytes = page.screenshot(full_page=full_page)

            if path:
                with open(path, "wb") as f:
                    f.write(screenshot_bytes)

            b64_data = base64.b64encode(screenshot_bytes).decode("utf-8")

            description = "Screenshot taken"
            if full_page:
                description += " (full page)"
            if path:
                description += f", saved to {path}"

            return ToolResult(
                tool_name="browser_screenshot",
                content=description,
                success=True,
                metadata={"screenshot_base64": b64_data},
            )
        except ImportError:
            return ToolResult(
                tool_name="browser_screenshot",
                content=(
                    "playwright not installed. Install with: uv sync --extra browser"
                ),
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="browser_screenshot",
                content=f"Screenshot error: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Tool 5: BrowserExtractTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("browser_extract")
class BrowserExtractTool(BaseTool):
    """Extract content from the current page."""

    tool_id = "browser_extract"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_extract",
            description=(
                "Extract content from the current browser page."
                " Supports extracting text, links, or tables."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS selector to extract from. Default: 'body'."
                        ),
                    },
                    "extract_type": {
                        "type": "string",
                        "description": (
                            "Type of extraction: 'text', 'links',"
                            " or 'tables'. Default: 'text'."
                        ),
                    },
                },
            },
            category="browser",
        )

    def execute(self, **params: Any) -> ToolResult:
        selector = params.get("selector", "body")
        extract_type = params.get("extract_type", "text")

        if extract_type not in ("text", "links", "tables"):
            return ToolResult(
                tool_name="browser_extract",
                content=(
                    f"Invalid extract_type: '{extract_type}'."
                    " Must be 'text', 'links', or 'tables'."
                ),
                success=False,
            )

        try:
            page = _session.page

            if extract_type == "text":
                content = page.inner_text(selector)
                if len(content) > 10000:
                    content = content[:10000] + "\n\n[Content truncated]"
                return ToolResult(
                    tool_name="browser_extract",
                    content=content,
                    success=True,
                    metadata={"selector": selector, "extract_type": extract_type},
                )

            elif extract_type == "links":
                links = page.eval_on_selector_all(
                    f"{selector} a[href]",
                    """elements => elements.map(el => ({
                        href: el.href,
                        text: el.innerText.trim()
                    }))""",
                )
                lines = []
                for link in links:
                    text = link.get("text", "")
                    href = link.get("href", "")
                    lines.append(f"- [{text}]({href})")
                content = "\n".join(lines) if lines else "No links found."
                if len(content) > 10000:
                    content = content[:10000] + "\n\n[Content truncated]"
                return ToolResult(
                    tool_name="browser_extract",
                    content=content,
                    success=True,
                    metadata={
                        "selector": selector,
                        "extract_type": extract_type,
                        "num_links": len(links),
                    },
                )

            else:  # tables
                tables_text = page.eval_on_selector_all(
                    f"{selector} table",
                    """elements => elements.map(el => el.innerText)""",
                )
                if tables_text:
                    content = "\n\n---\n\n".join(tables_text)
                else:
                    content = "No tables found."
                if len(content) > 10000:
                    content = content[:10000] + "\n\n[Content truncated]"
                return ToolResult(
                    tool_name="browser_extract",
                    content=content,
                    success=True,
                    metadata={
                        "selector": selector,
                        "extract_type": extract_type,
                        "num_tables": len(tables_text),
                    },
                )

        except ImportError:
            return ToolResult(
                tool_name="browser_extract",
                content=(
                    "playwright not installed. Install with: uv sync --extra browser"
                ),
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="browser_extract",
                content=f"Extract error: {exc}",
                success=False,
            )


__all__ = [
    "BrowserNavigateTool",
    "BrowserClickTool",
    "BrowserTypeTool",
    "BrowserScreenshotTool",
    "BrowserExtractTool",
]
