"""Tests for the Cloud engine backend."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import (
    CloudEngine,
    _is_codex_model,
    estimate_cost,
)


class TestEstimateCost:
    def test_known_model(self) -> None:
        cost = estimate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert cost == pytest.approx(12.50)  # 2.50 + 10.00

    def test_unknown_model(self) -> None:
        assert estimate_cost("unknown-model", 100, 100) == 0.0

    def test_prefix_match(self) -> None:
        cost = estimate_cost("gpt-4o-2024-01-01", 1_000_000, 0)
        assert cost == pytest.approx(2.50)


class TestCloudEngineHealth:
    def test_health_no_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        EngineRegistry.register_value("cloud", CloudEngine)
        engine = CloudEngine()
        assert engine.health() is False

    def test_health_with_openai_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        # Mock the openai import
        fake_openai = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"openai": fake_openai}):
            EngineRegistry.register_value("cloud", CloudEngine)
            engine = CloudEngine()
        assert engine.health() is True


class TestCloudEngineListModels:
    def test_list_models_no_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        EngineRegistry.register_value("cloud", CloudEngine)
        engine = CloudEngine()
        assert engine.list_models() == []


class TestCloudEngineGenerate:
    def test_generate_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        fake_usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        )
        fake_choice = SimpleNamespace(
            message=SimpleNamespace(content="Hello!"),
            finish_reason="stop",
        )
        fake_resp = SimpleNamespace(
            choices=[fake_choice], usage=fake_usage, model="gpt-4o"
        )

        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = fake_resp

        EngineRegistry.register_value("cloud", CloudEngine)
        engine = CloudEngine()
        engine._openai_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="gpt-4o"
        )
        assert result["content"] == "Hello!"
        assert result["usage"]["prompt_tokens"] == 10

    def test_generate_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        fake_usage = SimpleNamespace(input_tokens=12, output_tokens=8)
        fake_content = SimpleNamespace(text="Greetings!")
        fake_resp = SimpleNamespace(
            content=[fake_content],
            usage=fake_usage,
            model="claude-sonnet-4-20250514",
            stop_reason="end_turn",
        )

        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = fake_resp

        EngineRegistry.register_value("cloud", CloudEngine)
        engine = CloudEngine()
        engine._anthropic_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model="claude-sonnet-4-20250514",
        )
        assert result["content"] == "Greetings!"
        assert result["usage"]["prompt_tokens"] == 12
        assert result["usage"]["completion_tokens"] == 8


class TestOpenAIUnsupportedTemperatureRetry:
    """Regression for #426.

    Some OpenAI models (e.g. gpt-5) reject a non-default ``temperature``
    with HTTP 400 ``unsupported_value``. A brand-new install defaults to
    such a model, so the very first prompt 400s. The engine must detect
    this specific error and retry once without ``temperature``.
    """

    def _fake_resp(self):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="gpt-5",
        )

    def test_retries_without_temperature_on_unsupported_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        calls: list[dict] = []
        err = Exception(
            "Error code: 400 - {'error': {'message': \"Unsupported value: "
            "'temperature' does not support 0.7 with this model. Only the "
            "default (1) value is supported.\", 'type': "
            "'invalid_request_error', 'param': 'temperature', 'code': "
            "'unsupported_value'}}"
        )

        def create(**kwargs):
            calls.append(kwargs)
            if "temperature" in kwargs:
                raise err
            return self._fake_resp()

        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.side_effect = create

        EngineRegistry.register_value("cloud", CloudEngine)
        engine = CloudEngine()
        engine._openai_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model="gpt-5",
            temperature=0.7,
        )
        # The call succeeded via the retry.
        assert result["content"] == "ok"
        # First attempt sent temperature, retry dropped it.
        assert len(calls) == 2
        assert "temperature" in calls[0]
        assert "temperature" not in calls[1]

    def test_unrelated_400_is_not_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        calls: list[dict] = []
        err = Exception("Error code: 400 - context_length_exceeded")

        def create(**kwargs):
            calls.append(kwargs)
            raise err

        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.side_effect = create

        EngineRegistry.register_value("cloud", CloudEngine)
        engine = CloudEngine()
        engine._openai_client = fake_client

        with pytest.raises(Exception):  # noqa: B017 - re-raised unchanged
            engine.generate(
                [Message(role=Role.USER, content="Hi")],
                model="gpt-4o",
                temperature=0.7,
            )
        # No temperature-retry for an unrelated 400 — exactly one attempt.
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Codex provider support (OpenAI Responses API)
# ---------------------------------------------------------------------------


class TestCodexModelDetection:
    def test_is_codex_model(self) -> None:
        assert _is_codex_model("codex/gpt-4o") is True
        assert _is_codex_model("codex/gpt-5-mini") is True
        assert _is_codex_model("codex/gpt-5-mini-2025-08-07") is True

    def test_not_codex_model(self) -> None:
        assert _is_codex_model("gpt-4o") is False
        assert _is_codex_model("openrouter/openai/gpt-4o") is False


class TestCodexClientInit:
    def test_health_with_codex_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_CODEX_API_KEY", "test-token")
        engine = CloudEngine()
        assert engine.health() is True
        assert engine._codex_client is not None
        assert engine._codex_client["token"] == "test-token"
        assert "responses" in engine._codex_client["url"]

    def test_custom_codex_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_CODEX_API_KEY", "test-token")
        monkeypatch.setenv("OPENAI_CODEX_BASE_URL", "http://localhost:9999")
        engine = CloudEngine()
        assert engine._codex_client["url"] == "http://localhost:9999/responses"

    def test_list_models_includes_codex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_CODEX_API_KEY", "test-token")
        engine = CloudEngine()
        models = engine.list_models()
        assert "codex/gpt-4o" in models
        assert "codex/gpt-5-mini" in models
        assert "codex/gpt-5-mini-2025-08-07" in models

    def test_no_codex_key_means_no_codex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_CODEX_API_KEY", raising=False)
        engine = CloudEngine()
        assert engine._codex_client is None
        assert "codex/gpt-4o" not in engine.list_models()


class TestCodexGenerate:
    def test_generate_codex_uses_responses_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        fake_response = mock.MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "output_text": "Codex response!",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        fake_response.raise_for_status = mock.MagicMock()

        engine = CloudEngine()
        engine._codex_client = {
            "token": "test-token",
            "url": "https://api.openai.com/v1/responses",
        }

        with mock.patch(
            "openjarvis.engine.cloud.httpx.post",
            return_value=fake_response,
        ) as mock_post:
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")],
                model="codex/gpt-5-mini-2025-08-07",
            )

        assert result["content"] == "Codex response!"
        assert result["model"] == "gpt-5-mini-2025-08-07"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5

        # Verify correct Responses API request format
        call_kwargs = mock_post.call_args
        sent_body = call_kwargs.kwargs["json"]
        assert sent_body["model"] == "gpt-5-mini-2025-08-07"
        assert sent_body["stream"] is False
        assert "input" in sent_body  # Responses API format
        assert "messages" not in sent_body  # NOT chat completions

        # Verify correct headers
        sent_headers = call_kwargs.kwargs["headers"]
        assert sent_headers["Authorization"] == "Bearer test-token"
        assert sent_headers["OpenAI-Beta"] == "responses=experimental"

    def test_generate_codex_extracts_from_output_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fallback extraction from output[].content[] blocks."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        fake_response = mock.MagicMock()
        fake_response.json.return_value = {
            "output": [{"content": [{"type": "output_text", "text": "From blocks!"}]}],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }
        fake_response.raise_for_status = mock.MagicMock()

        engine = CloudEngine()
        engine._codex_client = {
            "token": "t",
            "url": "https://api.openai.com/v1/responses",
        }

        with mock.patch(
            "openjarvis.engine.cloud.httpx.post",
            return_value=fake_response,
        ):
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")],
                model="codex/gpt-4o",
            )
        assert result["content"] == "From blocks!"

    def test_generate_codex_passes_system_as_instructions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        fake_response = mock.MagicMock()
        fake_response.json.return_value = {
            "output_text": "ok",
            "usage": {},
        }
        fake_response.raise_for_status = mock.MagicMock()

        engine = CloudEngine()
        engine._codex_client = {
            "token": "t",
            "url": "https://api.openai.com/v1/responses",
        }

        with mock.patch(
            "openjarvis.engine.cloud.httpx.post",
            return_value=fake_response,
        ) as mock_post:
            engine.generate(
                [
                    Message(role=Role.SYSTEM, content="Be helpful"),
                    Message(role=Role.USER, content="Hi"),
                ],
                model="codex/gpt-4o",
            )

        sent_body = mock_post.call_args.kwargs["json"]
        assert sent_body["instructions"] == "Be helpful"
        # System message should NOT appear in input messages
        roles = [m["role"] for m in sent_body["input"]]
        assert "system" not in roles

    def test_codex_close(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        engine = CloudEngine()
        engine._codex_client = {"token": "t", "url": "http://test"}
        engine.close()
        assert engine._codex_client is None


class TestOpenRouterToolForwarding:
    """Regression for #511: the OpenRouter engine must forward tools/tool_choice
    to the (OpenAI-compatible) API and parse tool_calls back out of the response.
    Pre-fix, both were dropped, silently breaking function-calling via OpenRouter.
    """

    def test_generate_forwards_tools_and_parses_tool_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        fake_tc = SimpleNamespace(
            id="call_1",
            type="function",
            function=SimpleNamespace(name="get_weather", arguments='{"city": "NYC"}'),
        )
        fake_choice = SimpleNamespace(
            message=SimpleNamespace(content=None, tool_calls=[fake_tc]),
            finish_reason="tool_calls",
        )
        fake_resp = SimpleNamespace(
            choices=[fake_choice],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            model="openai/gpt-4o",
        )
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = fake_resp

        EngineRegistry.register_value("cloud", CloudEngine)
        engine = CloudEngine()
        engine._openrouter_client = fake_client

        tools = [
            {
                "type": "function",
                "function": {"name": "get_weather", "parameters": {}},
            }
        ]
        result = engine.generate(
            [Message(role=Role.USER, content="weather in NYC?")],
            model="openrouter/openai/gpt-4o",
            tools=tools,
            tool_choice="auto",
        )

        # tools / tool_choice are forwarded to the API call
        sent = fake_client.chat.completions.create.call_args.kwargs
        assert sent["tools"] == tools
        assert sent["tool_choice"] == "auto"

        # tool_calls from the response are parsed back into the result
        assert result["tool_calls"][0]["id"] == "call_1"
        assert result["tool_calls"][0]["function"]["name"] == "get_weather"
        assert result["tool_calls"][0]["function"]["arguments"] == '{"city": "NYC"}'
