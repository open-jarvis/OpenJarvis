"""Bridge between the internal event bus and the analytics client.

The internal bus (:mod:`openjarvis.core.events`) carries dozens of
event types — most are too granular or too internal to ship as
analytics. The bridge:

  - Subscribes to a focused subset of EventTypes.
  - Aggregates high-frequency events (INFERENCE_END, TOOL_CALL_END)
    via :class:`SessionAggregator` so we only ship one event per chat
    session, not one per inference.
  - Forwards user-meaningful low-frequency events directly
    (FEEDBACK_RECEIVED, SECURITY_ALERT).
  - Tracks first-uses in-process so ``tool_first_used`` fires once per
    (anon_id, tool) per process. (First-use *across* processes is
    not promised — that would require disk state and isn't worth the
    complexity for v1.)
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from openjarvis.analytics.aggregator import SessionAggregator
from openjarvis.analytics.redaction import hash_id
from openjarvis.core.events import Event, EventType

if TYPE_CHECKING:
    from openjarvis.analytics.client import AnalyticsClient
    from openjarvis.core.events import EventBus

logger = logging.getLogger(__name__)

# Allowlist of known engines — anything else gets normalised to "unknown"
# so we don't leak custom engine names through the engine property.
_KNOWN_ENGINES = frozenset(
    {
        "ollama",
        "vllm",
        "mlx",
        "llama_cpp",
        "openai",
        "anthropic",
        "google",
    }
)

# Default session id used when an internal event doesn't carry one.
_DEFAULT_SESSION = "default"


class EventBridge:
    """Subscribes to the internal bus and routes to the analytics client."""

    def __init__(
        self,
        bus: "EventBus",
        client: "AnalyticsClient",
        aggregator: SessionAggregator | None = None,
    ) -> None:
        self.bus = bus
        self.client = client
        self.aggregator = aggregator or SessionAggregator(client)
        self._first_tool_uses: set[str] = set()
        self._first_chat_emitted = False
        self._lock = threading.Lock()
        self._subscribed = False

    def start(self) -> None:
        """Attach subscribers to the bus. Idempotent."""
        if self._subscribed:
            return
        self.bus.subscribe(EventType.INFERENCE_END, self._on_inference_end)
        self.bus.subscribe(EventType.TOOL_CALL_END, self._on_tool_end)
        self.bus.subscribe(EventType.SESSION_END, self._on_session_end)
        self.bus.subscribe(EventType.AGENT_TURN_END, self._on_agent_turn_end)
        self.bus.subscribe(EventType.FEEDBACK_RECEIVED, self._on_feedback)
        self.bus.subscribe(EventType.SECURITY_ALERT, self._on_security_alert)
        self._subscribed = True
        logger.debug("Analytics bridge subscribed to internal event bus")

    def stop(self) -> None:
        """Detach subscribers and flush buffered sessions."""
        if self._subscribed:
            try:
                self.bus.unsubscribe(EventType.INFERENCE_END, self._on_inference_end)
                self.bus.unsubscribe(EventType.TOOL_CALL_END, self._on_tool_end)
                self.bus.unsubscribe(EventType.SESSION_END, self._on_session_end)
                self.bus.unsubscribe(EventType.AGENT_TURN_END, self._on_agent_turn_end)
                self.bus.unsubscribe(EventType.FEEDBACK_RECEIVED, self._on_feedback)
                self.bus.unsubscribe(EventType.SECURITY_ALERT, self._on_security_alert)
            except Exception as exc:
                logger.debug("Analytics bridge unsubscribe error: %s", exc)
            self._subscribed = False
        self.aggregator.shutdown()

    # -- handlers --------------------------------------------------------

    def _session_id(self, data: dict) -> str:
        sid = data.get("session_id") or data.get("session") or data.get("trace_id")
        return str(sid) if sid else _DEFAULT_SESSION

    def _normalise_engine(self, raw: object) -> str:
        if not isinstance(raw, str):
            return ""
        e = raw.lower()
        return e if e in _KNOWN_ENGINES else "unknown"

    def _on_inference_end(self, event: Event) -> None:
        try:
            data = event.data or {}
            self.aggregator.record_inference(
                session_id=self._session_id(data),
                tokens_in=int(
                    data.get("input_tokens") or data.get("prompt_tokens") or 0
                ),
                tokens_out=int(
                    data.get("output_tokens") or data.get("completion_tokens") or 0
                ),
                latency_ms=float(
                    data.get("latency_ms")
                    or (data.get("latency_seconds", 0) or 0) * 1000.0
                ),
                model_hash=hash_id(str(data.get("model", ""))),
                engine=self._normalise_engine(data.get("engine")),
            )

            # One-shot first_chat_sent per process lifetime.
            # Note: we don't set "platform" here — the backend can't reliably
            # tell whether the call came from CLI, desktop, or web. The
            # frontend owns platform-aware events; this one is just the
            # activation marker.
            with self._lock:
                if not self._first_chat_emitted:
                    self._first_chat_emitted = True
                    self.client.capture("first_chat_sent", {})
        except Exception as exc:
            logger.debug("Bridge _on_inference_end error: %s", exc)

    def _on_tool_end(self, event: Event) -> None:
        try:
            data = event.data or {}
            session_id = self._session_id(data)
            tool_name_raw = str(data.get("tool_name") or data.get("tool") or "")
            self.aggregator.record_tool(session_id, tool_name=hash_id(tool_name_raw))

            # First-use per (process, tool). Use the raw name's hash to
            # de-duplicate without leaking the literal name.
            tool_key = hash_id(tool_name_raw)
            with self._lock:
                first = tool_key and tool_key not in self._first_tool_uses
                if first:
                    self._first_tool_uses.add(tool_key)
            if first:
                # tool_name property must be in the analytics allowlist;
                # if the raw name isn't recognised, we send "custom_tool".
                from openjarvis.analytics.events import KNOWN_TOOL_NAMES

                shipped_name = (
                    tool_name_raw
                    if tool_name_raw in KNOWN_TOOL_NAMES
                    else "custom_tool"
                )
                self.client.capture("tool_first_used", {"tool_name": shipped_name})
        except Exception as exc:
            logger.debug("Bridge _on_tool_end error: %s", exc)

    def _on_session_end(self, event: Event) -> None:
        try:
            data = event.data or {}
            self.aggregator.end_session(self._session_id(data))
        except Exception as exc:
            logger.debug("Bridge _on_session_end error: %s", exc)

    def _on_agent_turn_end(self, event: Event) -> None:
        # AGENT_TURN_END can mark the end of a logical chat exchange.
        # If there's no explicit SESSION_END, treat this as an idle hint
        # rather than a hard close — the aggregator will flush on idle
        # if no more events arrive.
        try:
            data = event.data or {}
            if data.get("error"):
                self.aggregator.record_error(self._session_id(data))
        except Exception as exc:
            logger.debug("Bridge _on_agent_turn_end error: %s", exc)

    def _on_feedback(self, event: Event) -> None:
        try:
            data = event.data or {}
            rating = data.get("rating")
            has_comment = bool(data.get("comment") or data.get("text"))
            self.client.capture(
                "feedback_submitted",
                {
                    "rating": int(rating) if isinstance(rating, (int, float)) else 0,
                    "has_comment": has_comment,
                },
            )
        except Exception as exc:
            logger.debug("Bridge _on_feedback error: %s", exc)

    def _on_security_alert(self, event: Event) -> None:
        try:
            data = event.data or {}
            self.client.capture(
                "error_shown_to_user",
                {
                    "error_class": "permission_denied",
                    "platform": str(data.get("platform", "cli")),
                },
            )
        except Exception as exc:
            logger.debug("Bridge _on_security_alert error: %s", exc)


__all__ = ["EventBridge"]
