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
            side_effect=lambda k, c: _FakeEngine(healthy=(k == "healthy")),
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


class TestMiningSidecarEngineHandoff:
    """Engine discovery picks up (or ignores) a mining sidecar at runtime."""

    def test_engine_discovery_picks_up_mining_sidecar(
        self, written_sidecar, monkeypatch
    ) -> None:
        """When a mining sidecar exists with vllm_endpoint, discovery
        registers a ``vllm-pearl-mining`` engine in the EngineRegistry.
        """
        from openjarvis.mining import _constants as mining_const

        monkeypatch.setattr(mining_const, "SIDECAR_PATH", written_sidecar)

        cfg = JarvisConfig()
        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=lambda k, c: _FakeEngine(healthy=True),
        ):
            discover_engines(cfg)

        assert EngineRegistry.contains("vllm-pearl-mining")

    def test_engine_discovery_no_mining_engine_when_sidecar_absent(
        self, tmp_path, monkeypatch
    ) -> None:
        """No mining sidecar → no ``vllm-pearl-mining`` engine registered."""
        from openjarvis.mining import _constants as mining_const

        missing = tmp_path / "no-such-mining.json"
        monkeypatch.setattr(mining_const, "SIDECAR_PATH", missing)

        cfg = JarvisConfig()
        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=lambda k, c: _FakeEngine(healthy=True),
        ):
            discover_engines(cfg)

        assert not EngineRegistry.contains("vllm-pearl-mining")

    def test_engine_discovery_skips_when_sidecar_missing_vllm_endpoint(
        self, tmp_path, monkeypatch
    ) -> None:
        """Sidecar present but no ``vllm_endpoint`` field → skip registration.

        Data-driven gate: a future cpu-pearl provider writes a sidecar that
        doesn't replace an inference engine (no vllm_endpoint field).
        """
        import json as _json

        sidecar = tmp_path / "mining.json"
        sidecar.write_text(
            _json.dumps(
                {
                    "provider": "cpu-pearl",
                    "wallet_address": "prl1q...",
                    "started_at": 1234567890,
                    # deliberately omit vllm_endpoint
                }
            )
        )
        from openjarvis.mining import _constants as mining_const

        monkeypatch.setattr(mining_const, "SIDECAR_PATH", sidecar)

        cfg = JarvisConfig()
        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=lambda k, c: _FakeEngine(healthy=True),
        ):
            discover_engines(cfg)

        assert not EngineRegistry.contains("vllm-pearl-mining")
