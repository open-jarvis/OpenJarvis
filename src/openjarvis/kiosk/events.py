"""Vision event types and EventHistory ring buffer for kiosk FSM."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class VisionEvent:
    """A single vision observation at one tick (200ms / 5 Hz).

    Attributes:
        kind: One of no_person, person_unknown, person_near.
        ts: Unix timestamp from the vision server.
        nearest_m: Distance in meters of the nearest person (0.0 when unknown/absent).
        track_id: Track ID of the nearest person (-1 when absent).
    """

    kind: Literal["no_person", "person_unknown", "person_near"]
    ts: float
    nearest_m: float
    track_id: int


@dataclass
class EventHistory:
    """Ring buffer holding the last N seconds of vision events.

    Provides pure query methods consumed by evaluate_state(). All
    time-window logic lives here — the evaluator asks questions,
    never computes raw durations from event timestamps.

    Attributes:
        max_age_seconds: Events older than this are pruned on push.
    """

    max_age_seconds: float = 60.0
    _events: list[VisionEvent] = field(default_factory=list, init=False)

    # -- mutation --------------------------------------------------

    def push(self, event: VisionEvent) -> None:
        """Append an event and prune events older than max_age_seconds."""
        self._events.append(event)
        self._prune(event.ts)

    def _prune(self, now: float) -> None:
        cutoff = now - self.max_age_seconds
        while self._events and self._events[0].ts < cutoff:
            self._events.pop(0)

    # -- queries ---------------------------------------------------

    def last_event(self) -> VisionEvent | None:
        """Return the most recent event, or None if empty."""
        return self._events[-1] if self._events else None

    def events_in_window(self, seconds: float, now: float) -> list[VisionEvent]:
        """Return all events within the last ``seconds`` from ``now``."""
        cutoff = now - seconds
        return [e for e in self._events if e.ts > cutoff]

    def consecutive_kind_duration(self, kind: str, now: float) -> float:
        """How long has ``kind`` been running consecutively up to ``now``?

        Walks backward from the most recent event. If the most recent
        event is not of ``kind``, returns 0.0. Otherwise returns the
        time span from the earliest consecutive event of ``kind`` to
        the latest.
        """
        if not self._events:
            return 0.0

        # Walk backward from the end
        run_start = None
        for e in reversed(self._events):
            if e.kind == kind:
                run_start = e.ts
            else:
                break

        if run_start is None:
            return 0.0

        latest = now
        return round(latest - run_start, 6)

    def last_event_ts(self, kind: str) -> float | None:
        """Return the timestamp of the most recent event of ``kind``, or None."""
        for e in reversed(self._events):
            if e.kind == kind:
                return e.ts
        return None

    def nearest_in_window(self, seconds: float, now: float) -> float:
        """Return the minimum nearest_m among person_near events in the window.

        Returns float('inf') if no person_near events exist in the window.
        Only considers person_near events (not person_unknown).
        """
        cutoff = now - seconds
        min_dist = float("inf")
        for e in self._events:
            if e.ts >= cutoff and e.kind == "person_near":
                if e.nearest_m < min_dist:
                    min_dist = e.nearest_m
        return min_dist
