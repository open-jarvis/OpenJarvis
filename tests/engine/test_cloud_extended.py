"""Extended cloud engine tests -- Gemini support and updated models."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.cloud import (
    _ANTHROPIC_MODELS,
    _GOOGLE_MODELS,
    _OPENAI_MODELS,
    PRICING,
    CloudEngine,
    _is_anthropic_model,
    _is_google_model,
    estimate_cost,
)


def _make_cloud_engine(monkeypatch: pytest.MonkeyPatch) -> CloudEngine:
    """Create a CloudEngine with all API keys cleared."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    if not EngineRegistry.contains("cloud"):
        EngineRegistry.register_value("cloud", CloudEngine)
    return CloudEngine()


def _fake_openai_response(
    content: str = "Hello!",
    model: str = "gpt-5-mini",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    tool_calls: list | None = None,
) -> SimpleNamespace:
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice], usage=usage, model=model)


def _fake_anthropic_response(
    content: str = "Hello!",
    model: str = "claude-opus-4-6",
    input_tokens: int = 12,
    output_tokens: int = 8,
) -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    text_block = SimpleNamespace(text=content)
    return SimpleNamespace(
        content=[text_block], usage=usage, model=model, stop_reason="end_turn"
    )


def _fake_gemini_response(
    content: str = "Hello!",
    prompt_tokens: int = 15,
    completion_tokens: int = 10,
) -> SimpleNamespace:
    usage = SimpleNamespace(
        prompt_token_count=prompt_tokens,
        candidates_token_count=completion_tokens,
    )
    return SimpleNamespace(text=content, usage_metadata=usage)


# ---------------------------------------------------------------------------
# OpenAI tests
# ---------------------------------------------------------------------------


class TestCloudOpenAI:
    def test_gpt_5_mini_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _fake_openai_response(
            content="I am GPT-5 Mini", model="gpt-5-mini"
        )
        engine._openai_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="gpt-5-mini"
        )
        assert result["content"] == "I am GPT-5 Mini"
        assert result["model"] == "gpt-5-mini"
        assert result["usage"]["prompt_tokens"] == 10

    def test_gpt_5_mini_cost_estimate(self) -> None:
        cost = estimate_cost("gpt-5-mini", 1_000_000, 1_000_000)
        # $0.25/M input + $2.00/M output = $2.25
        assert cost == pytest.approx(2.25)

    def test_gpt_5_mini_tool_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_tool_call = SimpleNamespace(
            id="call_xyz",
            type="function",
            function=SimpleNamespace(name="calc", arguments='{"x":1}'),
        )
        fake_resp = _fake_openai_response(content="", model="gpt-5-mini")
        fake_resp.choices[0].message.tool_calls = [fake_tool_call]
        fake_resp.choices[0].finish_reason = "tool_calls"

        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = fake_resp
        engine._openai_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Calculate")], model="gpt-5-mini"
        )
        assert result["content"] == ""
        # Verify flat tool_calls format
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["id"] == "call_xyz"
        assert tc["name"] == "calc"
        assert tc["arguments"] == '{"x":1}'

    def test_no_tool_calls_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _fake_openai_response(
            content="Just text", model="gpt-5-mini"
        )
        engine._openai_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="gpt-5-mini"
        )
        assert "tool_calls" not in result


# ---------------------------------------------------------------------------
# Anthropic tests
# ---------------------------------------------------------------------------


