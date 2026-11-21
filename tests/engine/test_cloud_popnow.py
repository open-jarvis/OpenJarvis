"""Tests for PopNow cloud-provider support.

PopNow is an OpenAI-compatible aggregator, so these tests cover routing: its
model IDs are ``vendor/model/task``, which would otherwise match the
``"claude"`` / ``"gemini"`` substring predicates and the server-side
``"/" means OpenRouter`` fallback.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.cloud import (
    _POPNOW_POPULAR,
    PRICING,
    CloudEngine,
    _is_anthropic_model,
    _is_google_model,
    _is_popnow_model,
    estimate_cost,
)
from openjarvis.intelligence.model_catalog import BUILTIN_MODELS
from openjarvis.server import cloud_router
from tests.engine.conftest import CLOUD_KEY_ENV_VARS

_DEFAULT_MODEL = "popnow/deepseek/v4-flash/chat"


def _make_cloud_engine(monkeypatch: pytest.MonkeyPatch) -> CloudEngine:
    for name in CLOUD_KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    if not EngineRegistry.contains("cloud"):
        EngineRegistry.register_value("cloud", CloudEngine)
    return CloudEngine()


def _fake_response() -> SimpleNamespace:
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    message = SimpleNamespace(content="Hello from PopNow!", tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(
        choices=[choice], usage=usage, model="deepseek/v4-flash/chat"
    )


class TestPopNowRouting:
    def test_is_popnow_model(self) -> None:
        assert _is_popnow_model(_DEFAULT_MODEL) is True
        assert _is_popnow_model("deepseek/v4-flash/chat") is False

    def test_prefixed_claude_does_not_route_to_anthropic(self) -> None:
        assert _is_anthropic_model("popnow/anthropic/claude-sonnet-5.5/chat") is False

    def test_prefixed_gemini_does_not_route_to_google(self) -> None:
        assert _is_google_model("popnow/google/gemini-3.7-flash/chat") is False

    def test_server_router_keeps_popnow_off_openrouter(self) -> None:
        assert cloud_router.get_provider(_DEFAULT_MODEL) == "popnow"

    def test_popular_models_are_prefixed_chat_models(self) -> None:
        for model in _POPNOW_POPULAR:
            assert model.startswith("popnow/")
            assert model.endswith("/chat")


class TestPopNowClient:
    def test_no_key_no_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine._popnow_client is None
        assert not set(_POPNOW_POPULAR) & set(engine.list_models())

    def test_generate_strips_the_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response()
        engine._popnow_client = client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
        )

        sent = client.chat.completions.create.call_args.kwargs
        assert sent["model"] == "deepseek/v4-flash/chat"
        assert result["content"] == "Hello from PopNow!"

    def test_generate_without_a_client_names_the_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        with pytest.raises(EngineConnectionError, match="POPNOW_API_KEY"):
            engine.generate(
                [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
            )

    def test_close_releases_the_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        engine._popnow_client = client
        engine.close()
        client.close.assert_called_once()
        assert engine._popnow_client is None


class TestPopNowCatalog:
    @pytest.mark.parametrize("model", _POPNOW_POPULAR)
    def test_every_listed_model_has_a_rate(self, model: str) -> None:
        assert model in PRICING
        assert estimate_cost(model, 1_000_000, 0) == pytest.approx(PRICING[model][0])

    def test_every_listed_model_is_in_the_catalog(self) -> None:
        catalog = {spec.model_id: spec for spec in BUILTIN_MODELS}
        for model in _POPNOW_POPULAR:
            assert catalog[model].provider == "popnow"
