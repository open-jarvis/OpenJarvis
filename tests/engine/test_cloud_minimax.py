"""Tests for MiniMax cloud provider support."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.cloud import (
    _MINIMAX_MODELS,
    PRICING,
    CloudEngine,
    _is_minimax_model,
    estimate_cost,
)


def _make_cloud_engine(monkeypatch: pytest.MonkeyPatch) -> CloudEngine:
    """Create a CloudEngine with all API keys cleared."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    if not EngineRegistry.contains("cloud"):
        EngineRegistry.register_value("cloud", CloudEngine)
    return CloudEngine()


def _fake_minimax_response(
    content: str = "Hello from MiniMax!",
    model: str = "MiniMax-M2.5",
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


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------


class TestMiniMaxRouting:
    def test_is_minimax_model(self) -> None:
        assert _is_minimax_model("MiniMax-M2.7") is True
        assert _is_minimax_model("MiniMax-M2.7-highspeed") is True
        assert _is_minimax_model("MiniMax-M2.5") is True
        assert _is_minimax_model("MiniMax-M2.5-highspeed") is True
        assert _is_minimax_model("minimax-m2.7") is True
        assert _is_minimax_model("gpt-4o") is False
        assert _is_minimax_model("claude-opus-4-6") is False
        assert _is_minimax_model("gemini-3-pro") is False

    def test_minimax_models_list(self) -> None:
        assert "MiniMax-M2.7" in _MINIMAX_MODELS
        assert "MiniMax-M2.7-highspeed" in _MINIMAX_MODELS
        assert "MiniMax-M2.5" in _MINIMAX_MODELS
        assert "MiniMax-M2.5-highspeed" in _MINIMAX_MODELS

    def test_m27_is_first_in_list(self) -> None:
        assert _MINIMAX_MODELS[0] == "MiniMax-M2.7"
        assert _MINIMAX_MODELS[1] == "MiniMax-M2.7-highspeed"


# ---------------------------------------------------------------------------
# Init tests
# ---------------------------------------------------------------------------


class TestMiniMaxInit:
    def test_init_with_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        fake_openai = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"openai": fake_openai}):
            if not EngineRegistry.contains("cloud"):
                EngineRegistry.register_value("cloud", CloudEngine)
            engine = CloudEngine()
        assert engine._minimax_client is not None

    def test_health_with_minimax_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        fake_openai = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"openai": fake_openai}):
            engine = CloudEngine()
        assert engine.health() is True

    def test_no_minimax_key_no_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine._minimax_client is None


# ---------------------------------------------------------------------------
# Generate tests
# ---------------------------------------------------------------------------


