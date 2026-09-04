"""Regression tests for OpenRouter model ID normalization."""

from __future__ import annotations

import json

import httpx
import pytest

from openjarvis.core.types import Message
from openjarvis.engine._base import EngineConnectionError
from openjarvis.server import cloud_router


def _mock_openrouter_stream(
    monkeypatch, *, model="stealth/ox-alpha", first_model=None, cost=0
) -> dict[str, dict]:
    captured: dict[str, dict] = {}
    events = "\n\n".join(
        [
            "data: "
            + json.dumps(
                {
                    "model": first_model or model,
                    "choices": [{"delta": {"content": "ok"}}],
                }
            ),
            "data: "
            + json.dumps(
                {
                    "model": model,
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                        "cost": cost,
                    },
                }
            ),
            "data: [DONE]",
        ]
    )
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=events,
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        cloud_router.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )
    return captured


def test_get_provider_detects_bare_openrouter_id():
    assert cloud_router.get_provider("anthropic/claude-haiku-4.5") == "openrouter"


def test_get_provider_detects_litellm_prefixed_openrouter_id():
    model = "openrouter/anthropic/claude-haiku-4.5"
    assert cloud_router.get_provider(model) == "openrouter"


@pytest.mark.parametrize(
    "requested_model,expected_forwarded_model",
    [
        ("anthropic/claude-haiku-4.5", "anthropic/claude-haiku-4.5"),
        ("openrouter/anthropic/claude-haiku-4.5", "anthropic/claude-haiku-4.5"),
        ("openrouter/auto", "openrouter/auto"),
    ],
)
@pytest.mark.asyncio
async def test_stream_cloud_normalizes_openrouter_model_before_forwarding(
    monkeypatch, requested_model, expected_forwarded_model
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured: dict[str, str] = {}

    async def fake_stream_openai(model, messages, temperature, max_tokens, **kwargs):
        captured["model"] = model
        yield "ok"

    monkeypatch.setattr(cloud_router, "_stream_openai", fake_stream_openai)

    tokens = [
        token
        async for token in cloud_router.stream_cloud(
            requested_model, [Message(role="user", content="hi")]
        )
    ]

    assert tokens == ["ok"]
    assert captured["model"] == expected_forwarded_model


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested_model", ["openrouter/stealth/ox-alpha", "stealth/ox-alpha"]
)
async def test_direct_ox_stream_enforces_free_private_route(
    monkeypatch, requested_model
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured = _mock_openrouter_stream(monkeypatch)

    tokens = [
        token
        async for token in cloud_router.stream_cloud(
            requested_model, [Message(role="user", content="hi")]
        )
    ]

    assert tokens == ["ok"]
    assert captured["payload"]["provider"] == {
        "allow_fallbacks": False,
        "data_collection": "deny",
        "zdr": True,
        "max_price": {
            "prompt": 0,
            "completion": 0,
            "request": 0,
            "image": 0,
        },
    }
    assert captured["payload"]["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_direct_ox_stream_rejects_nonzero_cost(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _mock_openrouter_stream(monkeypatch, cost=0.01)

    stream = cloud_router.stream_cloud(
        "openrouter/stealth/ox-alpha", [Message(role="user", content="hi")]
    )

    with pytest.raises(EngineConnectionError):
        await anext(stream)


@pytest.mark.asyncio
async def test_direct_ox_stream_rejects_model_change_before_yielding(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _mock_openrouter_stream(monkeypatch, first_model="paid/substitute")
    stream = cloud_router.stream_cloud(
        "openrouter/stealth/ox-alpha", [Message(role="user", content="hi")]
    )

    with pytest.raises(EngineConnectionError):
        await anext(stream)


@pytest.mark.asyncio
async def test_other_openrouter_stream_has_no_ox_policy(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured = _mock_openrouter_stream(monkeypatch, model="anthropic/claude-haiku-4.5")

    tokens = [
        token
        async for token in cloud_router.stream_cloud(
            "openrouter/anthropic/claude-haiku-4.5",
            [Message(role="user", content="hi")],
        )
    ]

    assert tokens == ["ok"]
    assert "provider" not in captured["payload"]
