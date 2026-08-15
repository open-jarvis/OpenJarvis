"""KioskRuntime and kiosk_main() — the single asyncio coroutine driving the FSM."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from openjarvis.kiosk.config import KioskConfig
from openjarvis.kiosk.events import EventHistory
from openjarvis.kiosk.evaluate import evaluate_state, KioskState, UserResponse
from openjarvis.kiosk.effects import KioskDependencies, run_side_effects

logger = logging.getLogger(__name__)


@dataclass
class KioskRuntime:
    """Mutable runtime state — only the main loop reads/writes this.

    All debounce/timer state is derived from EventHistory + timestamps.
    The only mutable fields here track when phases began and whether
    one-shot events (warnings) have fired.
    """

    history: EventHistory
    current_state: KioskState
    session_start: float | None
    prompting_started_at: float | None
    last_decline_at: float | None
    warning_sent: bool
    deps: KioskDependencies


async def kiosk_main(
    event_queue: asyncio.Queue,
    deps: KioskDependencies,
    *,
    config: KioskConfig | None = None,
) -> None:
    """Single coroutine — evaluates state at up to 5 Hz, runs effects.

    This is THE main loop. No other task mutates kiosk state. The
    user_response mechanism receives callbacks from the routes layer
    through an asyncio.Queue or callback set on the runtime.

    Args:
        event_queue: asyncio.Queue fed by VisionClient.
        deps: All I/O dependencies (bus and fixed-cue TTS).
        config: Optional KioskConfig override.
    """
    from openjarvis.kiosk.evaluate import set_config

    if config is not None:
        set_config(config)

    runtime = KioskRuntime(
        history=EventHistory(max_age_seconds=60.0),
        current_state="idle",
        session_start=None,
        prompting_started_at=None,
        last_decline_at=None,
        warning_sent=False,
        deps=deps,
    )

    # Channel for user responses from the routes layer
    response_queue: asyncio.Queue = asyncio.Queue(maxsize=8)

    # Expose so routes can push responses
    import openjarvis.kiosk.runtime as mod
    mod._current_response_queue = response_queue

    logger.warning("Kiosk main loop started — state=idle")

    user_response = None
    tick_count = 0

    while True:
        user_response = None  # fresh slate each tick
        tick_count += 1

        # Wait for next vision event OR user response (whichever first)
        try:
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(event_queue.get()),
                    asyncio.create_task(response_queue.get()),
                ],
                timeout=0.2,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel the loser
            for task in pending:
                task.cancel()

            for task in done:
                try:
                    result = task.result()
                    if isinstance(result, dict) and "event" in result:
                        # It's a vision event
                        runtime.history.push(_dict_to_vision_event(result))
                    elif result in ("accept", "decline"):
                        # It's a user response — store for this evaluation cycle
                        user_response = result
                except asyncio.CancelledError:
                    pass
        except asyncio.TimeoutError:
            pass  # No new events — still re-evaluate for time-based transitions

        now = time.time()
        new_state, effects = evaluate_state(
            runtime.history, now,
            runtime.current_state,
            user_response,
            runtime.session_start,
            runtime.prompting_started_at,
            runtime.last_decline_at,
        )
        # Record decline for cooldown (before we transition away from prompting).
        if runtime.current_state == "prompting" and user_response == "decline":
            runtime.last_decline_at = now

        # Track phase boundaries
        if new_state != runtime.current_state:
            logger.warning("%s -> %s", runtime.current_state, new_state)
            runtime.current_state = new_state
            _set_state(new_state)
            if new_state == "active":
                runtime.session_start = now
                runtime.warning_sent = False
                runtime.prompting_started_at = None
                runtime.last_decline_at = None
            elif new_state == "prompting":
                runtime.prompting_started_at = now
            elif new_state == "cleanup":
                runtime.session_start = None
                runtime.warning_sent = False
            elif new_state == "idle":
                runtime.session_start = None
                runtime.prompting_started_at = None

            # Re-evaluate: if we just transitioned TO prompting with a pending
            # user_response, handle it immediately (closes the 200ms race window
            # where a response arrives on the same tick as approaching->prompting)
            if new_state == "prompting" and user_response is not None:
                new_state, effects = evaluate_state(
                    runtime.history, now,
                    runtime.current_state,
                    user_response,
                    runtime.session_start,
                    runtime.prompting_started_at,
                    runtime.last_decline_at,
                )

        # Deduplicate tts_warning: fire only once per session
        if runtime.warning_sent:
            effects = [fx for fx in effects if fx.kind != "tts_warning"]
        elif any(fx.kind == "tts_warning" for fx in effects):
            runtime.warning_sent = True

        await run_side_effects(effects, runtime.deps)

        if tick_count % 50 == 0:
            last = runtime.history.last_event()
            evt_info = f"{last.kind}" if last else "none"
            if last and last.kind == "person_near":
                evt_info += f"@{last.nearest_m:.2f}m"
            logger.warning("kiosk tick=%d state=%s last_event=%s", tick_count, runtime.current_state, evt_info)


# Module-level references for routes
_current_response_queue: asyncio.Queue | None = None
_current_state: KioskState = "idle"


def _set_state(state: KioskState) -> None:
    global _current_state
    _current_state = state


async def push_user_response(response: UserResponse) -> None:
    """Called by routes to deliver user consent response to the main loop."""
    if _current_response_queue is not None:
        await _current_response_queue.put(response)


def _dict_to_vision_event(d: dict):
    """Convert a raw dict from the vision WS into a VisionEvent."""
    from openjarvis.kiosk.events import VisionEvent

    raw_event = d.get("event", "no_person")
    if raw_event == "person_present":
        kind = "person_near"
    elif raw_event in ("person_left", "scene_empty"):
        kind = "no_person"
    else:
        kind = raw_event

    ts = d.get("ts", time.time())
    nearest_m = d.get("nearest_m", 0.0)
    track_id = d.get("track_id", -1)
    return VisionEvent(kind=kind, ts=ts, nearest_m=nearest_m, track_id=track_id)
