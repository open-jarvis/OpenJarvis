"""Tests for Cheaper Inference cloud-provider support.

Cheaper Inference is an OpenAI-compatible gateway, so the interesting surface
is the *routing*, not the HTTP call (that is the shared OpenAI SDK). Its model
IDs are bare (``gpt-5.4-mini``, ``claude-sonnet-5``), so they carry a
``cheaperinference/`` prefix. These tests pin that a prefixed ID always
reaches the Cheaper Inference client and never another provider's.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.cloud import (
    _CHEAPERINFERENCE_POPULAR,
    CloudEngine,
    _is_anthropic_model,
    _is_cheaperinference_model,
    _is_deepseek_model,
    _is_google_model,
    _is_openai_model,
)
from openjarvis.intelligence.model_catalog import BUILTIN_MODELS
from openjarvis.server import cloud_router
from tests.engine.conftest import CLOUD_KEY_ENV_VARS

_DEFAULT_MODEL = "cheaperinference/gpt-5.4-mini"


def _make_cloud_engine(monkeypatch: pytest.MonkeyPatch) -> CloudEngine:
    """Create a CloudEngine with all API keys cleared."""
    for name in CLOUD_KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    if not EngineRegistry.contains("cloud"):
        EngineRegistry.register_value("cloud", CloudEngine)
    return CloudEngine()


def _fake_response(
    content: str = "Hello from Cheaper Inference!",
    model: str = "gpt-5.4-mini",
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


class TestCheaperInferenceRouting:
    def test_is_cheaperinference_model(self) -> None:
        assert _is_cheaperinference_model(_DEFAULT_MODEL) is True
        assert _is_cheaperinference_model("cheaperinference/glm-5.3") is True
        assert _is_cheaperinference_model("gpt-5.4-mini") is False
        assert _is_cheaperinference_model("codex/gpt-4o") is False

    def test_prefixed_claude_does_not_route_to_anthropic(self) -> None:
        assert _is_anthropic_model("claude-sonnet-4-6") is True
        assert _is_anthropic_model("cheaperinference/claude-sonnet-5") is False

    def test_prefixed_gemini_does_not_route_to_google(self) -> None:
        assert _is_google_model("gemini-3-pro") is True
        assert _is_google_model("cheaperinference/gemini-3.1-pro") is False

    def test_prefixed_deepseek_does_not_route_to_deepseek_direct(self) -> None:
        assert _is_deepseek_model("deepseek-v4-flash") is True
        assert _is_deepseek_model("cheaperinference/deepseek-v4-flash") is False

    def test_prefixed_gpt_does_not_route_to_openai_direct(self) -> None:
        assert _is_openai_model("gpt-5.4-mini") is True
        assert _is_openai_model(_DEFAULT_MODEL) is False

    def test_popular_models_all_carry_the_prefix(self) -> None:
        assert _CHEAPERINFERENCE_POPULAR
        for model in _CHEAPERINFERENCE_POPULAR:
            assert model.startswith("cheaperinference/"), model

    def test_default_model_is_first(self) -> None:
        assert _CHEAPERINFERENCE_POPULAR[0] == _DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Client init / lifecycle
# ---------------------------------------------------------------------------


class TestCheaperInferenceInit:
    def test_init_with_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in CLOUD_KEY_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("CHEAPER_INFERENCE_API_KEY", "ci_live_test")
        fake_openai = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"openai": fake_openai}):
            if not EngineRegistry.contains("cloud"):
                EngineRegistry.register_value("cloud", CloudEngine)
            engine = CloudEngine()
        assert engine._cheaperinference_client is not None
        fake_openai.OpenAI.assert_called_once_with(
            base_url="https://api.cheaperinference.com/v1", api_key="ci_live_test"
        )

    def test_health_with_cheaperinference_key_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in CLOUD_KEY_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("CHEAPER_INFERENCE_API_KEY", "ci_live_test")
        with mock.patch.dict("sys.modules", {"openai": mock.MagicMock()}):
            engine = CloudEngine()
        assert engine.health() is True

    def test_no_key_no_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine._cheaperinference_client is None

    def test_list_models_only_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert _DEFAULT_MODEL not in engine.list_models()
        engine._cheaperinference_client = mock.MagicMock()
        assert set(_CHEAPERINFERENCE_POPULAR).issubset(set(engine.list_models()))

    def test_can_serve_requires_the_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        assert engine.can_serve(_DEFAULT_MODEL) is False
        engine._cheaperinference_client = mock.MagicMock()
        assert engine.can_serve(_DEFAULT_MODEL) is True

    def test_close_releases_the_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        engine._cheaperinference_client = client
        engine.close()
        client.close.assert_called_once()
        assert engine._cheaperinference_client is None


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


class TestCheaperInferenceGenerate:
    def test_generate_strips_the_prefix_before_calling_the_gateway(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response()
        engine._cheaperinference_client = client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
        )

        sent = client.chat.completions.create.call_args.kwargs
        assert sent["model"] == "gpt-5.4-mini"
        assert result["content"] == "Hello from Cheaper Inference!"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["finish_reason"] == "stop"

    def test_generate_empty_choices_surfaces_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=None,
            error={"message": "Upstream error: Service temporarily overloaded"},
            usage=None,
            model="gpt-5.4-mini",
        )
        engine._cheaperinference_client = client

        with pytest.raises(EngineConnectionError) as exc_info:
            engine.generate(
                [Message(role=Role.USER, content="Hi")],
                model=_DEFAULT_MODEL,
            )

        assert "Cheaper Inference" in str(exc_info.value)
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
            return _fake_response()

        client.chat.completions.create.side_effect = create
        engine._cheaperinference_client = client

        result = engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model=_DEFAULT_MODEL,
            temperature=0.7,
        )

        assert result["content"] == "Hello from Cheaper Inference!"
        assert len(calls) == 2
        assert calls[0]["model"] == calls[1]["model"] == "gpt-5.4-mini"
        assert "temperature" in calls[0]
        assert "temperature" not in calls[1]

    @pytest.mark.parametrize("model", _CHEAPERINFERENCE_POPULAR)
    def test_every_listed_model_routes_to_the_client(
        self, monkeypatch: pytest.MonkeyPatch, model: str
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response(model=model)
        engine._cheaperinference_client = client
        # Every other provider client stays None: reaching one would raise.
        engine.generate([Message(role=Role.USER, content="Hi")], model=model)
        assert client.chat.completions.create.call_count == 1

    def test_generate_without_a_client_names_the_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        with pytest.raises(EngineConnectionError, match="CHEAPER_INFERENCE_API_KEY"):
            engine.generate(
                [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
            )

    def test_tools_and_tool_choice_are_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        client = mock.MagicMock()
        client.chat.completions.create.return_value = _fake_response()
        engine._cheaperinference_client = client
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
        engine._cheaperinference_client = client
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": {"type": "object"}},
        }

        engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model=_DEFAULT_MODEL,
            response_format=response_format,
        )

        sent = client.chat.completions.create.call_args.kwargs
        assert sent["response_format"] == response_format

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
        engine._cheaperinference_client = client

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


class TestCheaperInferenceStream:
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
        engine._cheaperinference_client = client

        tokens = [
            t
            async for t in engine.stream(
                [Message(role=Role.USER, content="Hi")], model=_DEFAULT_MODEL
            )
        ]

        assert tokens == ["Hel", "lo"]
        sent = client.chat.completions.create.call_args.kwargs
        assert sent["model"] == "gpt-5.4-mini"
        assert sent["stream"] is True

    @pytest.mark.asyncio
    async def test_stream_without_a_client_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _make_cloud_engine(monkeypatch)
        with pytest.raises(EngineConnectionError, match="Cheaper Inference"):
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
        engine._cheaperinference_client = client

        chunks = [
            c
            async for c in engine._stream_full_openai(
                [Message(role=Role.USER, content="Hi")],
                model="cheaperinference/claude-sonnet-5",
                temperature=0.7,
                max_tokens=32,
            )
        ]

        assert client.chat.completions.create.call_args.kwargs["model"] == (
            "claude-sonnet-5"
        )
        assert [c.content for c in chunks] == ["hi"]


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class TestCheaperInferenceCatalog:
    def test_catalog_entries_match_the_popular_list(self) -> None:
        specs = {
            s.model_id: s for s in BUILTIN_MODELS if s.provider == "cheaperinference"
        }
        assert set(specs) == set(_CHEAPERINFERENCE_POPULAR)
        for spec in specs.values():
            assert spec.requires_api_key is True
            assert spec.supported_engines == ("cloud",)
            assert spec.context_length > 0


# ---------------------------------------------------------------------------
# Server-side cloud router
# ---------------------------------------------------------------------------


class TestCheaperInferenceServerRouting:
    def test_prefix_wins_over_the_slash_fallback(self) -> None:
        """The router's ``"/" in model`` fallback must not claim the
        prefixed ID."""
        assert cloud_router.get_provider(_DEFAULT_MODEL) == "cheaperinference"

    def test_prefixed_claude_is_not_classified_as_anthropic(self) -> None:
        assert cloud_router.get_provider("claude-sonnet-4-6") == "anthropic"
        assert (
            cloud_router.get_provider("cheaperinference/claude-sonnet-5")
            == "cheaperinference"
        )

    def test_is_cloud_model(self) -> None:
        assert cloud_router.is_cloud_model(_DEFAULT_MODEL) is True