class TestCloudAnthropic:
    def test_claude_opus_4_6_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = _fake_anthropic_response(
            content="I am Opus 4.6", model="claude-opus-4-6"
        )
        engine._anthropic_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="claude-opus-4-6"
        )
        assert result["content"] == "I am Opus 4.6"
        assert result["model"] == "claude-opus-4-6"

    def test_claude_sonnet_4_6_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = _fake_anthropic_response(
            content="I am Sonnet 4.6", model="claude-sonnet-4-6"
        )
        engine._anthropic_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="claude-sonnet-4-6"
        )
        assert result["content"] == "I am Sonnet 4.6"

    def test_claude_haiku_4_5_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = _fake_anthropic_response(
            content="I am Haiku 4.5", model="claude-haiku-4-5"
        )
        engine._anthropic_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="claude-haiku-4-5"
        )
        assert result["content"] == "I am Haiku 4.5"

    def test_claude_cost_estimate(self) -> None:
        # claude-opus-4-6: $5.00/M in, $25.00/M out
        cost = estimate_cost("claude-opus-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(30.00)

        # claude-sonnet-4-6: $3.00/M in, $15.00/M out
        cost = estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.00)

        # claude-haiku-4-5: $1.00/M in, $5.00/M out
        cost = estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000)
        assert cost == pytest.approx(6.00)

    def test_anthropic_routing(self) -> None:
        assert _is_anthropic_model("claude-opus-4-6") is True
        assert _is_anthropic_model("claude-sonnet-4-6") is True
        assert _is_anthropic_model("claude-haiku-4-5") is True
        assert _is_anthropic_model("gpt-5-mini") is False
        assert _is_anthropic_model("gemini-3-pro") is False

    def test_anthropic_tool_use_extraction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anthropic tool_use blocks are extracted as flat tool_calls."""
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()

        # Build a response with a tool_use block
        text_block = SimpleNamespace(type="text", text="Let me calculate.")
        tool_block = SimpleNamespace(
            type="tool_use",
            id="toolu_123",
            name="calculator",
            input={"expression": "2+2"},
        )
        usage = SimpleNamespace(input_tokens=10, output_tokens=15)
        fake_resp = SimpleNamespace(
            content=[text_block, tool_block],
            usage=usage,
            model="claude-opus-4-6",
            stop_reason="tool_use",
        )
        fake_client.messages.create.return_value = fake_resp
        engine._anthropic_client = fake_client

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "Math",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        result = engine.generate(
            [Message(role=Role.USER, content="What is 2+2?")],
            model="claude-opus-4-6",
            tools=openai_tools,
        )
        assert result["content"] == "Let me calculate."
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["id"] == "toolu_123"
        assert tc["name"] == "calculator"
        assert '"expression"' in tc["arguments"]

    def test_anthropic_tools_converted_to_input_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tools passed to Anthropic use input_schema format."""
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = _fake_anthropic_response(
            content="Ok", model="claude-opus-4-6"
        )
        engine._anthropic_client = fake_client

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "calc",
                    "description": "Math",
                    "parameters": {
                        "type": "object",
                        "properties": {"x": {"type": "integer"}},
                    },
                },
            }
        ]

        engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model="claude-opus-4-6",
            tools=openai_tools,
        )
        call_kwargs = fake_client.messages.create.call_args
        passed_tools = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools")
        assert passed_tools is not None
        assert passed_tools[0]["name"] == "calc"
        assert "input_schema" in passed_tools[0]

    def test_anthropic_no_tool_calls_when_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = _fake_anthropic_response(
            content="Just text", model="claude-opus-4-6"
        )
        engine._anthropic_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="claude-opus-4-6"
        )
        assert "tool_calls" not in result

    def test_anthropic_system_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = _fake_anthropic_response(
            content="With system", model="claude-opus-4-6"
        )
        engine._anthropic_client = fake_client

        engine.generate(
            [
                Message(role=Role.SYSTEM, content="You are helpful"),
                Message(role=Role.USER, content="Hi"),
            ],
            model="claude-opus-4-6",
        )
        call_kwargs = fake_client.messages.create.call_args
        assert (
            call_kwargs.kwargs.get("system") == "You are helpful"
            or call_kwargs[1].get("system") == "You are helpful"
        )


# ---------------------------------------------------------------------------
# Gemini tests
# ---------------------------------------------------------------------------


