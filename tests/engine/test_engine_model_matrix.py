"""Cross-product parametrized tests: engine x scenario."""

from __future__ import annotations

import httpx
import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.ollama import OllamaEngine
from openjarvis.engine.openai_compat_engines import (
    AppleFmEngine,
    ExoEngine,
    LemonadeEngine,
    LlamaCppEngine,
    LMStudioEngine,
    MLXEngine,
    NexaEngine,
    SGLangEngine,
    UzuEngine,
    VLLMEngine,
)

_OPENAI_COMPAT_ENGINES = [
    ("vllm", "http://testhost:8000", VLLMEngine),
    ("sglang", "http://testhost:30000", SGLangEngine),
    ("llamacpp", "http://testhost:8080", LlamaCppEngine),
    ("mlx", "http://testhost:8081", MLXEngine),
    ("lmstudio", "http://testhost:1234", LMStudioEngine),
    ("exo", "http://testhost:52415", ExoEngine),
    ("nexa", "http://testhost:18181", NexaEngine),
    ("uzu", "http://testhost:8000", UzuEngine),
    ("apple_fm", "http://testhost:8079", AppleFmEngine),
    ("lemonade", "http://testhost:8000", LemonadeEngine),
]


def _api_prefix(engine_key: str) -> str:
    """Return the API prefix for an engine."""
    if engine_key == "uzu":
        return ""
    if engine_key == "lemonade":
        return "/v1"
    return "/v1"


ENGINES_AND_HOSTS = [(key, host) for key, host, _ in _OPENAI_COMPAT_ENGINES] + [
    ("ollama", "http://testhost:11434"),
]

MODELS = [
    "gpt-oss:120b",
    "qwen3:8b",
    "glm-4.7-flash",
    "trinity-mini",
    "qwen3.5:35b-a3b",
    "LiquidAI/LFM2.5-1.2B-Instruct-GGUF",
]

_ENGINE_CLASSES = {key: cls for key, _, cls in _OPENAI_COMPAT_ENGINES}
_ENGINE_CLASSES["ollama"] = OllamaEngine


def _create_engine(engine_key: str, host: str):
    """Instantiate the right engine class for the given key."""
    cls = _ENGINE_CLASSES.get(engine_key)
    if cls is None:
        raise ValueError(f"Unknown engine: {engine_key}")
    if not EngineRegistry.contains(engine_key):
        EngineRegistry.register_value(engine_key, cls)
    return cls(host=host)


def _mock_simple_chat(respx_mock, engine_key: str, host: str, model: str):
    """Set up mock for a simple chat response."""
    if engine_key == "ollama":
        respx_mock.post(f"{host}/api/chat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": "Hello!"},
                    "model": model,
                    "prompt_eval_count": 10,
                    "eval_count": 5,
                    "done": True,
                },
            )
        )
    else:  # All OpenAI-compatible engines
        prefix = _api_prefix(engine_key)
        respx_mock.post(f"{host}{prefix}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "Hello!"}, "finish_reason": "stop"},
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "model": model,
                },
            )
        )


def _mock_tool_call(respx_mock, engine_key: str, host: str, model: str):
    """Set up mock for a tool-call response."""
    if engine_key == "ollama":
        respx_mock.post(f"{host}/api/chat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "calculator",
                                    "arguments": '{"x":1}',
                                },
                            }
                        ],
                    },
                    "model": model,
                    "prompt_eval_count": 10,
                    "eval_count": 8,
                    "done": True,
                },
            )
        )
    else:  # All OpenAI-compatible engines
        prefix = _api_prefix(engine_key)
        respx_mock.post(f"{host}{prefix}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "calculator",
                                            "arguments": '{"x":1}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 8,
                        "total_tokens": 18,
                    },
                    "model": model,
                },
            )
        )


def _mock_error(respx_mock, engine_key: str, host: str):
    """Set up mock for connection error."""
    if engine_key == "ollama":
        respx_mock.post(f"{host}/api/chat").mock(
            side_effect=httpx.ConnectError("refused")
        )
    else:  # All OpenAI-compatible engines
        prefix = _api_prefix(engine_key)
        respx_mock.post(f"{host}{prefix}/chat/completions").mock(
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
            engine.generate([Message(role=Role.USER, content="Hi")], model="qwen3:8b")


# ---------------------------------------------------------------------------
# Cross-product: engine x model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_key,host", ENGINES_AND_HOSTS)
@pytest.mark.parametrize("model_id", MODELS)
class TestEngineModelMatrix:
    def test_generate_with_model(
        self,
        respx_mock,
        engine_key: str,
        host: str,
        model_id: str,
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
        if engine_key == "ollama":
            respx_mock.get(f"{host}/api/tags").mock(
                return_value=httpx.Response(200, json={"models": []})
            )
        else:  # All OpenAI-compatible engines
            prefix = _api_prefix(engine_key)
            respx_mock.get(f"{host}{prefix}/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
        assert engine.health() is True

    def test_health_false(self, respx_mock, engine_key: str, host: str) -> None:
        engine = _create_engine(engine_key, host)
        if engine_key == "ollama":
            respx_mock.get(f"{host}/api/tags").mock(
                side_effect=httpx.ConnectError("refused")
            )
        else:  # All OpenAI-compatible engines
            prefix = _api_prefix(engine_key)
            respx_mock.get(f"{host}{prefix}/models").mock(
                side_effect=httpx.ConnectError("refused")
            )
        assert engine.health() is False
