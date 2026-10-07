"""Tests for Opper cloud-provider support.

Opper is an OpenAI-compatible gateway, so the interesting surface is not the
HTTP call (that is the shared OpenAI SDK) but the *routing*: most Opper model
IDs contain ``claude`` or ``gemini``, which the substring predicates would send
to the Anthropic and Google SDKs, and a provider-pinned route such as
``opper/anthropic/claude-sonnet-4-6`` contains a ``/``, which the server-side
cloud router treats as OpenRouter. These tests pin that an ``opper/``-prefixed
ID always reaches the Opper client and never leaks into another provider's.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.cloud import (
    _OPPER_POPULAR,
    PRICING,
    CloudEngine,
    _is_anthropic_model,
    _is_deepseek_model,
    _is_google_model,
    _is_openai_model,
    _is_opper_model,
    estimate_cost,
)
from openjarvis.intelligence.model_catalog import BUILTIN_MODELS
from openjarvis.server import cloud_router
from tests.engine.conftest import CLOUD_KEY_ENV_VARS

_ALL_CLOUD_KEYS = CLOUD_KEY_ENV_VARS

_DEFAULT_MODEL = "opper/claude-sonnet-4-6"


def _make_cloud_engine(monkeypatch: pytest.MonkeyPatch) -> CloudEngine:
    """Create a CloudEngine with all API keys cleared."""
    for name in _ALL_CLOUD_KEYS:
        monkeypatch.delenv(name, raising=False)
    if not EngineRegistry.contains("cloud"):
        EngineRegistry.register_value("cloud", CloudEngine)
    return CloudEngine()


def _fake_response(
    content: str = "Hello from Opper!",
    model: str = "claude-sonnet-4-6",
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


class TestOpperRouting:
    def test_is_opper_model(self) -> None:
        assert _is_opper_model(_DEFAULT_MODEL) is True
        assert _is_opper_model("opper/anthropic/claude-sonnet-4-6") is True
        assert _is_opper_model("claude-sonnet-4-6") is False
        assert _is_opper_model("openrouter/anthropic/claude-sonnet-4") is False

    def test_prefixed_claude_does_not_route_to_anthropic(self) -> None:
        """``"claude" in model`` would otherwise swallow the gateway ID."""
        assert _is_anthropic_model("claude-sonnet-4-6") is True
        assert _is_anthropic_model(_DEFAULT_MODEL) is False
        assert _is_anthropic_model("opper/anthropic/claude-sonnet-4-6") is False

    def test_prefixed_gemini_does_not_route_to_google(self) -> None:
        assert _is_google_model("gemini-3-pro") is True
        assert _is_google_model("opper/gemini-3.8-flash") is False

    def test_prefixed_gpt_does_not_route_to_openai_direct(self) -> None:
        assert _is_openai_model("gpt-4o") is True
        assert _is_openai_model("opper/gpt-5.5") is False

    def test_prefixed_deepseek_does_not_route_to_deepseek_direct(self) -> None:
        assert _is_deepseek_model("deepseek-v4-pro") is True
        assert _is_deepseek_model("opper/deepseek-v4-pro") is False

    def test_popular_models_all_carry_the_prefix(self) -> None:
        assert _OPPER_POPULAR
        for model in _OPPER_POPULAR:
            assert model.startswith("opper/"), model

    def test_default_model_is_first(self) -> None:
        assert _OPPER_POPULAR[0] == _DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Client init / lifecycle
# ---------------------------------------------------------------------------


class TestOpperInit:
    def test_init_with_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in _ALL_CLOUD_KEYS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OPPER_API_KEY", "op-test")
        fake_openai = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"openai": fake_openai}):
            if not EngineRegistry.contains("cloud"):
                EngineRegistry.register_value("cloud", CloudEngine)
            engine = CloudEngine()
        assert engine._opper_client is not None
        fake_openai.OpenAI.assert_called_once_with(
            base_url="https://api.opper.ai/v3/compat", api_key="op-test"
        )

    def test_health_with_opper_key_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in _ALL_CLOUD_KEYS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OPPER_API_KEY", "op-test")
        with mock.patch.dict("sys.modules", {"openai": mock.MagicMock()}):
            engine = CloudEngine()
        assert engine.health() is True

    def test_no_key_no_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine._opper_client is None

    def test_list_models_only_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert _DEFAULT_MODEL not in engine.list_models()
        engine._opper_client = mock.MagicMock()
        assert set(_OPPER_POPULAR).issubset(set(engine.list_models()))

    def test_can_serve_requires_the_opper_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine.can_serve(_DEFAULT_MODEL) is False
        engine._anthropic_client = mock.MagicMock()
        assert engine.can_serve(_DEFAULT_MODEL) is False
        engine._opper_client = mock.MagicMock()
        assert engine.can_serve(_DEFAULT_MODEL) is True

    def test_close_releases_the_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        engine._opper_client = client
        engine.close()
        client.close.assert_called_once()
        assert engine._opper_client is None


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


class TestOpperGenerate:
    def test_generate_strips_the_prefix_before_calling_the_gateway(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response()
        engine._opper_client = client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
        )

        sent = client.chat.completions.create.call_args.kwargs
        assert sent["model"] == "claude-sonnet-4-6"
        assert result["content"] == "Hello from Opper!"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["finish_reason"] == "stop"

    def test_pinned_route_keeps_its_provider_segment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response()
        engine._opper_client = client

        engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model="opper/anthropic/claude-sonnet-4-6",
        )

        sent = client.chat.completions.create.call_args.kwargs
        assert sent["model"] == "anthropic/claude-sonnet-4-6"

    def test_generate_empty_choices_surfaces_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        fake_resp = SimpleNamespace(
            choices=None,
            error={"message": "Upstream error: Service temporarily overloaded"},
            usage=None,
            model="claude-sonnet-4-6",
        )
        client.chat.completions.create.return_value = fake_resp
        engine._opper_client = client

        with pytest.raises(EngineConnectionError) as exc_info:
            engine.generate(
                [Message(role=Role.USER, content="Hi")],
                model=_DEFAULT_MODEL,
            )

        assert "Opper" in str(exc_info.value)
        assert "Service temporarily overloaded" in str(exc_info.value)

    def test_generate_retries_without_unsupported_temperature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        calls: list[dict] = []

        def create(**kwargs):
            calls.append(kwargs)
            if "temperature" in kwargs:
                raise Exception(
                    "Error code: 400 - Unsupported value: 'temperature' "
                    "does not support 0.7"
                )
            return _fake_response(model="gpt-5.5")

        client.chat.completions.create.side_effect = create
        engine._opper_client = client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model="opper/gpt-5.5",
            temperature=0.7,
        )

        assert result["content"] == "Hello from Opper!"
        assert len(calls) == 2
        assert calls[0]["model"] == calls[1]["model"] == "gpt-5.5"
        assert "temperature" in calls[0]
        assert "temperature" not in calls[1]

    @pytest.mark.parametrize("model", _OPPER_POPULAR)
    def test_every_listed_model_routes_to_the_opper_client(
        self, monkeypatch: pytest.MonkeyPatch, model: str
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response(model=model)
        engine._opper_client = client
        # Every other provider client stays None: reaching one would raise.
        engine.generate([Message(role=Role.USER, content="Hi")], model=model)
        assert client.chat.completions.create.call_count == 1

    def test_generate_without_a_client_names_the_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        with pytest.raises(EngineConnectionError, match="OPPER_API_KEY"):
            engine.generate(
                [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
            )

    def test_tools_and_tool_choice_are_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response()
        engine._opper_client = client
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
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response()
        engine._opper_client = client

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
        engine._opper_client = client

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


class TestOpperStream:
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
        engine._opper_client = client

        tokens = [
            t
            async for t in engine.stream(
                [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
            )
        ]

        assert tokens == ["Hel", "lo"]
        sent = client.chat.completions.create.call_args.kwargs
        assert sent["model"] == "claude-sonnet-4-6"
        assert sent["stream"] is True

    @pytest.mark.asyncio
    async def test_stream_without_a_client_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        with pytest.raises(EngineConnectionError, match="Opper"):
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
        engine._opper_client = client

        chunks = [
            c
            async for c in engine._stream_full_openai(
                [Message(role=Role.USER, content="Hi")],
                model="opper/gemini-3.8-flash",
                temperature=0.7,
                max_tokens=32,
            )
        ]

        assert client.chat.completions.create.call_args.kwargs["model"] == (
            "gemini-3.8-flash"
        )
        assert [c.content for c in chunks] == ["hi"]


# ---------------------------------------------------------------------------
# Pricing / catalog
# ---------------------------------------------------------------------------


class TestOpperPricing:
    @pytest.mark.parametrize("model", _OPPER_POPULAR)
    def test_every_listed_model_has_a_rate(self, model: str) -> None:
        assert model in PRICING, f"{model} would silently cost $0"
        assert estimate_cost(model, 1_000_000, 1_000_000) > 0.0

    def test_generate_reports_cost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response(
            prompt_tokens=1_000_000, completion_tokens=1_000_000
        )
        engine._opper_client = client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
        )

        assert result["cost_usd"] == pytest.approx(3.00 + 15.00)

    def test_catalog_entries_match_the_pricing_table(self) -> None:
        specs = {s.model_id: s for s in BUILTIN_MODELS if s.provider == "opper"}
        assert set(specs) == set(_OPPER_POPULAR)
        for model_id, spec in specs.items():
            assert spec.requires_api_key is True
            assert spec.supported_engines == ("cloud",)
            rate_in, rate_out = PRICING[model_id]
            assert spec.metadata["pricing_input"] == pytest.approx(rate_in)
            assert spec.metadata["pricing_output"] == pytest.approx(rate_out)


# ---------------------------------------------------------------------------
# Server-side cloud router
# ---------------------------------------------------------------------------


class TestOpperServerRouting:
    def test_provider_is_opper_not_anthropic(self) -> None:
        assert cloud_router.get_provider("claude-sonnet-4-6") == "anthropic"
        assert cloud_router.get_provider(_DEFAULT_MODEL) == "opper"

    def test_pinned_route_is_opper_not_openrouter(self) -> None:
        """The router's ``"/" in model`` fallback means OpenRouter; the opper
        prefix has to win before it."""
        assert cloud_router.get_provider("opper/anthropic/claude-sonnet-4-6") == "opper"
        assert cloud_router.get_provider("meta-llama/llama-3-8b") == "openrouter"

    def test_is_cloud_model(self) -> None:
        assert cloud_router.is_cloud_model(_DEFAULT_MODEL) is True

    def test_local_hf_orgs_still_win(self) -> None:
        assert cloud_router.get_provider("unsloth/MiniMax-M2.5-GGUF") is None