class TestCloudGemini:
    def test_gemini_init_with_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        fake_genai = mock.MagicMock()
        with mock.patch.dict(
            "sys.modules",
            {
                "google": mock.MagicMock(),
                "google.genai": fake_genai,
            },
        ):
            if not EngineRegistry.contains("cloud"):
                EngineRegistry.register_value("cloud", CloudEngine)
            engine = CloudEngine()
        assert engine._google_client is not None

    def test_gemini_2_5_pro_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.models.generate_content.return_value = _fake_gemini_response(
            content="I am Gemini 2.5 Pro"
        )
        engine._google_client = fake_client

        # Mock the genai types import
        fake_config = mock.MagicMock()
        fake_types = mock.MagicMock()
        fake_types.GenerateContentConfig.return_value = fake_config
        with mock.patch.dict(
            "sys.modules",
            {
                "google": mock.MagicMock(),
                "google.genai": mock.MagicMock(),
                "google.genai.types": fake_types,
            },
        ):
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="gemini-2.5-pro"
            )
        assert result["content"] == "I am Gemini 2.5 Pro"
        assert result["model"] == "gemini-2.5-pro"
        assert result["usage"]["prompt_tokens"] == 15
        assert result["usage"]["completion_tokens"] == 10

    def test_gemini_2_5_flash_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.models.generate_content.return_value = _fake_gemini_response(
            content="I am Gemini 2.5 Flash"
        )
        engine._google_client = fake_client

        fake_types = mock.MagicMock()
        fake_types.GenerateContentConfig.return_value = mock.MagicMock()
        with mock.patch.dict(
            "sys.modules",
            {
                "google": mock.MagicMock(),
                "google.genai": mock.MagicMock(),
                "google.genai.types": fake_types,
            },
        ):
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="gemini-2.5-flash"
            )
        assert result["content"] == "I am Gemini 2.5 Flash"

    def test_gemini_3_pro_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.models.generate_content.return_value = _fake_gemini_response(
            content="I am Gemini 3 Pro"
        )
        engine._google_client = fake_client

        fake_types = mock.MagicMock()
        fake_types.GenerateContentConfig.return_value = mock.MagicMock()
        with mock.patch.dict(
            "sys.modules",
            {
                "google": mock.MagicMock(),
                "google.genai": mock.MagicMock(),
                "google.genai.types": fake_types,
            },
        ):
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="gemini-3-pro"
            )
        assert result["content"] == "I am Gemini 3 Pro"

    def test_gemini_3_flash_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.models.generate_content.return_value = _fake_gemini_response(
            content="I am Gemini 3 Flash"
        )
        engine._google_client = fake_client

        fake_types = mock.MagicMock()
        fake_types.GenerateContentConfig.return_value = mock.MagicMock()
        with mock.patch.dict(
            "sys.modules",
            {
                "google": mock.MagicMock(),
                "google.genai": mock.MagicMock(),
                "google.genai.types": fake_types,
            },
        ):
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="gemini-3-flash"
            )
        assert result["content"] == "I am Gemini 3 Flash"

    def test_gemini_function_call_extraction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Google function_call parts are extracted as flat tool_calls."""
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()

        # Build a response with a function_call part
        text_part = SimpleNamespace(text="Let me calculate.", function_call=None)
        fc = SimpleNamespace(name="calculator", args={"expression": "2+2"})
        fc_part = SimpleNamespace(text=None, function_call=fc)
        content_obj = SimpleNamespace(parts=[text_part, fc_part])
        candidate = SimpleNamespace(content=content_obj)
        usage = SimpleNamespace(prompt_token_count=10, candidates_token_count=8)
        fake_resp = SimpleNamespace(
            candidates=[candidate],
            usage_metadata=usage,
            text=None,
        )
        fake_client.models.generate_content.return_value = fake_resp
        engine._google_client = fake_client

        fake_types = mock.MagicMock()
        fake_config = mock.MagicMock()
        fake_types.GenerateContentConfig.return_value = fake_config
        with mock.patch.dict(
            "sys.modules",
            {
                "google": mock.MagicMock(),
                "google.genai": mock.MagicMock(),
                "google.genai.types": fake_types,
            },
        ):
            result = engine.generate(
                [Message(role=Role.USER, content="What is 2+2?")],
                model="gemini-3-pro",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "description": "Math",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            )

        assert result["content"] == "Let me calculate."
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["name"] == "calculator"
        assert '"expression"' in tc["arguments"]

    def test_gemini_no_tool_calls_when_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.models.generate_content.return_value = _fake_gemini_response(
            content="Just text"
        )
        engine._google_client = fake_client

        fake_types = mock.MagicMock()
        fake_types.GenerateContentConfig.return_value = mock.MagicMock()
        with mock.patch.dict(
            "sys.modules",
            {
                "google": mock.MagicMock(),
                "google.genai": mock.MagicMock(),
                "google.genai.types": fake_types,
            },
        ):
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="gemini-3-pro"
            )
        assert "tool_calls" not in result

    def test_gemini_cost_estimate(self) -> None:
        # gemini-2.5-pro: $1.25/M in, $10.00/M out
        cost = estimate_cost("gemini-2.5-pro", 1_000_000, 1_000_000)
        assert cost == pytest.approx(11.25)

        # gemini-2.5-flash: $0.30/M in, $2.50/M out
        cost = estimate_cost("gemini-2.5-flash", 1_000_000, 1_000_000)
        assert cost == pytest.approx(2.80)

        # gemini-3-pro: $2.00/M in, $12.00/M out
        cost = estimate_cost("gemini-3-pro", 1_000_000, 1_000_000)
        assert cost == pytest.approx(14.00)

        # gemini-3-flash: $0.50/M in, $3.00/M out
        cost = estimate_cost("gemini-3-flash", 1_000_000, 1_000_000)
        assert cost == pytest.approx(3.50)

    def test_gemini_routing(self) -> None:
        assert _is_google_model("gemini-2.5-pro") is True
        assert _is_google_model("gemini-2.5-flash") is True
        assert _is_google_model("gemini-3-pro") is True
        assert _is_google_model("gemini-3-flash") is True
        assert _is_google_model("gpt-5-mini") is False
        assert _is_google_model("claude-opus-4-6") is False

    def test_gemini_no_client_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine._google_client is None

        fake_types = mock.MagicMock()
        fake_types.GenerateContentConfig.return_value = mock.MagicMock()
        with mock.patch.dict(
            "sys.modules",
            {
                "google": mock.MagicMock(),
                "google.genai": mock.MagicMock(),
                "google.genai.types": fake_types,
            },
        ):
            with pytest.raises(
                EngineConnectionError,
                match="Google client not available",
            ):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="gemini-3-pro"
                )


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


class TestCloudModelDiscovery:
    def test_list_models_includes_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When all clients are set, all model lists are returned."""
        engine = _make_cloud_engine(monkeypatch)
        engine._openai_client = mock.MagicMock()
        engine._anthropic_client = mock.MagicMock()
        engine._google_client = mock.MagicMock()
        models = engine.list_models()
        for m in _OPENAI_MODELS:
            assert m in models
        for m in _ANTHROPIC_MODELS:
            assert m in models
        for m in _GOOGLE_MODELS:
            assert m in models

    def test_no_api_key_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine.list_models() == []

    def test_only_google_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        engine._google_client = mock.MagicMock()
        models = engine.list_models()
        assert set(models) == set(_GOOGLE_MODELS)
        # No OpenAI or Anthropic models
        for m in _OPENAI_MODELS:
            assert m not in models
        for m in _ANTHROPIC_MODELS:
            assert m not in models

    def test_health_with_google_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        engine._google_client = mock.MagicMock()
        assert engine.health() is True

    def test_health_no_clients(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine.health() is False


# ---------------------------------------------------------------------------
# Pricing completeness
# ---------------------------------------------------------------------------


class TestPricingTable:
    def test_all_new_models_in_pricing(self) -> None:
        expected = [
            "gpt-5-mini",
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3-pro",
            "gemini-3-flash",
        ]
        for model_id in expected:
            assert model_id in PRICING, f"{model_id} missing from PRICING dict"

    def test_pricing_values_positive(self) -> None:
        for model_id, (inp, out) in PRICING.items():
            assert inp >= 0, f"{model_id} has negative input price"
            assert out >= 0, f"{model_id} has negative output price"

    def test_zero_tokens_zero_cost(self) -> None:
        assert estimate_cost("gpt-5-mini", 0, 0) == 0.0