class TestMiniMaxGenerate:
    def test_m27_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _fake_minimax_response(
            content="I am MiniMax M2.7", model="MiniMax-M2.7"
        )
        engine._minimax_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="MiniMax-M2.7"
        )
        assert result["content"] == "I am MiniMax M2.7"
        assert result["model"] == "MiniMax-M2.7"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5

    def test_m27_highspeed_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _fake_minimax_response(
            content="I am MiniMax M2.7 Highspeed", model="MiniMax-M2.7-highspeed"
        )
        engine._minimax_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="MiniMax-M2.7-highspeed"
        )
        assert result["content"] == "I am MiniMax M2.7 Highspeed"
        assert result["model"] == "MiniMax-M2.7-highspeed"

    def test_m25_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _fake_minimax_response(
            content="I am MiniMax M2.5", model="MiniMax-M2.5"
        )
        engine._minimax_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="MiniMax-M2.5"
        )
        assert result["content"] == "I am MiniMax M2.5"
        assert result["model"] == "MiniMax-M2.5"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5

    def test_m25_highspeed_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _fake_minimax_response(
            content="I am MiniMax M2.5 Highspeed", model="MiniMax-M2.5-highspeed"
        )
        engine._minimax_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="MiniMax-M2.5-highspeed"
        )
        assert result["content"] == "I am MiniMax M2.5 Highspeed"
        assert result["model"] == "MiniMax-M2.5-highspeed"

    def test_temperature_clamped_above_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MiniMax requires temperature in (0.0, 1.0]; verify zero is clamped."""
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _fake_minimax_response()
        engine._minimax_client = fake_client

        engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model="MiniMax-M2.5",
            temperature=0.0,
        )
        call_kwargs = fake_client.chat.completions.create.call_args
        actual_temp = call_kwargs.kwargs.get("temperature") or call_kwargs[1].get(
            "temperature"
        )
        assert actual_temp >= 0.01, "Temperature should be clamped above zero"

    def test_temperature_clamped_at_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MiniMax requires temperature <= 1.0; verify high values are clamped."""
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _fake_minimax_response()
        engine._minimax_client = fake_client

        engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model="MiniMax-M2.5",
            temperature=2.0,
        )
        call_kwargs = fake_client.chat.completions.create.call_args
        actual_temp = call_kwargs.kwargs.get("temperature") or call_kwargs[1].get(
            "temperature"
        )
        assert actual_temp <= 1.0, "Temperature should be clamped at 1.0"

    def test_tool_calls_extraction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_tool_call = SimpleNamespace(
            id="call_minimax_123",
            type="function",
            function=SimpleNamespace(name="search", arguments='{"q":"test"}'),
        )
        fake_resp = _fake_minimax_response(content="", model="MiniMax-M2.5")
        fake_resp.choices[0].message.tool_calls = [fake_tool_call]

        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = fake_resp
        engine._minimax_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Search")], model="MiniMax-M2.5"
        )
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["id"] == "call_minimax_123"
        assert tc["name"] == "search"

    def test_no_tool_calls_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _fake_minimax_response(
            content="Just text"
        )
        engine._minimax_client = fake_client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model="MiniMax-M2.5"
        )
        assert "tool_calls" not in result

    def test_no_client_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine._minimax_client is None

        with pytest.raises(EngineConnectionError, match="MiniMax client not available"):
            engine.generate(
                [Message(role=Role.USER, content="Hi")], model="MiniMax-M2.5"
            )


# ---------------------------------------------------------------------------
# Model discovery tests
# ---------------------------------------------------------------------------


class TestMiniMaxModelDiscovery:
    def test_list_models_includes_minimax(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        engine._minimax_client = mock.MagicMock()
        models = engine.list_models()
        for m in _MINIMAX_MODELS:
            assert m in models

    def test_only_minimax_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        engine._minimax_client = mock.MagicMock()
        models = engine.list_models()
        assert set(models) == set(_MINIMAX_MODELS)


# ---------------------------------------------------------------------------
# Pricing tests
# ---------------------------------------------------------------------------


class TestMiniMaxPricing:
    def test_minimax_models_in_pricing(self) -> None:
        assert "MiniMax-M2.7" in PRICING
        assert "MiniMax-M2.7-highspeed" in PRICING
        assert "MiniMax-M2.5" in PRICING
        assert "MiniMax-M2.5-highspeed" in PRICING

    def test_minimax_m27_cost_estimate(self) -> None:
        # MiniMax-M2.7: $0.30/M in, $1.20/M out
        cost = estimate_cost("MiniMax-M2.7", 1_000_000, 1_000_000)
        assert cost == pytest.approx(1.50)

    def test_minimax_m27_highspeed_cost_estimate(self) -> None:
        # MiniMax-M2.7-highspeed: $0.60/M in, $2.40/M out
        cost = estimate_cost("MiniMax-M2.7-highspeed", 1_000_000, 1_000_000)
        assert cost == pytest.approx(3.00)

    def test_minimax_m25_cost_estimate(self) -> None:
        # MiniMax-M2.5: $0.30/M in, $1.20/M out
        cost = estimate_cost("MiniMax-M2.5", 1_000_000, 1_000_000)
        assert cost == pytest.approx(1.50)

    def test_zero_tokens_zero_cost(self) -> None:
        assert estimate_cost("MiniMax-M2.7", 0, 0) == 0.0


# ---------------------------------------------------------------------------
# Close tests
# ---------------------------------------------------------------------------


class TestMiniMaxClose:
    def test_close_minimax_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        fake_client = mock.MagicMock()
        engine._minimax_client = fake_client
        engine.close()
        assert engine._minimax_client is None
        fake_client.close.assert_called_once()
