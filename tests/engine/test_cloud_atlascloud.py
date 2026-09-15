"""Tests for Atlas Cloud cloud-provider support.

Atlas Cloud is an OpenAI-compatible aggregator, so the interesting surface is
not the HTTP call (that is the shared OpenAI SDK) but the *routing*: its model
IDs are already ``vendor/model``, which collides with three existing rules —
the ``"claude" in model`` / ``"gemini" in model`` substring predicates and the
``"/" in model means OpenRouter`` fallback in the server-side cloud router.
These tests pin that an ``atlascloud/``-prefixed ID always reaches the Atlas
client and never leaks into another provider's.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.cloud import (
    _ATLASCLOUD_POPULAR,
    PRICING,
    CloudEngine,
    _is_anthropic_model,
    _is_atlascloud_model,
    _is_google_model,
    _is_minimax_model,
    _is_openai_model,
    estimate_cost,
)
from openjarvis.intelligence.model_catalog import BUILTIN_MODELS
from openjarvis.server import cloud_router

_ALL_CLOUD_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "MINIMAX_API_KEY",
    "DEEPSEEK_API_KEY",
    "ATLASCLOUD_API_KEY",
)

_DEFAULT_MODEL = "atlascloud/openai/gpt-4.1-mini"


def _make_cloud_engine(monkeypatch: pytest.MonkeyPatch) -> CloudEngine:
    """Create a CloudEngine with all API keys cleared."""
    for name in _ALL_CLOUD_KEYS:
        monkeypatch.delenv(name, raising=False)
    if not EngineRegistry.contains("cloud"):
        EngineRegistry.register_value("cloud", CloudEngine)
    return CloudEngine()


def _fake_response(
    content: str = "Hello from Atlas Cloud!",
    model: str = "openai/gpt-4.1-mini",
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
# Routing
# ---------------------------------------------------------------------------


class TestAtlasCloudRouting:
    def test_is_atlascloud_model(self) -> None:
        assert _is_atlascloud_model(_DEFAULT_MODEL) is True
        assert _is_atlascloud_model("atlascloud/zai-org/GLM-4.6") is True
        assert _is_atlascloud_model("openai/gpt-4.1-mini") is False
        assert _is_atlascloud_model("gpt-4o") is False
        assert _is_atlascloud_model("openrouter/openai/gpt-4o") is False

    def test_prefixed_claude_does_not_route_to_anthropic(self) -> None:
        """``"claude" in model`` would otherwise swallow the aggregator ID."""
        assert _is_anthropic_model("claude-sonnet-4-6") is True
        assert _is_anthropic_model("atlascloud/anthropic/claude-sonnet-4-6") is False

    def test_prefixed_gemini_does_not_route_to_google(self) -> None:
        assert _is_google_model("gemini-3-pro") is True
        assert _is_google_model("atlascloud/google/gemini-3-pro") is False

    def test_prefixed_minimax_does_not_route_to_minimax_direct(self) -> None:
        """Atlas serves a MiniMax model; direct-MiniMax must not claim it."""
        assert _is_minimax_model("MiniMax-M2.5") is True
        assert _is_minimax_model("atlascloud/minimaxai/minimax-m2.5") is False

    def test_prefixed_gpt_does_not_route_to_openai_direct(self) -> None:
        assert _is_openai_model("gpt-4o") is True
        assert _is_openai_model(_DEFAULT_MODEL) is False

    def test_popular_models_all_carry_the_prefix(self) -> None:
        assert _ATLASCLOUD_POPULAR
        for model in _ATLASCLOUD_POPULAR:
            assert model.startswith("atlascloud/"), model

    def test_default_model_is_first(self) -> None:
        assert _ATLASCLOUD_POPULAR[0] == _DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Client init / lifecycle
# ---------------------------------------------------------------------------


class TestAtlasCloudInit:
    def test_init_with_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in _ALL_CLOUD_KEYS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("ATLASCLOUD_API_KEY", "apikey-test")
        fake_openai = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"openai": fake_openai}):
            if not EngineRegistry.contains("cloud"):
                EngineRegistry.register_value("cloud", CloudEngine)
            engine = CloudEngine()
        assert engine._atlascloud_client is not None
        fake_openai.OpenAI.assert_called_once_with(
            base_url="https://api.atlascloud.ai/v1", api_key="apikey-test"
        )

    def test_health_with_atlascloud_key_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in _ALL_CLOUD_KEYS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("ATLASCLOUD_API_KEY", "apikey-test")
        with mock.patch.dict("sys.modules", {"openai": mock.MagicMock()}):
            engine = CloudEngine()
        assert engine.health() is True

    def test_no_key_no_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine._atlascloud_client is None

    def test_list_models_only_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert _DEFAULT_MODEL not in engine.list_models()
        engine._atlascloud_client = mock.MagicMock()
        assert set(_ATLASCLOUD_POPULAR).issubset(set(engine.list_models()))

    def test_can_serve_requires_the_atlas_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine.can_serve(_DEFAULT_MODEL) is False
        engine._atlascloud_client = mock.MagicMock()
        assert engine.can_serve(_DEFAULT_MODEL) is True

    def test_close_releases_the_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        engine._atlascloud_client = client
        engine.close()
        client.close.assert_called_once()
        assert engine._atlascloud_client is None

    def test_close_also_releases_the_deepseek_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: close() used to leave _deepseek_client (and its httpx
        connection pool) alive while dropping every other provider client."""
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        engine._deepseek_client = client
        engine.close()
        client.close.assert_called_once()
        assert engine._deepseek_client is None


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


