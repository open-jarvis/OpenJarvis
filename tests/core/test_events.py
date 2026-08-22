"""Tests for the pub/sub event bus."""

from __future__ import annotations

import logging
import threading

from openjarvis.core.events import (
    Event,
    EventBus,
    EventType,
    get_event_bus,
    reset_event_bus,
)


class TestEventBus:
    def test_subscribe_and_publish(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(EventType.INFERENCE_END, received.append)
        bus.publish(EventType.INFERENCE_END, {"model": "test"})
        assert len(received) == 1
        assert received[0].data["model"] == "test"

    def test_multiple_subscribers(self) -> None:
        bus = EventBus()
        a: list[Event] = []
        b: list[Event] = []
        bus.subscribe(EventType.TOOL_CALL_START, a.append)
        bus.subscribe(EventType.TOOL_CALL_START, b.append)
        bus.publish(EventType.TOOL_CALL_START)
        assert len(a) == 1
        assert len(b) == 1

    def test_failing_subscriber_does_not_starve_later_subscribers(self, caplog) -> None:
        bus = EventBus()
        received: list[Event] = []

        def fail(_event: Event) -> None:
            raise ValueError("boom")

        bus.subscribe(EventType.INFERENCE_END, fail)
        bus.subscribe(EventType.INFERENCE_END, received.append)

        with caplog.at_level(logging.ERROR, logger="openjarvis.core.events"):
            event = bus.publish(EventType.INFERENCE_END, {"model": "test"})

        assert received == [event]
        assert "boom" in caplog.text
        assert "inference_end" in caplog.text

    def test_publish_does_not_swallow_process_control_exceptions(self) -> None:
        bus = EventBus()

        def interrupt(_event: Event) -> None:
            raise KeyboardInterrupt

        bus.subscribe(EventType.INFERENCE_END, interrupt)

        try:
            bus.publish(EventType.INFERENCE_END)
        except KeyboardInterrupt:
            pass
        else:  # pragma: no cover - regression assertion
            raise AssertionError("KeyboardInterrupt should propagate")

    def test_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(EventType.MEMORY_STORE, received.append)
        bus.unsubscribe(EventType.MEMORY_STORE, received.append)
        bus.publish(EventType.MEMORY_STORE)
        assert len(received) == 0

    def test_unsubscribe_missing_callback_no_error(self) -> None:
        bus = EventBus()
        bus.unsubscribe(EventType.INFERENCE_START, lambda e: None)  # no-op

    def test_history_recording(self) -> None:
        bus = EventBus(record_history=True)
        bus.publish(EventType.INFERENCE_START)
        bus.publish(EventType.INFERENCE_END)
        assert len(bus.history) == 2

    def test_history_off_by_default(self) -> None:
        bus = EventBus()
        bus.publish(EventType.INFERENCE_START)
        assert len(bus.history) == 0

    def test_clear_history(self) -> None:
        bus = EventBus(record_history=True)
        bus.publish(EventType.AGENT_TURN_START)
        bus.clear_history()
        assert len(bus.history) == 0

    def test_publish_returns_event(self) -> None:
        bus = EventBus()
        event = bus.publish(EventType.TELEMETRY_RECORD, {"k": "v"})
        assert isinstance(event, Event)
        assert event.event_type == EventType.TELEMETRY_RECORD

    def test_different_event_types_isolated(self) -> None:
        bus = EventBus()
        a: list[Event] = []
        bus.subscribe(EventType.INFERENCE_START, a.append)
        bus.publish(EventType.INFERENCE_END)
        assert len(a) == 0

    def test_thread_safety(self) -> None:
        bus = EventBus(record_history=True)
        n = 100

        def worker() -> None:
            for _ in range(n):
                thread_name = threading.current_thread().name
                bus.publish(EventType.INFERENCE_END, {"t": thread_name})

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(bus.history) == 4 * n


class TestAgentEventTypes:
    def test_agent_tick_events_exist(self):
        from openjarvis.core.events import EventType

        assert EventType.AGENT_TICK_START
        assert EventType.AGENT_TICK_END
        assert EventType.AGENT_TICK_ERROR

    def test_agent_operational_events_exist(self):
        from openjarvis.core.events import EventType

        assert EventType.AGENT_BUDGET_EXCEEDED
        assert EventType.AGENT_STALL_DETECTED
        assert EventType.AGENT_MESSAGE_RECEIVED
        assert EventType.AGENT_CHECKPOINT_SAVED


class TestSingleton:
    def test_get_event_bus_returns_same_instance(self) -> None:
        reset_event_bus()
        a = get_event_bus()
        b = get_event_bus()
        assert a is b

    def test_reset_replaces_instance(self) -> None:
        reset_event_bus()
        a = get_event_bus()
        reset_event_bus()
        b = get_event_bus()
        assert a is not b
