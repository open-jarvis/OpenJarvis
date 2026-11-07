"""Event recording system for agent execution telemetry."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class EventType(str, Enum):
    """Supported event types for agent telemetry."""

    LM_INFERENCE_START = "lm_inference_start"
    LM_INFERENCE_END = "lm_inference_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    PREFILL_START = "prefill_start"
    PREFILL_END = "prefill_end"
    DECODE_START = "decode_start"
    DECODE_END = "decode_end"
    # Submodel call events (for MCP tools that call inference servers)
    SUBMODEL_CALL_START = "submodel_call_start"
    SUBMODEL_CALL_END = "submodel_call_end"


@dataclass
class AgentEvent:
    """Single event recorded during agent execution."""

    event_type: str
    timestamp: float  # Unix timestamp from time.time()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"AgentEvent({self.event_type!r}, "
            f"ts={self.timestamp:.3f}, meta={self.metadata})"
        )


class EventRecorder:
    """Thread-safe recorder for agent execution events.

    Records events with timestamps for later correlation with energy telemetry.
    All operations are thread-safe for use in concurrent agent execution.

    Example:
        >>> recorder = EventRecorder()
        >>> recorder.record('tool_call_start', tool='calculator')
        >>> recorder.record('tool_call_end', tool='calculator')
        >>> events = recorder.get_events()
        >>> len(events)
        2
    """

    def __init__(self) -> None:
        """Initialize the event recorder."""
        self._events: List[AgentEvent] = []
        self._lock = threading.Lock()

    def record(self, event_type: str, **metadata: Any) -> None:
        """Record an event with current timestamp.

        Args:
            event_type: Type of event (e.g., 'tool_call_start', 'lm_inference_end')
            **metadata: Additional metadata to attach to the event
        """
        event = AgentEvent(
            event_type=event_type,
            timestamp=time.time(),
            metadata=metadata,
        )
        with self._lock:
            self._events.append(event)

    def get_events(self) -> List[AgentEvent]:
        """Return a copy of all recorded events.

        Returns:
            List of all recorded events in chronological order.
        """
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """Clear all recorded events."""
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        """Return the number of recorded events."""
        with self._lock:
            return len(self._events)


__all__ = ["AgentEvent", "EventRecorder", "EventType"]
