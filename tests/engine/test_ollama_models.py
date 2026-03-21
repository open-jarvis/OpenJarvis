"""Tests for Ollama engine with extended local model set."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.ollama import OllamaEngine

OLLAMA_HOST = "http://testhost:11434"
NEW_MODELS = ["gpt-oss:120b", "qwen3:8b", "glm-4.7-flash", "trinity-mini"]


def _make_engine() -> OllamaEngine:
    if not EngineRegistry.contains("ollama"):
        EngineRegistry.register_value("ollama", OllamaEngine)
    return OllamaEngine(host=OLLAMA_HOST)


def _ollama_response(
    content: str = "Hello!",
    model: str = "qwen3:8b",
    prompt_eval_count: int = 10,
    eval_count: int = 5,
    tool_calls: list | None = None,
) -> dict:
    """Build an Ollama-format response dict."""
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    result: dict = {
        "message": message,
        "model": model,
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "done": True,
    }
    return result


# ---------------------------------------------------------------------------
# Generate tests (parametrized over new models)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", NEW_MODELS)
class TestOllamaGenerate:
    def test_generate_basic(self, respx_mock, model_id: str) -> None:
        engine = _make_engine()
        respx_mock.post(f"{OLLAMA_HOST}/api/chat").mock(
            return_value=httpx.Response(
                200, json=_ollama_response(content="Test reply", model=model_id)
            )
        )
        result = engine.generate(
            [Message(role=Role.USER, content="Hello")], model=model_id
        )
        assert result["content"] == "Test reply"
        assert result["model"] == model_id
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["usage"]["total_tokens"] == 15

    def test_generate_with_tools(self, respx_mock, model_id: str) -> None:
        engine = _make_engine()
        tool_calls = [
            {
                "function": {
                    "name": "calculator",
                    "arguments": '{"expression":"2+2"}',
                },
            }
        ]
        respx_mock.post(f"{OLLAMA_HOST}/api/chat").mock(
            return_value=httpx.Response(
                200,
                json=_ollama_response(
                    content="",
                    model=model_id,
                    tool_calls=tool_calls,
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
        assert result["tool_calls"][0]["id"] == "call_0"

    def test_generate_with_multiple_tool_calls(self, respx_mock, model_id: str) -> None:
        engine = _make_engine()
        tool_calls = [
            {"function": {"name": "tool_a", "arguments": "{}"}},
            {"function": {"name": "tool_b", "arguments": "{}"}},
        ]
        respx_mock.post(f"{OLLAMA_HOST}/api/chat").mock(
            return_value=httpx.Response(
                200,
                json=_ollama_response(
                    content="",
                    model=model_id,
                    tool_calls=tool_calls,
                ),
            )
        )
        result = engine.generate(
            [Message(role=Role.USER, content="Use tools")], model=model_id
        )
        assert len(result["tool_calls"]) == 2
        assert result["tool_calls"][0]["name"] == "tool_a"
        assert result["tool_calls"][1]["name"] == "tool_b"

    def test_generate_streaming(self, respx_mock, model_id: str) -> None:
        engine = _make_engine()
        lines = [
            json.dumps({"message": {"content": "Hello"}, "done": False}),
            json.dumps({"message": {"content": " world"}, "done": True}),
        ]
        body = "\n".join(lines)
        respx_mock.post(f"{OLLAMA_HOST}/api/chat").mock(
            return_value=httpx.Response(200, text=body)
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
        assert "Hello" in tokens


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


class TestOllamaModelDiscovery:
    def test_list_models(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.get(f"{OLLAMA_HOST}/api/tags").mock(
            return_value=httpx.Response(
                200,
                json={"models": [{"name": m} for m in NEW_MODELS]},
            )
        )
        models = engine.list_models()
        assert models == NEW_MODELS

    def test_list_models_empty(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.get(f"{OLLAMA_HOST}/api/tags").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        assert engine.list_models() == []

    def test_list_models_connection_error(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.get(f"{OLLAMA_HOST}/api/tags").mock(
            side_effect=httpx.ConnectError("refused")
        )
        assert engine.list_models() == []

    def test_health_healthy(self, respx_mock) -> None:
        engine = _make_engine()
        respx_mock.get(f"{OLLAMA_HOST}/api/tags").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        assert engine.health() is True

    def test_health_unhealthy(self) -> None:
        engine = _make_engine()
        with respx.mock:
            respx.get(f"{OLLAMA_HOST}/api/tags").mock(
                side_effect=httpx.ConnectError("refused")
            )
            assert engine.health() is False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestOllamaErrors:
    def test_connection_refused(self) -> None:
        engine = _make_engine()
        with respx.mock:
            respx.post(f"{OLLAMA_HOST}/api/chat").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )

    def test_timeout_raises_connection_error(self) -> None:
        engine = _make_engine()
        with respx.mock:
            respx.post(f"{OLLAMA_HOST}/api/chat").mock(
                side_effect=httpx.TimeoutException("timed out")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )

    def test_tools_payload_included(self, respx_mock) -> None:
        """Tools are included in the Ollama payload when provided."""
        engine = _make_engine()
        captured = {}

        def capture(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ollama_response(content="ok"))

        respx_mock.post(f"{OLLAMA_HOST}/api/chat").mock(side_effect=capture)
        engine.generate(
            [Message(role=Role.USER, content="Hello")],
            model="qwen3:8b",
            tools=[{"type": "function", "function": {"name": "calc"}}],
        )
        assert "tools" in captured["body"]

    def test_no_tools_no_tools_key(self, respx_mock) -> None:
        """Without tools kwarg, payload has no tools key."""
        engine = _make_engine()
        captured = {}

        def capture(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ollama_response(content="ok"))

        respx_mock.post(f"{OLLAMA_HOST}/api/chat").mock(side_effect=capture)
        engine.generate([Message(role=Role.USER, content="Hello")], model="qwen3:8b")
        assert "tools" not in captured["body"]
