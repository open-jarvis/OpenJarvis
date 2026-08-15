"""Side effects for the kiosk FSM — all I/O lives here, never in evaluate_state()."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from openjarvis.core.events import EventType

logger = logging.getLogger(__name__)

_TTS_MAP = {
    "tts_greeting": "Xin chào! Tôi có thể giúp gì cho bạn?",
    "tts_warning": "Phiên trò chuyện sẽ kết thúc sau 1 phút nữa.",
    "tts_goodbye": "Tạm biệt! Hẹn gặp lại.",
}

# -- SideEffect -------------------------------------------------------


@dataclass
class SideEffect:
    """A deferred I/O action returned by evaluate_state().

    evaluate_state() is pure — it returns a list of SideEffect
    descriptors. run_side_effects() executes them against real
    dependencies. This separation makes state transitions fully
    testable without mocking I/O.
    """

    kind: Literal[
        "publish_state",
        "tts_greeting",
        "tts_warning",
        "tts_goodbye",
    ]
    data: dict = field(default_factory=dict)


# -- KioskDependencies -------------------------------------------------


@dataclass
class KioskDependencies:
    """All I/O dependencies injected into run_side_effects().

    Never accessed by evaluate_state() — that function is pure.
    """

    bus: Any | None = None                         # has .publish(event_type, data)
    tts: Callable[[str], Awaitable[None]] | None = None  # async text-to-speech


# -- Runner -----------------------------------------------------------

async def run_side_effects(
    effects: list[SideEffect],
    deps: KioskDependencies,
) -> None:
    """Execute side effects in order. Never called from evaluate_state()."""

    for fx in effects:
        try:
            if fx.kind == "publish_state" and deps.bus is not None:
                deps.bus.publish(EventType.KIOSK_STATE_CHANGED, fx.data)

            elif fx.kind in _TTS_MAP and deps.tts is not None:
                text = fx.data.get("text", _TTS_MAP[fx.kind])
                await deps.tts(text)

        except Exception:
            logger.exception("Side effect %s failed", fx.kind)
