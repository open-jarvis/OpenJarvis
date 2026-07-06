"""Tests for web Deep Research planner engine selection."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from openjarvis.agents.research_loop import DEFAULT_PLANNER_MODEL
from openjarvis.core.config import JarvisConfig
from openjarvis.server import research_router


class _DummyEngine:
    def __init__(self, servable: bool = True) -> None:
        self.servable = servable

    def can_serve(self, model: str) -> bool:
        return self.servable


def test_resolve_planner_config_uses_chat_defaults() -> None:
    cfg = JarvisConfig()
    cfg.engine.default = "lmstudio"
    cfg.intelligence.default_model = "local-model"

    assert research_router._resolve_planner_config(cfg) == (
        "lmstudio",
        "local-model",
    )


def test_resolve_planner_config_prefers_active_chat_runtime() -> None:
    cfg = JarvisConfig()
    cfg.engine.default = "ollama"
    cfg.intelligence.default_model = ""

    assert research_router._resolve_planner_config(
        cfg,
        active_engine_key="lmstudio",
        active_model="server-model",
        request_model="selected-model",
    ) == (
        "lmstudio",
        "selected-model",
    )


def test_resolve_planner_config_uses_server_model_before_legacy_default() -> None:
    cfg = JarvisConfig()
    cfg.engine.default = "ollama"
    cfg.intelligence.default_model = ""
    cfg.server.model = "serve-model"

    assert research_router._resolve_planner_config(cfg) == (
        "ollama",
        "serve-model",
    )


def test_resolve_planner_config_allows_deep_research_override() -> None:
    cfg = JarvisConfig()
    cfg.engine.default = "lmstudio"
    cfg.intelligence.default_model = "chat-model"
    cfg.deep_research.engine = "vllm"
    cfg.deep_research.model = "planner-model"

    assert research_router._resolve_planner_config(cfg) == (
        "vllm",
        "planner-model",
    )


def test_resolve_planner_config_allows_partial_model_override() -> None:
    cfg = JarvisConfig()
    cfg.engine.default = "lmstudio"
    cfg.intelligence.default_model = "chat-model"
    cfg.deep_research.model = "planner-model"

    assert research_router._resolve_planner_config(cfg) == (
        "lmstudio",
        "planner-model",
    )


def test_resolve_planner_config_allows_partial_engine_override() -> None:
    cfg = JarvisConfig()
    cfg.engine.default = "lmstudio"
    cfg.intelligence.default_model = "chat-model"
    cfg.deep_research.engine = "vllm"

    assert research_router._resolve_planner_config(cfg) == (
        "vllm",
        "chat-model",
    )


def test_resolve_planner_config_keeps_legacy_fallback_when_unconfigured() -> None:
    cfg = JarvisConfig()
    cfg.engine.default = ""
    cfg.intelligence.default_model = ""

    assert research_router._resolve_planner_config(cfg) == (
        "ollama",
        DEFAULT_PLANNER_MODEL,
    )


def test_build_planner_engine_uses_configured_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = JarvisConfig()
    cfg.engine.default = "lmstudio"
    cfg.intelligence.default_model = "local-model"
    engine = _DummyEngine()
    calls: list[tuple[str | None, str | None]] = []

    def fake_get_engine(
        config: JarvisConfig,
        engine_key: str | None = None,
        model: str | None = None,
    ) -> tuple[str, _DummyEngine]:
        calls.append((engine_key, model))
        return "lmstudio", engine

    monkeypatch.setattr(research_router, "get_engine", fake_get_engine)

    engine_key, resolved_engine, model = research_router._build_planner_engine(cfg)

    assert calls == [("lmstudio", "local-model")]
    assert engine_key == "lmstudio"
    assert resolved_engine is engine
    assert model == "local-model"


def test_build_planner_engine_uses_active_engine_without_config_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = JarvisConfig()
    cfg.engine.default = "ollama"
    cfg.intelligence.default_model = ""
    active_engine = _DummyEngine()

    def fail_get_engine(*args: object, **kwargs: object) -> None:
        raise AssertionError("should use the live app engine")

    monkeypatch.setattr(research_router, "get_engine", fail_get_engine)

    engine_key, resolved_engine, model = research_router._build_planner_engine(
        cfg,
        active_engine=active_engine,
        active_engine_key="lmstudio",
        active_model="server-model",
        request_model="selected-model",
    )

    assert engine_key == "lmstudio"
    assert resolved_engine is active_engine
    assert model == "selected-model"


def test_build_planner_engine_rejects_active_engine_that_cannot_serve_model() -> None:
    cfg = JarvisConfig()

    with pytest.raises(RuntimeError, match="selected-model"):
        research_router._build_planner_engine(
            cfg,
            active_engine=_DummyEngine(servable=False),
            active_engine_key="cloud",
            request_model="selected-model",
        )


def test_build_planner_engine_honors_explicit_deep_research_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = JarvisConfig()
    cfg.deep_research.engine = "vllm"
    cfg.deep_research.model = "planner-model"
    active_engine = _DummyEngine()
    planner_engine = _DummyEngine()

    def fake_get_engine(
        config: JarvisConfig,
        engine_key: str | None = None,
        model: str | None = None,
    ) -> tuple[str, _DummyEngine]:
        assert engine_key == "vllm"
        assert model == "planner-model"
        return "vllm", planner_engine

    monkeypatch.setattr(research_router, "get_engine", fake_get_engine)

    engine_key, resolved_engine, model = research_router._build_planner_engine(
        cfg,
        active_engine=active_engine,
        active_engine_key="lmstudio",
        active_model="chat-model",
        request_model="selected-model",
    )

    assert engine_key == "vllm"
    assert resolved_engine is planner_engine
    assert model == "planner-model"


def test_research_route_passes_live_engine_and_selected_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    active_engine = _DummyEngine()

    def fake_stream(query: str, **kwargs: object):
        captured["query"] = query
        captured.update(kwargs)

        async def gen():
            yield 'data: {"type":"done","usage":{}}\n\n'

        return gen()

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=active_engine,
                engine_name="lmstudio",
                model="server-model",
            )
        )
    )

    monkeypatch.setattr(research_router, "_stream_research", fake_stream)

    response = asyncio.run(
        research_router.research(
            research_router.ResearchRequest(
                query="find notes",
                model="selected-model",
            ),
            request,  # type: ignore[arg-type]
        )
    )

    assert response.media_type == "text/event-stream"
    assert captured == {
        "query": "find notes",
        "active_engine": active_engine,
        "active_engine_key": "lmstudio",
        "active_model": "server-model",
        "request_model": "selected-model",
    }


def test_build_planner_engine_rejects_fallback_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = JarvisConfig()
    cfg.engine.default = "lmstudio"
    cfg.intelligence.default_model = "local-model"

    def fake_get_engine(
        config: JarvisConfig,
        engine_key: str | None = None,
        model: str | None = None,
    ) -> tuple[str, _DummyEngine]:
        return "ollama", _DummyEngine()

    monkeypatch.setattr(research_router, "get_engine", fake_get_engine)

    with pytest.raises(RuntimeError, match="lmstudio"):
        research_router._build_planner_engine(cfg)


def test_build_planner_engine_rejects_unavailable_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = JarvisConfig()
    cfg.engine.default = "lmstudio"
    cfg.intelligence.default_model = "local-model"

    monkeypatch.setattr(research_router, "get_engine", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="local-model"):
        research_router._build_planner_engine(cfg)
