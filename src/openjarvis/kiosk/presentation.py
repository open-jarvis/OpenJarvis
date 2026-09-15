"""Customer-display sessions backed by the already-live Playwright MCP client."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Iterable, Iterator
from urllib.parse import quote, urlsplit
from uuid import uuid4

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolResult

logger = logging.getLogger(__name__)


class PresentationUnavailableError(RuntimeError):
    """Raised when the customer display cannot be backed by Playwright."""


_PRESENTATION_GENERATION: ContextVar[str | None] = ContextVar(
    "openjarvis_presentation_generation", default=None
)


@contextmanager
def presentation_generation(generation: str | None) -> Iterator[None]:
    """Correlate display publications made by one native Voice session."""
    token = _PRESENTATION_GENERATION.set(generation)
    try:
        yield
    finally:
        _PRESENTATION_GENERATION.reset(token)


@dataclass(slots=True)
class PresentationSession:
    """State isolated to one customer-display browser page."""

    session_id: str
    display_url: str
    display_tab_index: int
    last_payload: dict[str, Any] = field(default_factory=lambda: {"view": "none"})
    display_connected: bool = True
    initial_display_started: bool = False


def find_playwright_client(clients: Iterable[Any]) -> Any | None:
    """Return the configured MCP client for the Playwright server, if present."""
    return next(
        (
            client
            for client in clients
            if getattr(client, "_server_name", None) == "playwright"
        ),
        None,
    )


class PresentationSessionManager:
    """Own the primary customer-display tab and its automation companion."""

    def __init__(self, bus: EventBus, client: Any | None) -> None:
        self._bus = bus
        self._client = find_playwright_client([client]) if client is not None else None
        self._lock = RLock()
        self._session: PresentationSession | None = None
        self._active_generation: str | None = None
        self._initial_display: Callable[[], ToolResult] | None = None

    def configure_initial_display(self, loader: Callable[[], ToolResult]) -> None:
        """Configure the recipe-backed display load for a newly opened tab."""
        with self._lock:
            self._initial_display = loader

    def preload_initial_display(self) -> bool:
        """Run the configured display recipe once without racing a Voice turn."""
        with self._lock:
            session = self._session
            loader = self._initial_display
            if (
                session is None
                or loader is None
                or session.initial_display_started
                or self._active_generation is not None
            ):
                return False
            session.initial_display_started = True
            generation = f"initial-display-{session.session_id}"
            self._active_generation = generation

        try:
            with presentation_generation(generation):
                result = loader()
            if not result.success:
                logger.warning("Initial display recipe failed.")
            return result.success
        except Exception:
            logger.exception("Initial display recipe raised.")
            return False

    def load_initial_display(self) -> bool:
        """Run the configured display recipe for an active kiosk session."""
        with self._lock:
            if self._session is None or self._initial_display is None:
                return False
            loader = self._initial_display

        try:
            result = loader()
            if not result.success:
                logger.warning("Initial display recipe failed.")
            return result.success
        except Exception:
            logger.exception("Initial display recipe raised.")
            return False

    def ensure(self, display_origin: str) -> PresentationSession:
        """Create one display tab, returning the existing session on later calls."""
        origin = _normalize_display_origin(display_origin)
        with self._lock:
            if self._session is not None:
                self.recover_display_tab()
                return self._session
            display_tab_index = _selected_tab_index(
                self._call_tool("browser_tabs", {"action": "list"})
            )
            session_id = uuid4().hex
            session = PresentationSession(
                session_id=session_id,
                display_url=f"{origin}/customer-display?session={session_id}",
                display_tab_index=display_tab_index,
            )
            try:
                self._call_tool("browser_navigate", {"url": session.display_url})
                self._focus_display_tab(session.display_tab_index)
            except PresentationUnavailableError:
                self._restore_tab(display_tab_index)
                raise
            self._session = session
            return session

    def publish(self, payload: dict[str, Any]) -> ToolResult:
        """Publish a display event scoped to the active customer session."""
        from openjarvis.agents._stubs import check_agent_cancelled

        with self._lock:
            check_agent_cancelled()
            if self._session is None or self._client is None:
                return ToolResult(
                    tool_name="presentation",
                    content="presentation_unavailable",
                    success=False,
                )
            publication_generation = _PRESENTATION_GENERATION.get()
            if (
                publication_generation is not None
                and publication_generation != self._active_generation
            ):
                return ToolResult(
                    tool_name="presentation",
                    content="presentation_stale_generation",
                    success=False,
                )
            if not self._session.display_connected:
                self.recover_display_tab()
            check_agent_cancelled()
            normalized = deepcopy(payload)
            normalized["presentation_session_id"] = self._session.session_id
            self._session.last_payload = normalized
            self._bus.publish(EventType.DISPLAY_UPDATE, normalized)
            return ToolResult(
                tool_name="presentation", content="presentation_published"
            )

    def activate(self, generation: str) -> bool:
        """Make one native Voice session authoritative for publications."""
        with self._lock:
            self._active_generation = generation
            if self._session is not None:
                try:
                    self._focus_display_tab(self._session.display_tab_index)
                except PresentationUnavailableError:
                    pass
            return True

    def active_generation(self, session_id: str) -> str | None:
        """Return the active publication generation for one display session."""
        with self._lock:
            if self._session is None or self._session.session_id != session_id:
                return None
            return self._active_generation

    def reset(self, session_id: str, *, generation: str | None = None) -> bool:
        """Replace only the active session's display state with the blank view."""
        with self._lock:
            if self._session is None or self._session.session_id != session_id:
                return False
            if generation is not None and self._active_generation != generation:
                return False
            self._active_generation = None
            self._session.last_payload = {
                "view": "none",
                "presentation_session_id": self._session.session_id,
            }
            self._bus.publish(EventType.DISPLAY_UPDATE, self._session.last_payload)
            return True

    def replay(self, session_id: str) -> dict[str, Any] | None:
        """Return the active session's most recent display event for reconnects."""
        with self._lock:
            if self._session is None or self._session.session_id != session_id:
                return None
            payload = deepcopy(self._session.last_payload)
            payload["presentation_session_id"] = self._session.session_id
            return payload

    def mark_display_connected(self, session_id: str) -> bool:
        """Record that the customer-display WebSocket is connected."""
        with self._lock:
            if self._session is None or self._session.session_id != session_id:
                return False
            self._session.display_connected = True
            return True

    def mark_display_disconnected(self, session_id: str) -> bool:
        """Record a display disconnect without discarding its replayable state."""
        with self._lock:
            if self._session is None or self._session.session_id != session_id:
                return False
            self._session.display_connected = False
            return True

    def recover_display_tab(self) -> bool:
        """Recreate and foreground a missing customer-display page."""
        with self._lock:
            session = self._session
            if session is None:
                return False
            previous_tab_index = session.display_tab_index
            try:
                tab_result = self._call_tool("browser_tabs", {"action": "list"})
                tab_list = _tool_text(tab_result)
                previous_tab_index = _selected_tab_index(tab_result)
                encoded_url = quote(session.display_url, safe=":/?=&")
                if encoded_url in tab_list:
                    self._focus_display_tab(session.display_tab_index)
                    return False
                self._call_tool("browser_navigate", {"url": session.display_url})
                session.display_tab_index = previous_tab_index
                self._focus_display_tab(session.display_tab_index)
                return True
            except PresentationUnavailableError:
                self._restore_tab(previous_tab_index)
                raise

    def _require_client(self) -> Any:
        if self._client is None:
            raise PresentationUnavailableError("presentation_unavailable")
        return self._client

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call Playwright and normalize protocol and transport failures."""
        try:
            result = self._require_client().call_tool(name, arguments)
        except PresentationUnavailableError:
            raise
        except Exception as exc:
            raise PresentationUnavailableError(f"{name} unavailable") from exc
        if not isinstance(result, dict) or result.get("isError"):
            raise PresentationUnavailableError(f"{name} returned an MCP error")
        return result

    def _focus_display_tab(self, display_tab_index: int) -> None:
        self._call_tool(
            "browser_tabs", {"action": "select", "index": display_tab_index}
        )

    def _restore_tab(self, tab_index: int) -> None:
        """Best-effort rollback that must not replace the primary MCP failure."""
        try:
            self._focus_display_tab(tab_index)
        except PresentationUnavailableError:
            pass


def _normalize_display_origin(display_origin: str) -> str:
    parsed = urlsplit(display_origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("display_origin must be an http(s) origin without a path")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _selected_tab_index(result: dict[str, Any]) -> int:
    """Parse the selected tab index from the textual Playwright tab listing."""
    text = _tool_text(result)
    for line in text.splitlines():
        if "current" not in line.lower():
            continue
        stripped = line.lstrip("- ").lstrip()
        index, separator, _ = stripped.partition(":")
        if separator and index.isdigit():
            return int(index)
    return 0


def _tool_text(result: dict[str, Any]) -> str:
    """Keep the current MCP response-shape parsing at this boundary."""
    content = result.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        item["text"]
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    )


__all__ = [
    "PresentationSession",
    "PresentationSessionManager",
    "PresentationUnavailableError",
    "find_playwright_client",
    "presentation_generation",
]
