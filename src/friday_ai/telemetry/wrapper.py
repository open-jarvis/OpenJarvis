"""Instrumented wrappers for inference engines — timing and telemetry publishing."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, Dict

from friday_ai.core.events import EventBus, EventType
from friday_ai.core.types import Message, TelemetryRecord
from friday_ai.engine._base import InferenceEngine


def instrumented_generate(
    engine: InferenceEngine,
    messages: Sequence[Message],
    *,
    model: str,
    bus: EventBus,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Call ``engine.generate()`` and publish telemetry events on *bus*.

    Returns the raw result dict from the engine.
    """
    bus.publish(EventType.INFERENCE_START, {"model": model, "engine": engine.engine_id})

    t0 = time.time()
    result = engine.generate(
        messages, model=model, temperature=temperature, max_tokens=max_tokens, **kwargs
    )
    latency = time.time() - t0

    usage = result.get("usage", {})
    rec = TelemetryRecord(
        timestamp=t0,
        model_id=model,
        engine=engine.engine_id,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        latency_seconds=latency,
        cost_usd=result.get("cost_usd", 0.0),
    )

    bus.publish(
        EventType.INFERENCE_END,
        {"model": model, "engine": engine.engine_id, "latency": latency},
    )
    bus.publish(EventType.TELEMETRY_RECORD, {"record": rec})

    return result


__all__ = ["instrumented_generate"]
