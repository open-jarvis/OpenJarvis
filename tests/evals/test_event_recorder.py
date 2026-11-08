"""Tests for EventRecorder thread safety and functionality."""

from __future__ import annotations

import threading

from friday_ai.evals.core.event_recorder import AgentEvent, EventRecorder, EventType


class TestEventType:
    def test_enum_values(self):
        assert EventType.LM_INFERENCE_START == "lm_inference_start"
        assert EventType.TOOL_CALL_END == "tool_call_end"

    def test_all_types_exist(self):
        assert len(EventType) == 10


class TestAgentEvent:
    def test_creation(self):
        e = AgentEvent(event_type="test", timestamp=123.456, metadata={"key": "val"})
        assert e.event_type == "test"
        assert e.timestamp == 123.456
        assert e.metadata == {"key": "val"}

    def test_repr(self):
        e = AgentEvent(event_type="test", timestamp=1.0)
        r = repr(e)
        assert "test" in r
        assert "1.000" in r


class TestEventRecorder:
    def test_record_and_get(self):
        rec = EventRecorder()
        rec.record("tool_call_start", tool="calc")
        rec.record("tool_call_end", tool="calc")
        events = rec.get_events()
        assert len(events) == 2
        assert events[0].event_type == "tool_call_start"
        assert events[0].metadata["tool"] == "calc"
        assert events[1].event_type == "tool_call_end"

    def test_len(self):
        rec = EventRecorder()
        assert len(rec) == 0
        rec.record("test")
        assert len(rec) == 1

    def test_clear(self):
        rec = EventRecorder()
        rec.record("test")
        rec.clear()
        assert len(rec) == 0
        assert rec.get_events() == []

    def test_get_events_returns_copy(self):
        rec = EventRecorder()
        rec.record("test")
        events = rec.get_events()
        events.clear()
        assert len(rec) == 1

    def test_timestamps_monotonic(self):
        rec = EventRecorder()
        for _ in range(10):
            rec.record("test")
        events = rec.get_events()
        for i in range(1, len(events)):
            assert events[i].timestamp >= events[i - 1].timestamp

    def test_thread_safety(self):
        rec = EventRecorder()
        barrier = threading.Barrier(4)

        def writer(thread_id):
            barrier.wait()
            for i in range(100):
                rec.record("test", thread=thread_id, index=i)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(rec) == 400
        events = rec.get_events()
        assert len(events) == 400
