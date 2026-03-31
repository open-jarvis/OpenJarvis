"""Tests for the Lemonade engine backend.

Validates that the ``/v1`` prefix is used correctly for models listing
and chat completions.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.openai_compat_engines import LemonadeEngine


@pytest.fixture()
def engine() -> LemonadeEngine:
    EngineRegistry.register_value("lemonade", LemonadeEngine)
    return LemonadeEngine(host="http://testhost:8000")


class TestLemonadeEngineBasics:
    def test_engine_id(self) -> None:
        assert LemonadeEngine.engine_id == "lemonade"

    def test_default_host(self) -> None:
        assert LemonadeEngine._default_host == "http://localhost:8000"

    def test_api_prefix(self) -> None:
        assert LemonadeEngine._api_prefix == "/v1"

    def test_registry_registration(self) -> None:
        EngineRegistry.register_value("lemonade", LemonadeEngine)
        assert EngineRegistry.get("lemonade") is LemonadeEngine


class TestLemonadeGenerate:
    def test_generate_uses_v1_prefix(self, engine: LemonadeEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:8000/v1/chat/completions").mock(
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
                        "model": "Qwen3-4B-Instruct",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="Qwen3-4B-Instruct"
            )
        assert result["content"] == "Hello!"
        assert result["usage"]["total_tokens"] == 7

    def test_generate_connection_error(self, engine: LemonadeEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:8000/v1/chat/completions").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")],
                    model="Qwen3-4B-Instruct",
                )


class TestLemonadeHealth:
    def test_health_true(self, engine: LemonadeEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8000/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            assert engine.health() is True

    def test_health_false(self, engine: LemonadeEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8000/v1/models").mock(
                side_effect=httpx.ConnectError("refused")
            )
            assert engine.health() is False


class TestLemonadeListModels:
    def test_list_models_uses_v1_prefix(self, engine: LemonadeEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8000/v1/models").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": "Qwen3-4B-Instruct"},
                            {"id": "Llama-3.1-8B"},
                        ]
                    },
                )
            )
            assert engine.list_models() == ["Qwen3-4B-Instruct", "Llama-3.1-8B"]
