"""Cross-product parametrized tests: engine x scenario."""

from __future__ import annotations

import httpx
import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.ollama import OllamaEngine
from openjarvis.engine.openai_compat_engines import VLLMEngine

ENGINES_AND_HOSTS = [
    ("vllm", "http://testhost:8000"),
    ("ollama", "http://testhost:11434"),
]

MODELS = ["gpt-oss:120b", "qwen3:8b", "glm-4.7-flash", "trinity-mini"]


def _create_engine(engine_key: str, host: str):
    """Instantiate the right engine class for the given key."""
    if engine_key == "vllm":
        if not EngineRegistry.contains("vllm"):
            EngineRegistry.register_value("vllm", VLLMEngine)
        return VLLMEngine(host=host)
    elif engine_key == "ollama":
        if not EngineRegistry.contains("ollama"):
            EngineRegistry.register_value("ollama", OllamaEngine)
        return OllamaEngine(host=host)
    else:
        raise ValueError(f"Unknown engine: {engine_key}")


def _mock_simple_chat(respx_mock, engine_key: str, host: str, model: str):
    """Set up mock for a simple chat response."""
    if engine_key == "vllm":
        respx_mock.post(f"{host}/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [
                    {"message": {"content": "Hello!"}, "finish_reason": "stop"},
                ],
                "usage": {
                    "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                },
                "model": model,
            })
        )
    elif engine_key == "ollama":
        respx_mock.post(f"{host}/api/chat").mock(
            return_value=httpx.Response(200, json={
                "message": {"role": "assistant", "content": "Hello!"},
                "model": model,
                "prompt_eval_count": 10,
                "eval_count": 5,
                "done": True,
            })
        )


def _mock_tool_call(respx_mock, engine_key: str, host: str, model: str):
    """Set up mock for a tool-call response."""
    if engine_key == "vllm":
        respx_mock.post(f"{host}/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [{
                    "message": {
                        "content": "",
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "calculator", "arguments": '{"x":1}'},
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {
                    "prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18,
                },
                "model": model,
            })
        )
    elif engine_key == "ollama":
        respx_mock.post(f"{host}/api/chat").mock(
            return_value=httpx.Response(200, json={
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "function": {"name": "calculator", "arguments": '{"x":1}'},
                    }],
                },
                "model": model,
                "prompt_eval_count": 10,
                "eval_count": 8,
                "done": True,
            })
        )


def _mock_error(respx_mock, engine_key: str, host: str):
    """Set up mock for connection error."""
    if engine_key == "vllm":
        respx_mock.post(f"{host}/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("refused")
        )
    elif engine_key == "ollama":
        respx_mock.post(f"{host}/api/chat").mock(
            side_effect=httpx.ConnectError("refused")
        )


# ---------------------------------------------------------------------------
# Cross-product: engine x scenario
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_key,host", ENGINES_AND_HOSTS)
class TestEngineScenarios:
    def test_simple_chat(self, respx_mock, engine_key: str, host: str) -> None:
        engine = _create_engine(engine_key, host)
        _mock_simple_chat(respx_mock, engine_key, host, "qwen3:8b")
        result = engine.generate(
            [Message(role=Role.USER, content="Hello")], model="qwen3:8b"
        )
        assert result["content"] == "Hello!"
        assert result["usage"]["prompt_tokens"] == 10

    def test_tool_call(self, respx_mock, engine_key: str, host: str) -> None:
        engine = _create_engine(engine_key, host)
        _mock_tool_call(respx_mock, engine_key, host, "qwen3:8b")
        result = engine.generate(
            [Message(role=Role.USER, content="Calculate")],
            model="qwen3:8b",
            tools=[{"type": "function", "function": {"name": "calculator"}}],
        )
        assert "tool_calls" in result
        assert result["tool_calls"][0]["name"] == "calculator"

    def test_error_handling(self, respx_mock, engine_key: str, host: str) -> None:
        engine = _create_engine(engine_key, host)
        _mock_error(respx_mock, engine_key, host)
        with pytest.raises(EngineConnectionError):
            engine.generate(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            )


# ---------------------------------------------------------------------------
# Cross-product: engine x model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_key,host", ENGINES_AND_HOSTS)
@pytest.mark.parametrize("model_id", MODELS)
class TestEngineModelMatrix:
    def test_generate_with_model(
        self, respx_mock, engine_key: str, host: str, model_id: str,
    ) -> None:
        engine = _create_engine(engine_key, host)
        _mock_simple_chat(respx_mock, engine_key, host, model_id)
        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model=model_id
        )
        assert result["content"] == "Hello!"
        assert result["model"] == model_id


# ---------------------------------------------------------------------------
# Health checks across engines
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_key,host", ENGINES_AND_HOSTS)
class TestEngineHealth:
    def test_health_true(self, respx_mock, engine_key: str, host: str) -> None:
        engine = _create_engine(engine_key, host)
        if engine_key == "vllm":
            respx_mock.get(f"{host}/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
        elif engine_key == "ollama":
            respx_mock.get(f"{host}/api/tags").mock(
                return_value=httpx.Response(200, json={"models": []})
            )
        assert engine.health() is True

    def test_health_false(self, respx_mock, engine_key: str, host: str) -> None:
        engine = _create_engine(engine_key, host)
        if engine_key == "vllm":
            respx_mock.get(f"{host}/v1/models").mock(
                side_effect=httpx.ConnectError("refused")
            )
        elif engine_key == "ollama":
            respx_mock.get(f"{host}/api/tags").mock(
                side_effect=httpx.ConnectError("refused")
            )
        assert engine.health() is False
