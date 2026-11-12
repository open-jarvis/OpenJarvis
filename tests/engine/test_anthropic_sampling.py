"""Anthropic's fixed-sampling models reject the legacy temperature field."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import (
    _ANTHROPIC_ALWAYS_THINKING_PREFIXES,
    _ANTHROPIC_MIN_THINKING_MAX_TOKENS,
    CloudEngine,
)


class _Stream:
    text_stream = ("ok",)

    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self.response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["_generate_anthropic", "_stream_anthropic", "_stream_full_anthropic"]
)
@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5-5",
        "claude-sonnet-5",
        "claude-sonnet-5-5",
        "claude-fable-5-1",
        "claude-haiku-5-5",
    ],
)
async def test_fixed_sampling_models_omit_temperature(method, model):
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        model=model,
        stop_reason="end_turn",
    )
    client = MagicMock()
    client.messages.create.return_value = response
    client.messages.stream.return_value = _Stream(response)
    engine = CloudEngine.__new__(CloudEngine)
    engine._anthropic_client = client
    messages = [Message(role=Role.USER, content="Hi")]

    if method == "_generate_anthropic":
        result = engine._generate_anthropic(
            messages, model=model, temperature=0.4, max_tokens=32
        )
        assert result["content"] == "ok"
        sent = client.messages.create.call_args.kwargs
    else:
        _ = [
            chunk
            async for chunk in getattr(engine, method)(
                messages, model=model, temperature=0.4, max_tokens=32
            )
        ]
        sent = client.messages.stream.call_args.kwargs

    assert "temperature" not in sent
    assert "temperature" not in sent.get("extra_body", {})
    assert sent["model"] == model
    if model.startswith(_ANTHROPIC_ALWAYS_THINKING_PREFIXES):
        # Always-thinking models get a floor so reasoning can't eat the reply.
        assert sent["max_tokens"] == _ANTHROPIC_MIN_THINKING_MAX_TOKENS
    else:
        assert sent["max_tokens"] == 32


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["_generate_anthropic", "_stream_anthropic", "_stream_full_anthropic"]
)
@pytest.mark.parametrize(
    "model", ["claude-sonnet-4-6", "claude-haiku-4-5", "claude-haiku-4-5-20251001"]
)
async def test_legacy_models_keep_requested_temperature(method, model):
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        model=model,
        stop_reason="end_turn",
    )
    client = MagicMock()
    client.messages.create.return_value = response
    client.messages.stream.return_value = _Stream(response)
    engine = CloudEngine.__new__(CloudEngine)
    engine._anthropic_client = client
    messages = [Message(role=Role.USER, content="Hi")]
    kwargs = {"model": response.model, "temperature": 0.4, "max_tokens": 32}

    if method == "_generate_anthropic":
        engine._generate_anthropic(messages, **kwargs)
        sent = client.messages.create.call_args.kwargs
    else:
        _ = [chunk async for chunk in getattr(engine, method)(messages, **kwargs)]
        sent = client.messages.stream.call_args.kwargs

    assert "temperature" not in sent
    assert sent["extra_body"]["temperature"] == 0.4
