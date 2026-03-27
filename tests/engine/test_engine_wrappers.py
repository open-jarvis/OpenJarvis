"""Tests for InstrumentedEngine, GuardrailsEngine, and MultiEngine stream_full
delegation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Dict, List

import pytest

from openjarvis.core.events import EventBus
from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine, StreamChunk
from openjarvis.engine.multi import MultiEngine
from openjarvis.security.guardrails import GuardrailsEngine
from openjarvis.telemetry.instrumented_engine import InstrumentedEngine

# ---------------------------------------------------------------------------
# Fake engine that yields predetermined StreamChunks via stream_full
# ---------------------------------------------------------------------------


class _FakeStreamFullEngine(InferenceEngine):
    engine_id = "fake-sf"

    def __init__(self, chunks: list[StreamChunk]) -> None:
        self._chunks = chunks

    def generate(self, messages, *, model, **kwargs) -> Dict[str, Any]:
        return {"content": "ok", "usage": {}}

    async def stream(self, messages, *, model, **kwargs) -> AsyncIterator[str]:
        yield "ok"

    async def stream_full(
        self, messages, *, model, **kwargs
    ) -> AsyncIterator[StreamChunk]:
        for c in self._chunks:
            yield c

    def list_models(self) -> List[str]:
        return ["fake-model"]

    def health(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# InstrumentedEngine.stream_full delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_instrumented_delegates_stream_full():
    """InstrumentedEngine.stream_full delegates to inner engine."""
    expected = [
        StreamChunk(content="Hello"),
        StreamChunk(content=" world"),
        StreamChunk(finish_reason="stop"),
    ]
    inner = _FakeStreamFullEngine(expected)
    bus = EventBus(record_history=True)
    engine = InstrumentedEngine(inner, bus)

    result = []
    async for chunk in engine.stream_full(
        [Message(role=Role.USER, content="test")],
        model="fake-model",
    ):
        result.append(chunk)

    assert len(result) == 3
    assert result[0].content == "Hello"
    assert result[1].content == " world"
    assert result[2].finish_reason == "stop"


# ---------------------------------------------------------------------------
# GuardrailsEngine.stream_full delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guardrails_delegates_stream_full():
    """GuardrailsEngine.stream_full delegates to wrapped engine."""
    expected = [
        StreamChunk(content="safe output"),
        StreamChunk(finish_reason="stop"),
    ]
    inner = _FakeStreamFullEngine(expected)
    engine = GuardrailsEngine(inner, scanners=[])

    result = []
    async for chunk in engine.stream_full(
        [Message(role=Role.USER, content="test")],
        model="fake-model",
    ):
        result.append(chunk)

    assert len(result) == 2
    assert result[0].content == "safe output"
    assert result[1].finish_reason == "stop"


# ---------------------------------------------------------------------------
# MultiEngine.stream_full routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_routes_stream_full_by_model():
    """MultiEngine routes stream_full to the correct engine by model name."""
    chunks_a = [StreamChunk(content="from A"), StreamChunk(finish_reason="stop")]
    chunks_b = [StreamChunk(content="from B"), StreamChunk(finish_reason="stop")]

    engine_a = _FakeStreamFullEngine(chunks_a)
    engine_a.list_models = lambda: ["model-a"]

    engine_b = _FakeStreamFullEngine(chunks_b)
    engine_b.list_models = lambda: ["model-b"]

    multi = MultiEngine([("a", engine_a), ("b", engine_b)])

    # Route to engine A
    result_a = []
    async for chunk in multi.stream_full(
        [Message(role=Role.USER, content="test")],
        model="model-a",
    ):
        result_a.append(chunk)

    assert result_a[0].content == "from A"

    # Route to engine B
    result_b = []
    async for chunk in multi.stream_full(
        [Message(role=Role.USER, content="test")],
        model="model-b",
    ):
        result_b.append(chunk)

    assert result_b[0].content == "from B"
