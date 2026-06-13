"""Tests for ask/chat engine resolution."""

from __future__ import annotations

import sys
from typing import Any

from openjarvis.core.config import JarvisConfig
from openjarvis.engine._base import InferenceEngine


class _FakeEngine(InferenceEngine):
    engine_id = "fake"

    def __init__(self, healthy: bool = True) -> None:
        self._is_healthy = healthy

    def health(self) -> bool:
        return self._is_healthy

    def generate(self, *args, **kwargs) -> str:
        return "fake output"

    def list_models(self) -> list[str]:
        return ["fake-model"]

    def stream(self, *args, **kwargs):
        yield "fake output"


def test_ask_engine_resolution_prefers_explicit_cli_key(monkeypatch: Any) -> None:
    # Import the module explicitly to bypass the __init__.py shadowing
    from openjarvis.cli import ask

    ask_mod = sys.modules["openjarvis.cli.ask"]

    cfg = JarvisConfig()
    cfg.engine.default = "ollama"
    cfg.intelligence.preferred_engine = "ollama"

    # Mock get_engine to just return the requested key
    def _mock_get_engine(
        config: JarvisConfig, key: str | None, model: str | None = None
    ) -> tuple[str, _FakeEngine] | None:
        return (key or "discovered", _FakeEngine())

    monkeypatch.setattr(ask_mod, "get_engine", _mock_get_engine)
    monkeypatch.setattr(ask_mod, "load_config", lambda: cfg)
    monkeypatch.setattr("sys.exit", lambda code: None)
    monkeypatch.setattr(ask_mod, "print_banner", lambda **kwargs: None)

    # We just want to spy on the resolved engine, but the easiest way is to
    # wrap get_engine
    resolved_key = None
    original_get_engine = _mock_get_engine

    def _spy_get_engine(
        config: JarvisConfig, key: str | None, model: str | None = None
    ) -> tuple[str, _FakeEngine] | None:
        nonlocal resolved_key
        resolved_key = key
        return original_get_engine(config, key, model=model)

    monkeypatch.setattr(ask_mod, "get_engine", _spy_get_engine)
    monkeypatch.setattr(ask_mod, "_run_research", lambda **kwargs: None)

    # We stub enough to get past engine resolution and then raise to stop execution
    def _mock_score_complexity(*args: Any, **kwargs: Any) -> Any:
        from openjarvis.learning.routing.complexity import ComplexityResult

        return ComplexityResult(
            score=0.5, tier="basic", suggested_max_tokens=100, signals=[]
        )

    monkeypatch.setattr(
        "openjarvis.learning.routing.complexity.score_complexity",
        _mock_score_complexity,
    )

    class StopExecution(Exception):
        pass

    def _mock_setup_security(*args, **kwargs):
        raise StopExecution()

    monkeypatch.setattr("openjarvis.security.setup_security", _mock_setup_security)

    import click

    try:
        with click.Context(ask):
            ask.callback(
                query=("hi",),
                model_name=None,
                engine_key="explicit_cli_key",
                temperature=None,
                max_tokens=None,
                output_json=False,
                no_stream=False,
                no_context=True,
                agent_name="none",
                tool_names=None,
                enable_profile=False,
                research_mode=False,
                knowledge_db=None,
                persona_name=None,
            )
    except StopExecution:
        pass

    assert resolved_key == "explicit_cli_key"


def test_ask_engine_resolution_prefers_configured_preferred_engine(
    monkeypatch: Any,
) -> None:
    from openjarvis.cli import ask

    ask_mod = sys.modules["openjarvis.cli.ask"]

    cfg = JarvisConfig()
    cfg.engine.default = "fallback_engine"
    cfg.intelligence.preferred_engine = "preferred_engine"

    resolved_key = None

    def _spy_get_engine(
        config: JarvisConfig, key: str | None, model: str | None = None
    ) -> tuple[str, _FakeEngine] | None:
        nonlocal resolved_key
        resolved_key = key
        return ("dummy", _FakeEngine())

    monkeypatch.setattr(ask_mod, "get_engine", _spy_get_engine)
    monkeypatch.setattr(ask_mod, "load_config", lambda: cfg)
    monkeypatch.setattr("sys.exit", lambda code: None)
    monkeypatch.setattr(ask_mod, "print_banner", lambda **kwargs: None)
    monkeypatch.setattr(ask_mod, "_run_research", lambda **kwargs: None)

    def _mock_score_complexity(*args: Any, **kwargs: Any) -> Any:
        from openjarvis.learning.routing.complexity import ComplexityResult

        return ComplexityResult(
            score=0.5, tier="basic", suggested_max_tokens=100, signals=[]
        )

    monkeypatch.setattr(
        "openjarvis.learning.routing.complexity.score_complexity",
        _mock_score_complexity,
    )

    class StopExecution(Exception):
        pass

    def _mock_setup_security(*args, **kwargs):
        raise StopExecution()

    monkeypatch.setattr("openjarvis.security.setup_security", _mock_setup_security)

    import click

    try:
        with click.Context(ask):
            ask.callback(
                query=("hi",),
                model_name=None,
                engine_key=None,
                temperature=None,
                max_tokens=None,
                output_json=False,
                no_stream=False,
                no_context=True,
                agent_name="none",
                tool_names=None,
                enable_profile=False,
                research_mode=False,
                knowledge_db=None,
                persona_name=None,
            )
    except StopExecution:
        pass

    assert resolved_key == "preferred_engine"


def test_ask_engine_resolution_falls_back_to_default_engine(monkeypatch: Any) -> None:
    from openjarvis.cli import ask

    ask_mod = sys.modules["openjarvis.cli.ask"]

    cfg = JarvisConfig()
    cfg.engine.default = "fallback_engine"
    cfg.intelligence.preferred_engine = ""

    resolved_key = None

    def _spy_get_engine(
        config: JarvisConfig, key: str | None, model: str | None = None
    ) -> tuple[str, _FakeEngine] | None:
        nonlocal resolved_key
        resolved_key = key
        return ("dummy", _FakeEngine())

    monkeypatch.setattr(ask_mod, "get_engine", _spy_get_engine)
    monkeypatch.setattr(ask_mod, "load_config", lambda: cfg)
    monkeypatch.setattr("sys.exit", lambda code: None)
    monkeypatch.setattr(ask_mod, "print_banner", lambda **kwargs: None)
    monkeypatch.setattr(ask_mod, "_run_research", lambda **kwargs: None)

    def _mock_score_complexity(*args: Any, **kwargs: Any) -> Any:
        from openjarvis.learning.routing.complexity import ComplexityResult

        return ComplexityResult(
            score=0.5, tier="basic", suggested_max_tokens=100, signals=[]
        )

    monkeypatch.setattr(
        "openjarvis.learning.routing.complexity.score_complexity",
        _mock_score_complexity,
    )

    class StopExecution(Exception):
        pass

    def _mock_setup_security(*args, **kwargs):
        raise StopExecution()

    monkeypatch.setattr("openjarvis.security.setup_security", _mock_setup_security)

    import click

    try:
        with click.Context(ask):
            ask.callback(
                query=("hi",),
                model_name=None,
                engine_key=None,
                temperature=None,
                max_tokens=None,
                output_json=False,
                no_stream=False,
                no_context=True,
                agent_name="none",
                tool_names=None,
                enable_profile=False,
                research_mode=False,
                knowledge_db=None,
                persona_name=None,
            )
    except StopExecution:
        pass

    assert resolved_key == "fallback_engine"
