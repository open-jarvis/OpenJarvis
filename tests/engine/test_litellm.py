"""Tests for the LiteLLM engine backend."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine.litellm import LiteLLMEngine


class TestLiteLLMEngineHealth:
    def test_health_importable(self) -> None:
        fake_litellm = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"litellm": fake_litellm}):
            engine = LiteLLMEngine()
            assert engine.health() is True

    def test_health_not_importable(self) -> None:
        with mock.patch.dict("sys.modules", {"litellm": None}):
            engine = LiteLLMEngine()
            assert engine.health() is False


class TestLiteLLMEngineGenerate:
    def test_generate(self) -> None:
        fake_usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        )
        fake_choice = SimpleNamespace(
            message=SimpleNamespace(content="Hello!", tool_calls=None),
            finish_reason="stop",
        )
        fake_resp = SimpleNamespace(
            choices=[fake_choice], usage=fake_usage, model="gpt-4o"
        )

        fake_litellm = mock.MagicMock()
        fake_litellm.completion.return_value = fake_resp
        fake_litellm.completion_cost.return_value = 0.001

        with mock.patch.dict("sys.modules", {"litellm": fake_litellm}):
            engine = LiteLLMEngine()
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="gpt-4o"
            )

        assert result["content"] == "Hello!"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["usage"]["total_tokens"] == 15
        assert result["model"] == "gpt-4o"
        assert result["finish_reason"] == "stop"
        assert result["cost_usd"] == 0.001

    def test_generate_with_tools(self) -> None:
        fake_tool_call = SimpleNamespace(
            id="call_123",
            function=SimpleNamespace(
                name="calculator",
                arguments='{"expression": "2+2"}',
            ),
        )
        fake_usage = SimpleNamespace(
            prompt_tokens=20, completion_tokens=10, total_tokens=30
        )
        fake_choice = SimpleNamespace(
            message=SimpleNamespace(
                content="",
                tool_calls=[fake_tool_call],
            ),
            finish_reason="tool_calls",
        )
        fake_resp = SimpleNamespace(
            choices=[fake_choice], usage=fake_usage, model="gpt-4o"
        )

        fake_litellm = mock.MagicMock()
        fake_litellm.completion.return_value = fake_resp
        fake_litellm.completion_cost.return_value = 0.002

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "Evaluate math",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        with mock.patch.dict("sys.modules", {"litellm": fake_litellm}):
            engine = LiteLLMEngine()
            result = engine.generate(
                [Message(role=Role.USER, content="What is 2+2?")],
                model="gpt-4o",
                tools=tools,
            )

        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["id"] == "call_123"
        assert tc["name"] == "calculator"
        assert tc["arguments"] == '{"expression": "2+2"}'

    def test_generate_with_api_base(self) -> None:
        fake_usage = SimpleNamespace(
            prompt_tokens=5, completion_tokens=3, total_tokens=8
        )
        fake_choice = SimpleNamespace(
            message=SimpleNamespace(content="Hi!", tool_calls=None),
            finish_reason="stop",
        )
        fake_resp = SimpleNamespace(
            choices=[fake_choice], usage=fake_usage, model="custom-model"
        )

        fake_litellm = mock.MagicMock()
        fake_litellm.completion.return_value = fake_resp
        fake_litellm.completion_cost.return_value = 0.0

        with mock.patch.dict("sys.modules", {"litellm": fake_litellm}):
            engine = LiteLLMEngine(api_base="http://localhost:8080")
            engine.generate(
                [Message(role=Role.USER, content="Hi")], model="custom-model"
            )

        call_kwargs = fake_litellm.completion.call_args
        assert call_kwargs[1]["api_base"] == "http://localhost:8080"

    def test_generate_cost_error_fallback(self) -> None:
        fake_usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        )
        fake_choice = SimpleNamespace(
            message=SimpleNamespace(content="Hello!", tool_calls=None),
            finish_reason="stop",
        )
        fake_resp = SimpleNamespace(
            choices=[fake_choice], usage=fake_usage, model="unknown/model"
        )

        fake_litellm = mock.MagicMock()
        fake_litellm.completion.return_value = fake_resp
        fake_litellm.completion_cost.side_effect = Exception("Unknown model")

        with mock.patch.dict("sys.modules", {"litellm": fake_litellm}):
            engine = LiteLLMEngine()
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="unknown/model"
            )

        assert result["cost_usd"] == 0.0


class TestLiteLLMEngineStream:
    def test_stream(self) -> None:
        # stream() must use the ASYNC litellm entry point (acompletion): the
        # sync litellm.completion makes blocking network reads inside an
        # ``async def``, stalling the event loop between tokens.
        chunk1 = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="Hel"))]
        )
        chunk2 = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="lo!"))]
        )
        chunk3 = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]
        )

        async def _chunks():
            for c in (chunk1, chunk2, chunk3):
                yield c

        fake_litellm = mock.MagicMock()
        fake_litellm.acompletion = mock.AsyncMock(return_value=_chunks())

        with mock.patch.dict("sys.modules", {"litellm": fake_litellm}):
            engine = LiteLLMEngine()
            import asyncio

            async def collect() -> list[str]:
                tokens: list[str] = []
                async for token in engine.stream(
                    [Message(role=Role.USER, content="Hi")], model="gpt-4o"
                ):
                    tokens.append(token)
                return tokens

            tokens = asyncio.run(collect())

        assert tokens == ["Hel", "lo!"]
        fake_litellm.acompletion.assert_awaited_once()
        assert fake_litellm.completion.call_count == 0


class TestLiteLLMEngineListModels:
    def test_list_models_default(self) -> None:
        engine = LiteLLMEngine()
        assert engine.list_models() == []

    def test_list_models_with_default_model(self) -> None:
        engine = LiteLLMEngine(default_model="anthropic/claude-sonnet-4-20250514")
        assert engine.list_models() == ["anthropic/claude-sonnet-4-20250514"]


class TestLiteLLMEngineRegistry:
    def test_registry_key(self) -> None:
        EngineRegistry.register_value("litellm", LiteLLMEngine)
        assert EngineRegistry.contains("litellm")
        cls = EngineRegistry.get("litellm")
        assert cls is LiteLLMEngine
