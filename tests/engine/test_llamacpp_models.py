"""Tests for llama.cpp engine with compatible models."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.openai_compat_engines import LlamaCppEngine

LLAMACPP_HOST = "http://testhost:8080"
# Only models with llamacpp in supported_engines
COMPATIBLE_MODELS = ["qwen3:8b", "trinity-mini"]


def _make_engine() -> LlamaCppEngine:
    if not EngineRegistry.contains("llamacpp"):
        EngineRegistry.register_value("llamacpp", LlamaCppEngine)
    return LlamaCppEngine(host=LLAMACPP_HOST)


def _openai_response(
    content: str = "Hello!",
    model: str = "qwen3:8b",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    tool_calls: list | None = None,
    finish_reason: str = "stop",
) -> dict:
    """Build an OpenAI-format response dict."""
    message: dict = {"content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
        finish_reason = "tool_calls"
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "model": model,
    }


# ---------------------------------------------------------------------------
# Generate tests (parametrized over compatible models)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", COMPATIBLE_MODELS)
class TestLlamaCppGenerate:
    def test_generate_basic(self, respx_mock, model_id: str) -> None:
        engine = _make_engine()
        respx_mock.post(f"{LLAMACPP_HOST}/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, json=_openai_response(content="Test reply", model=model_id)
            )
        )
        result = engine.generate(
            [Message(role=Role.USER, content="Hello")], model=model_id
        )
        assert result["content"] == "Test reply"
        assert result["model"] == model_id
        assert result["usage"]["total_tokens"] == 15

    def test_generate_with_tools(self, respx_mock, model_id: str) -> None:
        engine = _make_engine()
        tool_calls = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {
                    "name": "calculator",
                    "arguments": '{"expression":"3*3"}',
                },
            }
        ]
        respx_mock.post(f"{LLAMACPP_HOST}/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json=_openai_response(
                    content="",
                    model=model_id,
                    tool_calls=tool_calls,
                ),
            )
        )
        result = engine.generate(
            [Message(role=Role.USER, content="3*3")],
            model=model_id,
            tools=[{"type": "function", "function": {"name": "calculator"}}],
        )
        assert "tool_calls" in result
        assert result["tool_calls"][0]["name"] == "calculator"

    def test_generate_tool_fallback(self, respx_mock, model_id: str) -> None:
        """400 with tools in payload → retry without tools."""
        engine = _make_engine()
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            body = json.loads(request.content)
            if "tools" in body:
                return httpx.Response(400, json={"error": "unsupported"})
            return httpx.Response(
                200, json=_openai_response(content="Fallback", model=model_id)
            )

        respx_mock.post(f"{LLAMACPP_HOST}/v1/chat/completions").mock(
            side_effect=handler
        )
        result = engine.generate(
            [Message(role=Role.USER, content="Hello")],
            model=model_id,
            tools=[{"type": "function", "function": {"name": "calc"}}],
        )
        assert result["content"] == "Fallback"
        assert call_count == 2

    def test_generate_streaming(self, respx_mock, model_id: str) -> None:
        engine = _make_engine()
        sse = (
            'data: {"choices":[{"delta":{"content":"Hi"}}]}\n'
            'data: {"choices":[{"delta":{"content":" there"}}]}\n'
            "data: [DONE]\n"
        )
        respx_mock.post(f"{LLAMACPP_HOST}/v1/chat/completions").mock(
            return_value=httpx.Response(200, text=sse)
        )

        async def collect():
            tokens = []
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hi")], model=model_id
            ):
                tokens.append(tok)
            return tokens

        import asyncio

        tokens = asyncio.run(collect())
        assert tokens == ["Hi", " there"]


# ---------------------------------------------------------------------------
# Model discovery & health
# ---------------------------------------------------------------------------


class TestLlamaCppModelDiscovery:
    def test_list_models(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.get(f"{LLAMACPP_HOST}/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": m} for m in COMPATIBLE_MODELS]},
            )
        )
        assert engine.list_models() == COMPATIBLE_MODELS

    def test_health_healthy(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.get(f"{LLAMACPP_HOST}/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        assert engine.health() is True

    def test_health_unhealthy(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.get(f"{LLAMACPP_HOST}/v1/models").mock(
            side_effect=httpx.ConnectError("refused")
        )
        assert engine.health() is False


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TestLlamaCppErrors:
    def test_connection_refused(self) -> None:
        engine = _make_engine()
        with respx.mock:
            respx.post(f"{LLAMACPP_HOST}/v1/chat/completions").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )

    def test_default_host_is_8080(self) -> None:
        """LlamaCppEngine defaults to port 8080."""
        engine = LlamaCppEngine()
        assert engine._host == "http://localhost:8080"

    def test_engine_id(self) -> None:
        engine = LlamaCppEngine()
        assert engine.engine_id == "llamacpp"
