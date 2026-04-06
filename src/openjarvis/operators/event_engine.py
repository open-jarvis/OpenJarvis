"""EventTriggerEngine -- orchestrates event-source watchers for one operator.

Usage::

    engine = EventTriggerEngine(
        operator_id="inbox-monitor",
        bus=bus,
        tick_callback=lambda oid, prompt: system.ask(prompt, operator_id=oid),
    )
    engine.start(manifest.event_triggers)   # list of trigger config dicts
    ...
    engine.stop()
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from openjarvis.operators.watchers import (
    BaseWatcher,
    BusEventWatcher,
    FileWatcher,
    HttpPollWatcher,
    SystemMetricWatcher,
)

logger = logging.getLogger(__name__)

# Signature: (operator_id: str, prompt: str) -> None
TickCallback = Callable[[str, str], None]

# Prompt template injected when an event fires
_EVENT_PROMPT_TEMPLATE = (
    "[EVENT TRIGGER] {description}\n\n"
    "Event context:\n{context}\n\n"
    "[OPERATOR TICK] Respond to this event according to your operational protocol."
)


class EventTriggerEngine:
    """Manages a set of watchers for a single operator.

    When any watcher fires, the engine:
    1. Publishes ``OPERATOR_EVENT_FIRED`` on the EventBus.
    2. Calls ``tick_callback(operator_id, enriched_prompt)`` so the operator
       agent runs with event context injected into its prompt.

    Parameters
    ----------
    operator_id:
        The ID of the operator this engine serves.
    bus:
        ``EventBus`` instance for publishing operator events.
    tick_callback:
        Callable invoked when an event fires.  Receives the operator ID and
        the event-enriched prompt string.
    """

    def __init__(
        self,
        operator_id: str,
        bus: Any,
        tick_callback: TickCallback,
    ) -> None:
        self._operator_id = operator_id
        self._bus = bus
        self._tick_callback = tick_callback
        self._watchers: List[BaseWatcher] = []
        self._active = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active

    def start(self, triggers: List[Dict[str, Any]]) -> None:
        """Build and start all watchers for the given trigger configurations."""
        if not triggers:
            logger.debug("Operator %s has no event triggers.", self._operator_id)
            return

        for cfg in triggers:
            watcher = self._build_watcher(cfg)
            if watcher is None:
                continue
            with self._lock:
                self._watchers.append(watcher)
            try:
                watcher.start()
            except Exception:
                logger.exception(
                    "Failed to start watcher (type=%s) for operator %s",
                    cfg.get("type"),
                    self._operator_id,
                )

        self._active = True
        logger.info(
            "EventTriggerEngine started for operator %s (%d watchers)",
            self._operator_id,
            len(self._watchers),
        )

    def stop(self) -> None:
        """Stop all watchers and clean up."""
        with self._lock:
            watchers = list(self._watchers)
            self._watchers.clear()

        for w in watchers:
            try:
                w.stop()
            except Exception:
                logger.exception(
                    "Error stopping watcher for operator %s", self._operator_id
                )

        self._active = False
        logger.info("EventTriggerEngine stopped for operator %s", self._operator_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_watcher(self, cfg: Dict[str, Any]) -> Optional[BaseWatcher]:
        """Instantiate the correct watcher class for a trigger config dict."""
        trigger_type = cfg.get("type", "").lower()

        callback = self._make_callback()

        if trigger_type == "file":
            return FileWatcher(cfg, callback)
        if trigger_type == "system_metric":
            return SystemMetricWatcher(cfg, callback)
        if trigger_type == "http_poll":
            return HttpPollWatcher(cfg, callback)
        if trigger_type == "bus_event":
            return BusEventWatcher(cfg, callback, self._bus)

        logger.warning(
            "Unknown trigger type '%s' for operator %s — skipping.",
            trigger_type,
            self._operator_id,
        )
        return None

    def _make_callback(self) -> Callable[[str, Dict[str, Any]], None]:
        """Return a closure that captures self and fires the operator tick."""
        def _on_event(description: str, data: Dict[str, Any]) -> None:
            self._on_event_fired(description, data)
        return _on_event

    def _on_event_fired(self, description: str, data: Dict[str, Any]) -> None:
        """Called by any watcher when it detects an event."""
        from openjarvis.core.events import EventType

        # 1. Publish to EventBus so other subscribers can observe
        try:
            self._bus.publish(
                EventType.OPERATOR_EVENT_FIRED,
                {
                    "operator_id": self._operator_id,
                    "trigger": description,
                    "data": data,
                },
            )
        except Exception:
            logger.exception("Failed to publish OPERATOR_EVENT_FIRED")

        # 2. Build enriched prompt and invoke the tick callback
        context_str = "\n".join(f"  {k}: {v}" for k, v in data.items())
        prompt = _EVENT_PROMPT_TEMPLATE.format(
            description=description,
            context=context_str or "(no additional context)",
        )

        logger.info(
            "Operator %s event fired: %s", self._operator_id, description
        )

        try:
            self._tick_callback(self._operator_id, prompt)
        except Exception:
            logger.exception(
                "tick_callback raised an exception for operator %s", self._operator_id
            )


__all__ = ["EventTriggerEngine"]
