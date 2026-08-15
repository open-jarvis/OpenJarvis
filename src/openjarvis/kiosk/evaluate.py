"""Pure evaluate_state() — derives next kiosk state from event history.

No I/O. No mutable state. No timers. Fully deterministic.
Every handler is a standalone pure function.
"""

from __future__ import annotations

from typing import Literal

from openjarvis.kiosk.config import KioskConfig
from openjarvis.kiosk.events import EventHistory
from openjarvis.kiosk.effects import SideEffect

# -- Types ------------------------------------------------------------

KioskState = Literal["idle", "approaching", "prompting", "active", "cleanup"]
UserResponse = Literal["accept", "decline"]

# -- Config (defaults, overridable) -----------------------------------

_CFG = KioskConfig()


def set_config(cfg: KioskConfig) -> None:
    """Override default config (for tests or env-based setup)."""
    global _CFG
    _CFG = cfg


# -- Main entry point -------------------------------------------------


def evaluate_state(
    history: EventHistory,
    now: float,
    current_state: KioskState,
    user_response: UserResponse | None,
    session_start: float | None,
    prompting_started_at: float | None,
    last_decline_at: float | None = None,
) -> tuple[KioskState, list[SideEffect]]:
    """Pure function: event history + inputs -> next state + effects.

    Args:
        history: Ring buffer of recent vision events.
        now: Current unix timestamp.
        current_state: The current kiosk state.
        user_response: One-shot "accept" or "decline" (consumed only in PROMPTING).
        session_start: When the current ACTIVE session began (None if not in session).
        prompting_started_at: When PROMPTING began (for 30s auto-dismiss).
        last_decline_at: When the last "decline" was recorded (for cooldown).

    Returns:
        (next_state, list_of_side_effects)
    """
    handler = _HANDLERS.get(current_state)
    if handler is None:
        return (current_state, [])
    return handler(history, now, user_response, session_start,
                   prompting_started_at, last_decline_at)


# -- Handler registry -------------------------------------------------


def _evaluate_idle(
    history, now, user_response, session_start, prompting_started_at,
    last_decline_at,
) -> tuple[KioskState, list[SideEffect]]:
    # Decline cooldown: ignore the person until the cooldown expires.
    if (_cooldown_active(last_decline_at, now)):
        return ("idle", [])

    last = history.last_event()
    if last is None or last.kind != "person_near":
        return ("idle", [])
    if last.nearest_m >= _CFG.approach_threshold_m:
        return ("idle", [])

    sustained = history.consecutive_kind_duration("person_near", now)
    if sustained < _CFG.approach_entry_debounce:
        return ("idle", [])

    return ("approaching", [_publish_state("approaching")])


def _evaluate_approaching(
    history, now, user_response, session_start, prompting_started_at,
    last_decline_at,
) -> tuple[KioskState, list[SideEffect]]:
    # Decline cooldown: don't progress to prompting; return to idle.
    if (_cooldown_active(last_decline_at, now)):
        return ("idle", [])

    last = history.last_event()

    # Check if person is absent (no_person, far >1m, or depth unknown)
    is_absent = (
        last is None
        or last.kind == "no_person"
        or last.kind == "person_unknown"
        or (last.kind == "person_near" and last.nearest_m >= _CFG.approach_threshold_m)
    )
    if is_absent:
        absent = _consecutive_absent_duration(history, now)
        if absent >= _CFG.approach_sustain_seconds:
            return ("idle", [_publish_state("idle")])
        return ("approaching", [])

    # Person is in zone: person_near with valid distance
    if last.kind == "person_near" and last.nearest_m < _CFG.approach_threshold_m:
        sustained = history.consecutive_kind_duration("person_near", now)
        if sustained >= _CFG.approach_sustain_seconds:
            return ("prompting", [_publish_state("prompting")])
        return ("approaching", [])

    return ("approaching", [])


def _evaluate_prompting(
    history, now, user_response, session_start, prompting_started_at,
    last_decline_at,
) -> tuple[KioskState, list[SideEffect]]:
    # User response takes priority
    if user_response == "accept":
        return ("active", [
            _publish_state("active", mic_enabled=False),
            SideEffect("tts_greeting"),
            _publish_state("active", mic_enabled=True),
        ])
    if user_response == "decline":
        return ("idle", [_publish_state("idle")])

    # Auto-dismiss after popup timeout
    if prompting_started_at is not None:
        if now - prompting_started_at >= _CFG.popup_timeout:
            return ("idle", [_publish_state("idle")])

    # Person absent: no_person, far away (>1m), or depth lost
    last = history.last_event()
    is_absent = (
        last is None
        or last.kind == "no_person"
        or last.kind == "person_unknown"
        or (last.kind == "person_near" and last.nearest_m >= _CFG.approach_threshold_m)
    )
    if is_absent:
        absent = _consecutive_absent_duration(history, now)
        if absent >= _CFG.leave_sustain_seconds_prompting:
            return ("idle", [_publish_state("idle")])

    return ("prompting", [])


def _consecutive_absent_duration(history: EventHistory, now: float) -> float:
    """How long has the person been absent (no_person, far, or unknown)?"""
    events = history.events_in_window(60.0, now)
    if not events:
        return 0.0
    # Walk backward: find the most recent "present" event
    last_present_ts = None
    for e in reversed(events):
        if e.kind == "person_near" and e.nearest_m < _CFG.approach_threshold_m:
            last_present_ts = e.ts
            break
    if last_present_ts is None:
        # Never been present in the window
        return now - events[0].ts if events else 0.0
    return now - last_present_ts


def _evaluate_active(
    history, now, user_response, session_start, prompting_started_at,
    last_decline_at,
) -> tuple[KioskState, list[SideEffect]]:
    effects: list[SideEffect] = []

    if session_start is not None:
        elapsed = now - session_start

        # Hard timeout
        if elapsed >= _CFG.session_max_seconds:
            return ("cleanup", [
                _publish_state("cleanup"),
                SideEffect("tts_goodbye"),
            ])

        # One-time warning
        if elapsed >= _CFG.session_warning_seconds:
            effects.append(SideEffect("tts_warning"))

    # Leave detection: absent = no_person, far (>1m), or depth unknown
    last = history.last_event()
    is_absent = (
        last is None
        or last.kind == "no_person"
        or last.kind == "person_unknown"
        or (last.kind == "person_near" and last.nearest_m >= _CFG.approach_threshold_m)
    )
    if is_absent:
        absent = _consecutive_absent_duration(history, now)
        if absent >= _CFG.leave_sustain_seconds_active:
            return ("cleanup", [
                _publish_state("cleanup"),
                SideEffect("tts_goodbye"),
            ])

    return ("active", effects)


def _evaluate_cleanup(
    history, now, user_response, session_start, prompting_started_at,
    last_decline_at,
) -> tuple[KioskState, list[SideEffect]]:
    # Automatic: cleanup → idle
    return ("idle", [_publish_state("idle")])


def _publish_state(state: KioskState, *, mic_enabled: bool = False) -> SideEffect:
    """Publish state with an explicit fail-closed microphone policy."""
    return SideEffect("publish_state", {"state": state, "mic_enabled": mic_enabled})


def _cooldown_active(last_decline_at: float | None, now: float) -> bool:
    """True when decline cooldown is still in effect."""
    if last_decline_at is None:
        return False
    return (now - last_decline_at) < _CFG.decline_cooldown_seconds


_HANDLERS = {
    "idle": _evaluate_idle,
    "approaching": _evaluate_approaching,
    "prompting": _evaluate_prompting,
    "active": _evaluate_active,
    "cleanup": _evaluate_cleanup,
}
