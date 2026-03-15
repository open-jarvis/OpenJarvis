"""Tests for engine discovery."""

from __future__ import annotations

from unittest import mock

from openjarvis.core.config import JarvisConfig
from openjarvis.core.registry import EngineRegistry
from openjarvis.engine._base import InferenceEngine
from openjarvis.engine._discovery import (
    discover_engines,
    discover_models,
    get_engine,
)


class _FakeEngine(InferenceEngine):
    engine_id = "fake"

    def __init__(
        self,
        *,
        healthy: bool = True,
        models: list | None = None,
        **kwargs,  # noqa: ANN003
    ) -> None:
        self._healthy = healthy
        self._models = models or []

    def generate(self, messages, *, model, **kwargs):  # noqa: ANN001, ANN003
        return {"content": "ok", "usage": {}}

    async def stream(self, messages, *, model, **kwargs):  # noqa: ANN001, ANN003
        yield "ok"

    def list_models(self) -> list:
        return self._models

    def health(self) -> bool:
        return self._healthy


def _reg(key: str, eid: str) -> None:
    """Register a fake engine type under *key*."""
    cls = type(key.title(), (_FakeEngine,), {"engine_id": eid})
    EngineRegistry.register_value(key, cls)


class TestDiscoverEngines:
    def test_only_healthy_returned(self) -> None:
        _reg("healthy", "healthy")
        _reg("sick", "sick")

        cfg = JarvisConfig()
        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=lambda k, c: _FakeEngine(
                healthy=(k == "healthy")
            ),
        ):
            result = discover_engines(cfg)
        assert len(result) == 1
        assert result[0][0] == "healthy"

    def test_default_engine_first(self) -> None:
        _reg("a", "a")
        _reg("b", "b")

        cfg = JarvisConfig()
        cfg.engine.default = "b"
        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=lambda k, c: _FakeEngine(healthy=True),
        ):
            result = discover_engines(cfg)
        assert result[0][0] == "b"


class TestDiscoverModels:
    def test_aggregate_models(self) -> None:
        e1 = _FakeEngine(models=["m1", "m2"])
        e2 = _FakeEngine(models=["m3"])
        result = discover_models([("ollama", e1), ("vllm", e2)])
        assert result == {"ollama": ["m1", "m2"], "vllm": ["m3"]}


class TestGetEngine:
    def test_fallback_when_default_unhealthy(self) -> None:
        _reg("bad", "bad")
        _reg("good", "good")

        cfg = JarvisConfig()
        cfg.engine.default = "bad"

        def _make(k, c):  # noqa: ANN001
            return _FakeEngine(healthy=(k == "good"))

        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=_make,
        ):
            result = get_engine(cfg)
        assert result is not None
        assert result[0] == "good"

    def test_explicit_key_falls_back_to_any_healthy(self) -> None:
        """When an explicit engine_key fails, fallback to any healthy engine.

        Fixes #73: LM Studio running but not found because get_engine()
        returned None when the explicitly-requested key failed.
        """
        _reg("requested", "requested")
        _reg("running", "running")

        cfg = JarvisConfig()
        cfg.engine.default = "requested"

        def _make(k, c):  # noqa: ANN001
            return _FakeEngine(healthy=(k == "running"))

        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=_make,
        ):
            # Explicit key "requested" is unhealthy, but "running" is healthy
            result = get_engine(cfg, engine_key="requested")
        assert result is not None
        assert result[0] == "running"
