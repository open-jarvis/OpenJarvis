"""Tests for the instrumented inference wrappers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List
from unittest import mock

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Message, Role, TelemetryRecord
from openjarvis.engine._base import InferenceEngine
from openjarvis.telemetry.wrapper import instrumented_generate


class _StubEngine(InferenceEngine):
    engine_id = "stub"

    def __init__(self, response: Dict[str, Any] | None = None) -> None:
        self._response = response or {
            "content": "Hello",
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }

    def generate(
        self, messages: Sequence[Message], *, model: str, **kwargs: Any
    ) -> Dict[str, Any]:
        return self._response

    async def stream(
        self, messages: Sequence[Message], *, model: str, **kwargs: Any
    ) -> AsyncIterator[str]:
        yield "Hello"

    def list_models(self) -> List[str]:
        return ["stub-model"]

    def health(self) -> bool:
        return True


class TestInstrumentedGenerate:
    def test_calls_engine(self) -> None:
        engine = _StubEngine()
        bus = EventBus()
        result = instrumented_generate(
            engine,
            [Message(role=Role.USER, content="Hi")],
            model="m",
            bus=bus,
        )
        assert result["content"] == "Hello"

    def test_publishes_inference_events(self) -> None:
        engine = _StubEngine()
        bus = EventBus(record_history=True)
        instrumented_generate(
            engine,
            [Message(role=Role.USER, content="Hi")],
            model="m",
            bus=bus,
        )
        event_types = [e.event_type for e in bus.history]
        assert EventType.INFERENCE_START in event_types
        assert EventType.INFERENCE_END in event_types

    def test_publishes_telemetry_record(self) -> None:
        engine = _StubEngine()
        bus = EventBus(record_history=True)
        instrumented_generate(
            engine,
            [Message(role=Role.USER, content="Hi")],
            model="m",
            bus=bus,
        )
        telem_events = [
            e for e in bus.history if e.event_type == EventType.TELEMETRY_RECORD
        ]
        assert len(telem_events) == 1
        rec = telem_events[0].data["record"]
        assert isinstance(rec, TelemetryRecord)
        assert rec.model_id == "m"

    def test_measures_latency(self) -> None:
        engine = _StubEngine()
        bus = EventBus(record_history=True)
        instrumented_generate(
            engine,
            [Message(role=Role.USER, content="Hi")],
            model="m",
            bus=bus,
        )
        telem_events = [
            e for e in bus.history if e.event_type == EventType.TELEMETRY_RECORD
        ]
        rec = telem_events[0].data["record"]
        assert rec.latency_seconds >= 0

    def test_passes_kwargs(self) -> None:
        engine = _StubEngine()
        engine.generate = mock.MagicMock(return_value={"content": "ok", "usage": {}})
        bus = EventBus()
        instrumented_generate(
            engine,
            [Message(role=Role.USER, content="Hi")],
            model="m",
            bus=bus,
            temperature=0.1,
            max_tokens=512,
        )
        _, kwargs = engine.generate.call_args
        assert kwargs["temperature"] == 0.1
        assert kwargs["max_tokens"] == 512
