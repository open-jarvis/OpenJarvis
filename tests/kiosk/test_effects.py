"""Tests for Kiosk FSM side effects."""

from __future__ import annotations

import asyncio

from openjarvis.core.events import EventBus, EventType
from openjarvis.kiosk.effects import KioskDependencies, SideEffect, run_side_effects
from openjarvis.kiosk.evaluate import evaluate_state
from openjarvis.kiosk.events import EventHistory


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


def test_accepting_the_kiosk_prompt_loads_the_default_menu_before_enabling_mic(
) -> None:
    state, effects = evaluate_state(
        EventHistory(),
        now=0.0,
        current_state="prompting",
        user_response="accept",
        session_start=None,
        prompting_started_at=0.0,
    )

    assert state == "active"
    assert effects == [
        SideEffect("publish_state", {"state": "active", "mic_enabled": False}),
        SideEffect("load_initial_display"),
        SideEffect("tts_greeting"),
        SideEffect("publish_state", {"state": "active", "mic_enabled": True}),
    ]


def test_publish_display_scopes_menu_to_the_presentation_session() -> None:
    bus = EventBus(record_history=True)

    class Presentation:
        def publish(self, payload: dict) -> None:
            bus.publish(
                EventType.DISPLAY_UPDATE,
                {**payload, "presentation_session_id": "session-1"},
            )

    asyncio.run(
        run_side_effects(
            [SideEffect("publish_display", {"view": "menu", "items": []})],
            KioskDependencies(bus=bus, presentation=Presentation()),
        )
    )

    assert bus.history[0].event_type == EventType.DISPLAY_UPDATE
    assert bus.history[0].data == {
        "view": "menu",
        "items": [],
        "presentation_session_id": "session-1",
    }


def test_load_initial_display_runs_the_configured_menu_recipe() -> None:
    calls: list[str] = []

    class Presentation:
        def load_initial_display(self) -> None:
            calls.append("menu")

    asyncio.run(
        run_side_effects(
            [SideEffect("load_initial_display")],
            KioskDependencies(presentation=Presentation()),
        )
    )

    assert calls == ["menu"]
