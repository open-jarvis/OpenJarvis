"""Tests for the OpenAI-compatible engine base (covers vLLM + llama.cpp)."""

from __future__ import annotations

import httpx
import pytest
import respx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.openai_compat_engines import VLLMEngine


@pytest.fixture()
def engine() -> VLLMEngine:
    EngineRegistry.register_value("vllm", VLLMEngine)
    return VLLMEngine(host="http://testhost:8000")


class TestOpenAICompatGenerate:
    def test_generate_returns_content(self, engine: VLLMEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:8000/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {"content": "4"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 8,
                            "completion_tokens": 1,
                            "total_tokens": 9,
                        },
                        "model": "qwen3:8b",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="2+2")], model="qwen3:8b"
            )
        assert result["content"] == "4"
        assert result["usage"]["total_tokens"] == 9

    def test_empty_choices_returns_graceful_fallback(
        self,
        engine: VLLMEngine,
    ) -> None:
        with respx.mock:
            respx.post("http://testhost:8000/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 5,
                            "completion_tokens": 0,
                            "total_tokens": 5,
                        },
                        "model": "test",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="hi")],
                model="test",
            )
        assert result["content"] == ""
        assert result["finish_reason"] == "error"

    def test_generate_connection_error(self, engine: VLLMEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:8000/v1/chat/completions").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )


class TestOpenAICompatListModels:
    def test_list_models(self, engine: VLLMEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8000/v1/models").mock(
                return_value=httpx.Response(
                    200,
                    json={"data": [{"id": "model-a"}, {"id": "model-b"}]},
                )
            )
            assert engine.list_models() == ["model-a", "model-b"]


class TestOpenAICompatHealth:
    def test_health_true(self, engine: VLLMEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8000/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            assert engine.health() is True

    def test_health_false(self, engine: VLLMEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8000/v1/models").mock(
                side_effect=httpx.ConnectError("refused")
            )
            assert engine.health() is False


class TestOpenAICompatStream:
    @pytest.mark.asyncio
    async def test_stream_sse(self, engine: VLLMEngine) -> None:
        sse_lines = (
            'data: {"choices":[{"delta":{"content":"Hi"}}]}\n'
            'data: {"choices":[{"delta":{"content":" there"}}]}\n'
            "data: [DONE]\n"
        )
        with respx.mock:
            respx.post("http://testhost:8000/v1/chat/completions").mock(
                return_value=httpx.Response(200, text=sse_lines)
            )
            tokens = []
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hello")], model="m"
            ):
                tokens.append(tok)
        assert tokens == ["Hi", " there"]
