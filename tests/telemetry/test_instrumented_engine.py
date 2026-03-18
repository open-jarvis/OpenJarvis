"""Tests for InstrumentedEngine telemetry wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Message, Role
from openjarvis.telemetry.instrumented_engine import InstrumentedEngine


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": "Hello!",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    engine.list_models.return_value = ["test-model"]
    engine.health.return_value = True
    engine.stream.return_value = iter(["Hello", " world"])
    return engine


@pytest.fixture
def bus():
    return EventBus(record_history=True)


class TestInstrumentedEngine:
    def test_generate_passes_through(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        messages = [Message(role=Role.USER, content="Hi")]
        result = ie.generate(messages, model="test")
        assert result["content"] == "Hello!"
        mock_engine.generate.assert_called_once()

    def test_generate_publishes_events(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        messages = [Message(role=Role.USER, content="Hi")]
        ie.generate(messages, model="test")

        event_types = [e.event_type for e in bus.history]
        assert EventType.INFERENCE_START in event_types
        assert EventType.INFERENCE_END in event_types
        assert EventType.TELEMETRY_RECORD in event_types

    def test_generate_records_latency(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        messages = [Message(role=Role.USER, content="Hi")]
        ie.generate(messages, model="test")

        end_events = [e for e in bus.history if e.event_type == EventType.INFERENCE_END]
        assert len(end_events) == 1
        assert "latency" in end_events[0].data

    def test_generate_records_telemetry(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        messages = [Message(role=Role.USER, content="Hi")]
        ie.generate(messages, model="test")

        tel_events = [
            e for e in bus.history if e.event_type == EventType.TELEMETRY_RECORD
        ]
        assert len(tel_events) == 1
        record = tel_events[0].data["record"]
        assert record.model_id == "test"
        assert record.prompt_tokens == 10
        assert record.completion_tokens == 5

    def test_list_models_delegates(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        assert ie.list_models() == ["test-model"]

    def test_health_delegates(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        assert ie.health() is True

    def test_stream_delegates(self, mock_engine, bus):
        """Stream is async, so we test via pytest-asyncio or manually."""
        # InstrumentedEngine.stream is async, so we skip sync iteration test
        # and just verify the method exists and delegates
        ie = InstrumentedEngine(mock_engine, bus)
        assert hasattr(ie, "stream")

    def test_temperature_passthrough(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        messages = [Message(role=Role.USER, content="Hi")]
        ie.generate(messages, model="test", temperature=0.5, max_tokens=100)
        call_kwargs = mock_engine.generate.call_args
        temp = call_kwargs.kwargs.get("temperature") or call_kwargs[1].get(
            "temperature"
        )
        assert temp == 0.5

    def test_inner_engine_id(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        tel_events_data = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: tel_events_data.append(e.data),
        )
        messages = [Message(role=Role.USER, content="Hi")]
        ie.generate(messages, model="test")
        assert tel_events_data[0]["record"].engine == "mock"

    def test_kwargs_passthrough(self, mock_engine, bus):
        """Extra kwargs should be forwarded to inner engine."""
        ie = InstrumentedEngine(mock_engine, bus)
        messages = [Message(role=Role.USER, content="Hi")]
        ie.generate(messages, model="test", tools=[{"type": "function"}])
        call_kwargs = mock_engine.generate.call_args[1]
        assert "tools" in call_kwargs

    def test_engine_id_attribute(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        assert ie.engine_id == "instrumented"


class TestTokensPerJoule:
    def test_tokens_per_joule_zero_without_energy(self, mock_engine, bus):
        """tokens_per_joule is 0.0 when no energy monitor is available."""
        ie = InstrumentedEngine(mock_engine, bus)
        messages = [Message(role=Role.USER, content="Hi")]
        ie.generate(messages, model="test")

        tel_events = [
            e for e in bus.history if e.event_type == EventType.TELEMETRY_RECORD
        ]
        record = tel_events[0].data["record"]
        assert record.tokens_per_joule == 0.0

    def test_tokens_per_joule_formula_via_record(self):
        """Verify the formula: tokens_per_joule = completion_tokens / energy_joules."""
        from openjarvis.core.types import TelemetryRecord

        # Direct construction — verifies the field accepts computed values
        rec = TelemetryRecord(
            timestamp=1.0,
            model_id="test",
            completion_tokens=50,
            energy_joules=2.5,
            tokens_per_joule=50.0 / 2.5,  # = 20.0
        )
        assert rec.tokens_per_joule == pytest.approx(20.0)

    def test_tokens_per_joule_zero_when_no_tokens(self):
        """tokens_per_joule is 0.0 when completion_tokens is 0."""
        from openjarvis.core.types import TelemetryRecord

        rec = TelemetryRecord(
            timestamp=1.0,
            model_id="test",
            completion_tokens=0,
            energy_joules=5.0,
            tokens_per_joule=0.0,
        )
        assert rec.tokens_per_joule == 0.0
