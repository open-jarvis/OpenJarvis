"""Thread-safe pub/sub event bus for inter-pillar telemetry.

Extends IPW's ``EventRecorder`` into a full publish/subscribe system so that
any pillar can emit events (e.g. ``INFERENCE_END``) and any other pillar can
react without direct coupling.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional  # noqa: I001

# ---------------------------------------------------------------------------
# Event taxonomy
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """Supported event categories."""

    INFERENCE_START = "inference_start"
    INFERENCE_END = "inference_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    MEMORY_STORE = "memory_store"
    MEMORY_RETRIEVE = "memory_retrieve"
    AGENT_TURN_START = "agent_turn_start"
    AGENT_TURN_END = "agent_turn_end"
    TELEMETRY_RECORD = "telemetry_record"
    TRACE_STEP = "trace_step"
    TRACE_COMPLETE = "trace_complete"
    CHANNEL_MESSAGE_RECEIVED = "channel_message_received"
    CHANNEL_MESSAGE_SENT = "channel_message_sent"
    SECURITY_SCAN = "security_scan"
    SECURITY_ALERT = "security_alert"
    SECURITY_BLOCK = "security_block"
    SCHEDULER_TASK_START = "scheduler_task_start"
    SCHEDULER_TASK_END = "scheduler_task_end"
    BATCH_START = "batch_start"
    BATCH_END = "batch_end"
    # Phase 14 — Agent Hardening & Security
    TOOL_TIMEOUT = "tool_timeout"
    LOOP_GUARD_TRIGGERED = "loop_guard_triggered"
    CAPABILITY_DENIED = "capability_denied"
    TAINT_VIOLATION = "taint_violation"
    # Phase 15 — Workflow, Skills, Sessions
    WORKFLOW_START = "workflow_start"
    WORKFLOW_NODE_START = "workflow_node_start"
    WORKFLOW_NODE_END = "workflow_node_end"
    WORKFLOW_END = "workflow_end"
    SKILL_EXECUTE_START = "skill_execute_start"
    SKILL_EXECUTE_END = "skill_execute_end"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    # Phase 16 — A2A Protocol
    A2A_TASK_RECEIVED = "a2a_task_received"
    A2A_TASK_COMPLETED = "a2a_task_completed"
    # Phase 22 — Operators
    OPERATOR_TICK_START = "operator_tick_start"
    OPERATOR_TICK_END = "operator_tick_end"
    # Phase 25 — Configuration Optimization
    OPTIMIZE_RUN_START = "optimize_run_start"
    OPTIMIZE_TRIAL_START = "optimize_trial_start"
    OPTIMIZE_TRIAL_END = "optimize_trial_end"
    OPTIMIZE_RUN_END = "optimize_run_end"
    FEEDBACK_RECEIVED = "feedback_received"


@dataclass(slots=True)
class Event:
    """A single event published on the bus."""

    event_type: EventType
    timestamp: float
    data: Dict[str, Any] = field(default_factory=dict)


# Type alias for subscriber callbacks
Subscriber = Callable[[Event], None]


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class EventBus:
    """Thread-safe publish/subscribe event bus.

    Subscribers are called synchronously in registration order within the
    publishing thread.  An optional *record_history* flag retains all
    published events for later inspection (useful in tests/telemetry).
    """

    def __init__(self, *, record_history: bool = False) -> None:
        self._subscribers: Dict[EventType, List[Subscriber]] = {}
        self._lock = threading.Lock()
        self._record_history = record_history
        self._history: List[Event] = []

    # -- subscribe / unsubscribe --------------------------------------------

    def subscribe(self, event_type: EventType, callback: Subscriber) -> None:
        """Register *callback* to be called whenever *event_type* is published."""
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: EventType, callback: Subscriber) -> None:
        """Remove *callback* from listeners for *event_type*."""
        with self._lock:
            listeners = self._subscribers.get(event_type, [])
            try:
                listeners.remove(callback)
            except ValueError:
                pass

    # -- publish ------------------------------------------------------------

    def publish(
        self,
        event_type: EventType,
        data: Optional[Dict[str, Any]] = None,
    ) -> Event:
        """Create and dispatch an event to all subscribers.

        Returns the published ``Event`` instance.
        """
        event = Event(event_type=event_type, timestamp=time.time(), data=data or {})

        with self._lock:
            if self._record_history:
                self._history.append(event)
            listeners = list(self._subscribers.get(event_type, []))

        for callback in listeners:
            callback(event)

        return event

    # -- history ------------------------------------------------------------

    @property
    def history(self) -> List[Event]:
        """Return a copy of all recorded events (empty if recording is off)."""
        with self._lock:
            return list(self._history)

    def clear_history(self) -> None:
        """Discard all recorded events."""
        with self._lock:
            self._history.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bus: Optional[EventBus] = None
_bus_lock = threading.Lock()


def get_event_bus(*, record_history: bool = False) -> EventBus:
    """Return the module-level ``EventBus`` singleton, creating it if needed."""
    global _bus
    with _bus_lock:
        if _bus is None:
            _bus = EventBus(record_history=record_history)
        return _bus


def reset_event_bus() -> None:
    """Replace the singleton with a fresh instance (for tests)."""
    global _bus
    with _bus_lock:
        _bus = None


__all__ = [
    "Event",
    "EventBus",
    "EventType",
    "Subscriber",
    "get_event_bus",
    "reset_event_bus",
]
