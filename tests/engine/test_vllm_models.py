"""Tests for vLLM engine with extended local model set."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.openai_compat_engines import VLLMEngine

VLLM_HOST = "http://testhost:8000"
NEW_MODELS = ["gpt-oss:120b", "qwen3:8b", "glm-4.7-flash", "trinity-mini"]


def _make_engine() -> VLLMEngine:
    if not EngineRegistry.contains("vllm"):
        EngineRegistry.register_value("vllm", VLLMEngine)
    return VLLMEngine(host=VLLM_HOST)


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
# Generate tests (parametrized over new models)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", NEW_MODELS)
class TestVLLMGenerate:
    def test_generate_basic(self, respx_mock, model_id: str) -> None:
        engine = _make_engine()
        respx_mock.post(f"{VLLM_HOST}/v1/chat/completions").mock(
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
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "calculator",
                    "arguments": '{"expression":"2+2"}',
                },
            }
        ]
        respx_mock.post(f"{VLLM_HOST}/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json=_openai_response(
                    content="", model=model_id, tool_calls=tool_calls,
                ),
            )
        )
        result = engine.generate(
            [Message(role=Role.USER, content="What is 2+2?")],
            model=model_id,
            tools=[{"type": "function", "function": {"name": "calculator"}}],
        )
        assert "tool_calls" in result
        assert result["tool_calls"][0]["name"] == "calculator"
        assert result["tool_calls"][0]["id"] == "call_123"

    def test_generate_tool_fallback(self, respx_mock, model_id: str) -> None:
        """When tools cause a 400, engine retries without tools."""
        engine = _make_engine()
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            body = json.loads(request.content)
            if "tools" in body:
                return httpx.Response(400, json={"error": "tools not supported"})
            return httpx.Response(
                200, json=_openai_response(content="Fallback reply", model=model_id)
            )

        respx_mock.post(f"{VLLM_HOST}/v1/chat/completions").mock(
            side_effect=handler
        )
        result = engine.generate(
            [Message(role=Role.USER, content="Hello")],
            model=model_id,
            tools=[{"type": "function", "function": {"name": "calc"}}],
        )
        assert result["content"] == "Fallback reply"
        assert call_count == 2

    def test_generate_streaming(self, respx_mock, model_id: str) -> None:
        """SSE stream yields content tokens."""
        engine = _make_engine()
        sse = (
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n'
            'data: {"choices":[{"delta":{"content":" world"}}]}\n'
            "data: [DONE]\n"
        )
        respx_mock.post(f"{VLLM_HOST}/v1/chat/completions").mock(
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
        assert tokens == ["Hello", " world"]


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


class TestVLLMModelDiscovery:
    def test_list_models(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.get(f"{VLLM_HOST}/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": m} for m in NEW_MODELS]},
            )
        )
        models = engine.list_models()
        assert models == NEW_MODELS

    def test_health_check_healthy(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.get(f"{VLLM_HOST}/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        assert engine.health() is True

    def test_health_check_unhealthy(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.get(f"{VLLM_HOST}/v1/models").mock(
            side_effect=httpx.ConnectError("refused")
        )
        assert engine.health() is False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestVLLMErrors:
    def test_connection_refused(self) -> None:
        """No mock — ConnectError raises EngineConnectionError."""
        engine = VLLMEngine(host="http://localhost:19999")
        with respx.mock:
            respx.post("http://localhost:19999/v1/chat/completions").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )

    def test_invalid_model_404(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.post(f"{VLLM_HOST}/v1/chat/completions").mock(
            return_value=httpx.Response(404, json={"error": "model not found"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            engine.generate(
                [Message(role=Role.USER, content="Hi")], model="nonexistent"
            )

    def test_timeout_raises_connection_error(self) -> None:
        engine = _make_engine()
        with respx.mock:
            respx.post(f"{VLLM_HOST}/v1/chat/completions").mock(
                side_effect=httpx.TimeoutException("timed out")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )
