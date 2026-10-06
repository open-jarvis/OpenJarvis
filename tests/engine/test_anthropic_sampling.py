"""Anthropic's fixed-sampling models reject the legacy temperature field."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import CloudEngine


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
    ["claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-4-7", "claude-sonnet-5"],
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
    assert sent["model"] == model
    assert sent["max_tokens"] == 32


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["_generate_anthropic", "_stream_anthropic", "_stream_full_anthropic"]
)
async def test_legacy_models_keep_requested_temperature(method):
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        model="claude-sonnet-4-6",
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

    assert sent["temperature"] == 0.4
