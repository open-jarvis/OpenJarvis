"""Tests for the LM Studio engine backend."""

from __future__ import annotations

import httpx
import pytest
import respx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.openai_compat_engines import LMStudioEngine


@pytest.fixture()
def engine() -> LMStudioEngine:
    EngineRegistry.register_value("lmstudio", LMStudioEngine)
    return LMStudioEngine(host="http://testhost:1234")


class TestLMStudioEngineBasics:
    def test_engine_id(self) -> None:
        assert LMStudioEngine.engine_id == "lmstudio"

    def test_default_host(self) -> None:
        assert LMStudioEngine._default_host == "http://localhost:1234"

    def test_registry_registration(self) -> None:
        EngineRegistry.register_value("lmstudio", LMStudioEngine)
        assert EngineRegistry.get("lmstudio") is LMStudioEngine


class TestLMStudioGenerate:
    def test_generate_returns_content(self, engine: LMStudioEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:1234/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {"content": "Hello!"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 5,
                            "completion_tokens": 2,
                            "total_tokens": 7,
                        },
                        "model": "llama-3.1-8b",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="llama-3.1-8b"
            )
        assert result["content"] == "Hello!"
        assert result["usage"]["total_tokens"] == 7

    def test_generate_connection_error(self, engine: LMStudioEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:1234/v1/chat/completions").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="llama-3.1-8b"
                )


class TestLMStudioHealth:
    def test_health_true(self, engine: LMStudioEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:1234/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            assert engine.health() is True

    def test_health_false(self, engine: LMStudioEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:1234/v1/models").mock(
                side_effect=httpx.ConnectError("refused")
            )
            assert engine.health() is False


class TestLMStudioListModels:
    def test_list_models(self, engine: LMStudioEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:1234/v1/models").mock(
                return_value=httpx.Response(
                    200,
                    json={"data": [{"id": "llama-3.1-8b"}, {"id": "phi-3-mini"}]},
                )
            )
            assert engine.list_models() == ["llama-3.1-8b", "phi-3-mini"]
