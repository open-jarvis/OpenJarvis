"""Tests for Kiosk FSM side effects."""

from __future__ import annotations

import asyncio

from openjarvis.core.events import EventBus, EventType
from openjarvis.kiosk.effects import KioskDependencies, SideEffect, run_side_effects


def test_publish_state_emits_kiosk_state_event() -> None:
    bus = EventBus(record_history=True)

    asyncio.run(
        run_side_effects(
            [SideEffect("publish_state", {"state": "prompting", "mic_enabled": False})],
            KioskDependencies(bus=bus),
        )
    )

    assert len(bus.history) == 1
    assert bus.history[0].event_type == EventType.KIOSK_STATE_CHANGED
    assert bus.history[0].data == {"state": "prompting", "mic_enabled": False}
