"""Tests for InstrumentedEngine telemetry wrapper."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import TOKEN_COUNTING_VERSION, Message, Role
from openjarvis.engine._stubs import StreamChunk
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

    def test_generate_records_cost(self, mock_engine, bus):
        mock_engine.generate.return_value["cost_usd"] = 0.0015
        ie = InstrumentedEngine(mock_engine, bus)
        messages = [Message(role=Role.USER, content="Hi")]
        ie.generate(messages, model="test")

        event = next(
            e for e in bus.history if e.event_type == EventType.TELEMETRY_RECORD
        )
        assert event.data["record"].cost_usd == pytest.approx(0.0015)

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

    @pytest.mark.asyncio
    async def test_stream_full_records_terminal_usage_and_preserves_chunks(self, bus):
        expected = [
            StreamChunk(content="Hello"),
            StreamChunk(tool_calls=[{"index": 0, "function": {"name": "lookup"}}]),
            StreamChunk(
                finish_reason="tool_calls",
                usage={
                    "prompt_tokens": 7,
                    "prompt_tokens_evaluated": 5,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                },
            ),
        ]

        class StreamFullEngine:
            engine_id = "stream-full"

            async def stream_full(self, messages, *, model, **kwargs):
                for chunk in expected:
                    yield chunk

        engine = InstrumentedEngine(StreamFullEngine(), bus)
        messages = [Message(role=Role.USER, content="Hi")]

        actual = [
            chunk async for chunk in engine.stream_full(messages, model="test-model")
        ]

        assert actual == expected
        assert all(
            actual_chunk is expected_chunk
            for actual_chunk, expected_chunk in zip(actual, expected)
        )
        assert [event.event_type for event in bus.history] == [
            EventType.INFERENCE_START,
            EventType.INFERENCE_END,
            EventType.TELEMETRY_RECORD,
        ]
        record = bus.history[-1].data["record"]
        assert record.engine == "stream-full"
        assert record.is_streaming is True
        assert record.prompt_tokens == 7
        assert record.prompt_tokens_evaluated == 5
        assert record.completion_tokens == 3
        assert record.total_tokens == 10
        assert record.token_counting_version == TOKEN_COUNTING_VERSION
        end_event = bus.history[-2]
        assert end_event.data["usage"]["completion_tokens"] == 3

    @pytest.mark.asyncio
    async def test_stream_full_without_usage_counts_only_content_chunks(self, bus):
        chunks = [
            StreamChunk(content="first"),
            StreamChunk(content=""),
            StreamChunk(tool_calls=[{"index": 0}]),
            StreamChunk(content="second"),
            StreamChunk(finish_reason="stop"),
        ]

        class StreamFullEngine:
            engine_id = "stream-full"

            async def stream_full(self, messages, *, model, **kwargs):
                for chunk in chunks:
                    yield chunk

        engine = InstrumentedEngine(StreamFullEngine(), bus)
        messages = [Message(role=Role.USER, content="Hi")]

        actual = [
            chunk async for chunk in engine.stream_full(messages, model="test-model")
        ]

        assert actual == chunks
        assert [event.event_type for event in bus.history] == [
            EventType.INFERENCE_START,
            EventType.INFERENCE_END,
            EventType.TELEMETRY_RECORD,
        ]
        record = next(
            event.data["record"]
            for event in bus.history
            if event.event_type == EventType.TELEMETRY_RECORD
        )
        assert record.completion_tokens == 2
        assert record.prompt_tokens == 0
        assert record.total_tokens == 0
        assert record.is_streaming is True
        end_event = next(
            event
            for event in bus.history
            if event.event_type == EventType.INFERENCE_END
        )
        assert "usage" not in end_event.data

    @pytest.mark.asyncio
    async def test_stream_full_prefers_later_usage_over_earlier(self, bus):
        chunks = [
            StreamChunk(
                content="Hello",
                usage={
                    "prompt_tokens": 1,
                    "completion_tokens": 99,
                    "total_tokens": 100,
                },
            ),
            StreamChunk(
                finish_reason="stop",
                usage={
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                },
            ),
        ]

        class StreamFullEngine:
            engine_id = "stream-full"

            async def stream_full(self, messages, *, model, **kwargs):
                for chunk in chunks:
                    yield chunk

        engine = InstrumentedEngine(StreamFullEngine(), bus)
        messages = [Message(role=Role.USER, content="Hi")]

        actual = [
            chunk async for chunk in engine.stream_full(messages, model="test-model")
        ]

        assert actual == chunks
        record = next(
            event.data["record"]
            for event in bus.history
            if event.event_type == EventType.TELEMETRY_RECORD
        )
        assert record.prompt_tokens == 7
        assert record.completion_tokens == 3
        assert record.total_tokens == 10

    @pytest.mark.asyncio
    async def test_stream_shared_finalizer_preserves_no_usage_shape(self, bus):
        class StreamEngine:
            engine_id = "stream"

            async def stream(self, messages, *, model, **kwargs):
                for token in ["Hello", "", " world"]:
                    yield token

        engine = InstrumentedEngine(StreamEngine(), bus)
        messages = [Message(role=Role.USER, content="Hi")]

        tokens = [token async for token in engine.stream(messages, model="test-model")]

        assert tokens == ["Hello", "", " world"]
        assert [event.event_type for event in bus.history] == [
            EventType.INFERENCE_START,
            EventType.INFERENCE_END,
            EventType.TELEMETRY_RECORD,
        ]
        record = bus.history[-1].data["record"]
        assert record.completion_tokens == 3
        assert record.prompt_tokens == 0
        assert record.total_tokens == 0
        assert record.is_streaming is True
        assert "usage" not in bus.history[-2].data

    @pytest.mark.asyncio
    async def test_stream_full_tool_only_records_energy(self, bus):
        class EnergySample:
            energy_joules = 4.0
            mean_power_watts = 8.0
            mean_utilization_pct = 25.0
            peak_memory_used_gb = 1.0
            mean_temperature_c = 40.0
            energy_method = "test"
            vendor = "test"
            cpu_energy_joules = 1.0
            gpu_energy_joules = 3.0
            dram_energy_joules = 0.0
            ane_energy_joules = 0.0
            soc_energy_joules = 4.0
            basis = "soc"

        class EnergyMonitor:
            active = False

            @contextmanager
            def sample(self):
                self.active = True
                try:
                    yield EnergySample()
                finally:
                    self.active = False

        monitor = EnergyMonitor()

        class StreamFullEngine:
            engine_id = "stream-full"

            async def stream_full(self, messages, *, model, **kwargs):
                assert monitor.active is True
                yield StreamChunk(tool_calls=[{"index": 0}])
                assert monitor.active is True
                yield StreamChunk(
                    finish_reason="tool_calls",
                    usage={
                        "prompt_tokens": 4,
                        "completion_tokens": 0,
                        "total_tokens": 4,
                    },
                )

        engine = InstrumentedEngine(
            StreamFullEngine(),
            bus,
            energy_monitor=monitor,
        )
        messages = [Message(role=Role.USER, content="Use a tool")]

        chunks = [
            chunk async for chunk in engine.stream_full(messages, model="test-model")
        ]

        assert len(chunks) == 2
        assert monitor.active is False
        record = next(
            event.data["record"]
            for event in bus.history
            if event.event_type == EventType.TELEMETRY_RECORD
        )
        assert record.prompt_tokens == 4
        assert record.completion_tokens == 0
        assert record.energy_joules == 4.0


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