class TestAtlasCloudGenerate:
    def test_generate_strips_the_prefix_before_calling_the_gateway(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response()
        engine._atlascloud_client = client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
        )

        sent = client.chat.completions.create.call_args.kwargs
        assert sent["model"] == "openai/gpt-4.1-mini"
        assert result["content"] == "Hello from Atlas Cloud!"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["finish_reason"] == "stop"

    @pytest.mark.parametrize("model", _ATLASCLOUD_POPULAR)
    def test_every_listed_model_routes_to_the_atlas_client(
        self, monkeypatch: pytest.MonkeyPatch, model: str
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response(model=model)
        engine._atlascloud_client = client
        # Every other provider client stays None: reaching one would raise.
        engine.generate([Message(role=Role.USER, content="Hi")], model=model)
        assert client.chat.completions.create.call_count == 1

    def test_generate_without_a_client_names_the_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        with pytest.raises(EngineConnectionError, match="ATLASCLOUD_API_KEY"):
            engine.generate(
                [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
            )

    def test_tools_and_tool_choice_are_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response()
        engine._atlascloud_client = client
        tools = [{"type": "function", "function": {"name": "search"}}]

        engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model=_DEFAULT_MODEL,
            tools=tools,
            tool_choice="auto",
        )

        sent = client.chat.completions.create.call_args.kwargs
        assert sent["tools"] == tools
        assert sent["tool_choice"] == "auto"

    def test_response_format_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unlike OpenRouter, the gateway honours OpenAI JSON mode."""
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response()
        engine._atlascloud_client = client

        engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model=_DEFAULT_MODEL,
            response_format={"type": "json_object"},
        )

        sent = client.chat.completions.create.call_args.kwargs
        assert sent["response_format"] == {"type": "json_object"}

    def test_tool_calls_are_normalised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response(
            content="",
            tool_calls=[
                SimpleNamespace(
                    id="call_1",
                    type="function",
                    function=SimpleNamespace(name="search", arguments='{"q":"x"}'),
                )
            ],
        )
        engine._atlascloud_client = client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
        )

        assert result["tool_calls"] == [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q":"x"}'},
            }
        ]


# ---------------------------------------------------------------------------
# stream()
# ---------------------------------------------------------------------------


class TestAtlasCloudStream:
    @pytest.mark.asyncio
    async def test_stream_yields_content_deltas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=c))])
            for c in ("Hel", "lo")
        ] + [SimpleNamespace(choices=[])]
        engine._atlascloud_client = client

        tokens = [
            t
            async for t in engine.stream(
                [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
            )
        ]

        assert tokens == ["Hel", "lo"]
        sent = client.chat.completions.create.call_args.kwargs
        assert sent["model"] == "openai/gpt-4.1-mini"
        assert sent["stream"] is True

    @pytest.mark.asyncio
    async def test_stream_without_a_client_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        with pytest.raises(EngineConnectionError, match="Atlas Cloud"):
            async for _ in engine.stream(
                [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
            ):
                pass

    @pytest.mark.asyncio
    async def test_stream_full_strips_the_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="hi", tool_calls=None),
                        finish_reason=None,
                    )
                ]
            )
        ]
        engine._atlascloud_client = client

        chunks = [
            c
            async for c in engine._stream_full_openai(
                [Message(role=Role.USER, content="Hi")],
                model="atlascloud/zai-org/GLM-4.6",
                temperature=0.7,
                max_tokens=32,
            )
        ]

        assert client.chat.completions.create.call_args.kwargs["model"] == (
            "zai-org/GLM-4.6"
        )
        assert [c.content for c in chunks] == ["hi"]


# ---------------------------------------------------------------------------
# Pricing / catalog
# ---------------------------------------------------------------------------


class TestAtlasCloudPricing:
    @pytest.mark.parametrize("model", _ATLASCLOUD_POPULAR)
    def test_every_listed_model_has_a_rate(self, model: str) -> None:
        assert model in PRICING, f"{model} would silently cost $0"
        assert estimate_cost(model, 1_000_000, 1_000_000) > 0.0

    def test_cost_uses_the_atlas_rate_not_the_direct_vendor_rate(self) -> None:
        """``atlascloud/minimaxai/minimax-m2.5`` and ``MiniMax-M2.5`` are
        different line items — a prefix collision here would misprice."""
        atlas = estimate_cost("atlascloud/minimaxai/minimax-m2.5", 1_000_000, 0)
        direct = estimate_cost("MiniMax-M2.5", 1_000_000, 0)
        assert atlas == pytest.approx(0.295)
        assert direct == pytest.approx(0.30)

    def test_generate_reports_cost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response(
            prompt_tokens=1_000_000, completion_tokens=1_000_000
        )
        engine._atlascloud_client = client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
        )

        assert result["cost_usd"] == pytest.approx(0.40 + 1.60)

    def test_catalog_entries_match_the_pricing_table(self) -> None:
        specs = {s.model_id: s for s in BUILTIN_MODELS if s.provider == "atlascloud"}
        assert set(specs) == set(_ATLASCLOUD_POPULAR)
        for model_id, spec in specs.items():
            assert spec.requires_api_key is True
            assert spec.supported_engines == ("cloud",)
            rate_in, rate_out = PRICING[model_id]
            assert spec.metadata["pricing_input"] == pytest.approx(rate_in)
            assert spec.metadata["pricing_output"] == pytest.approx(rate_out)


# ---------------------------------------------------------------------------
# Server-side cloud router
# ---------------------------------------------------------------------------


class TestAtlasCloudServerRouting:
    def test_provider_is_atlascloud_not_openrouter(self) -> None:
        """The router's ``"/" in model`` fallback means OpenRouter; the
        atlascloud prefix has to win before it."""
        assert cloud_router.get_provider(_DEFAULT_MODEL) == "atlascloud"
        assert cloud_router.get_provider("meta-llama/llama-3-8b") == "openrouter"

    def test_prefixed_claude_is_not_classified_as_anthropic(self) -> None:
        assert cloud_router.get_provider("claude-sonnet-4-6") == "anthropic"
        assert (
            cloud_router.get_provider("atlascloud/anthropic/claude-sonnet-4-6")
            == "atlascloud"
        )

    def test_is_cloud_model(self) -> None:
        assert cloud_router.is_cloud_model(_DEFAULT_MODEL) is True

    def test_local_hf_orgs_still_win(self) -> None:
        assert cloud_router.get_provider("unsloth/MiniMax-M2.5-GGUF") is None
