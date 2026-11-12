"""Exercise the real Anthropic SDK against an in-memory HTTP transport."""

from __future__ import annotations

import json

import pytest

from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import (
    _ANTHROPIC_ALWAYS_THINKING_PREFIXES,
    _ANTHROPIC_MIN_THINKING_MAX_TOKENS,
    CloudEngine,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["generate", "stream", "stream_full"])
@pytest.mark.parametrize(
    "model,supports_temperature",
    [
        ("claude-sonnet-4-6", True),
        ("claude-haiku-4-5-20251001", True),
        ("claude-opus-4-7", False),
        ("claude-opus-4-8", False),
        ("claude-opus-5-5", False),
        ("claude-sonnet-5-5", False),
        ("claude-fable-5-1", False),
        ("claude-haiku-5-5", False),
    ],
)
async def test_anthropic_sdk_sampling_parameters(
    mode: str, model: str, supports_temperature: bool
) -> None:
    anthropic = pytest.importorskip("anthropic")
    http = pytest.importorskip("httpx2")
    requests = []
    message = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "Hello"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 3, "output_tokens": 1},
    }

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if not body.get("stream"):
            return http.Response(200, json=message)
        events = [
            {
                "type": "message_start",
                "message": {**message, "content": [], "stop_reason": None},
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
            {"type": "message_stop"},
        ]
        content = "".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
        )
        return http.Response(
            200, headers={"content-type": "text/event-stream"}, text=content
        )

    with anthropic.Anthropic(
        api_key="test-key",
        http_client=anthropic.DefaultHttpxClient(transport=http.MockTransport(respond)),
    ) as client:
        engine = CloudEngine()
        engine._anthropic_client = client
        kwargs = {
            "model": message["model"],
            "temperature": 0.35,
            "max_tokens": 42,
        }
        messages = [Message(role=Role.USER, content="Hi")]
        if mode == "generate":
            assert engine._generate_anthropic(messages, **kwargs)["content"] == "Hello"
        elif mode == "stream":
            chunks = [
                chunk async for chunk in engine._stream_anthropic(messages, **kwargs)
            ]
            assert "".join(chunks) == "Hello"
        else:
            chunks = [
                chunk
                async for chunk in engine._stream_full_anthropic(messages, **kwargs)
            ]
            assert "".join(chunk.content or "" for chunk in chunks) == "Hello"

    assert len(requests) == 1
    if supports_temperature:
        assert requests[0]["temperature"] == 0.35
    else:
        assert "temperature" not in requests[0]
    if model.startswith(_ANTHROPIC_ALWAYS_THINKING_PREFIXES):
        # Always-thinking models get a floor so reasoning can't eat the reply.
        assert requests[0]["max_tokens"] == _ANTHROPIC_MIN_THINKING_MAX_TOKENS
    else:
        assert requests[0]["max_tokens"] == 42
    assert requests[0]["model"] == message["model"]
