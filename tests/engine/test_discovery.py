"""Tests for engine discovery."""

from __future__ import annotations

from unittest import mock

from openjarvis.core.config import JarvisConfig
from openjarvis.core.registry import EngineRegistry
from openjarvis.engine._base import InferenceEngine
from openjarvis.engine._discovery import (
    _make_engine,
    discover_engines,
    discover_models,
    get_engine,
)
from openjarvis.engine.litellm import LiteLLMEngine


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

    def test_health_checks_run_concurrently(self) -> None:
        """Regression for #263 — discovery must probe engines in parallel.

        Each engine's health() does a blocking network probe with its own
        timeout, so serial discovery cost = sum of probe times. With N
        engines each sleeping S, parallel discovery wall-time must stay far
        below N*S (closer to S). We don't measure real time precisely (CI is
        noisy); instead we record concurrency: the max number of health()
        calls in flight simultaneously must exceed 1.
        """
        import threading
        import time

        n_engines = 6
        sleep_s = 0.15
        for i in range(n_engines):
            _reg(f"slow{i}", f"slow{i}")

        lock = threading.Lock()
        in_flight = 0
        max_in_flight = 0

        class _SlowEngine(_FakeEngine):
            def health(self) -> bool:
                nonlocal in_flight, max_in_flight
                with lock:
                    in_flight += 1
                    max_in_flight = max(max_in_flight, in_flight)
                time.sleep(sleep_s)
                with lock:
                    in_flight -= 1
                return True

        cfg = JarvisConfig()
        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=lambda k, c: _SlowEngine(healthy=True),
        ):
            start = time.monotonic()
            result = discover_engines(cfg)
            elapsed = time.monotonic() - start

        # All slow engines were discovered (plus any real registered ones).
        assert len([r for r in result if r[0].startswith("slow")]) == n_engines
        # Concurrency actually happened — more than one probe overlapped.
        assert max_in_flight > 1, f"probes ran serially (max_in_flight={max_in_flight})"
        # Wall-time is well under the serial sum (n*sleep), allowing slack.
        assert elapsed < n_engines * sleep_s * 0.7


class TestDiscoverModels:
    def test_aggregate_models(self) -> None:
        e1 = _FakeEngine(models=["m1", "m2"])
        e2 = _FakeEngine(models=["m3"])
        result = discover_models([("ollama", e1), ("vllm", e2)])
        assert result == {"ollama": ["m1", "m2"], "vllm": ["m3"]}


class TestLiteLLMDiscovery:
    def test_configured_default_model_is_advertised(self) -> None:
        """Regression for #713: discovery must configure LiteLLM's model.

        LiteLLM cannot enumerate every model supported by every provider, so
        ``LiteLLMEngine.list_models()`` advertises the configured default
        model.  Dropping that value while constructing the engine leaves the
        API and Web UI with an empty model list.
        """
        cfg = JarvisConfig()
        cfg.intelligence.default_model = "groq/llama-3.3-70b-versatile"
        EngineRegistry.register_value("litellm", LiteLLMEngine)

        engine = _make_engine("litellm", cfg)

        assert engine.list_models() == ["groq/llama-3.3-70b-versatile"]


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

    def test_explicit_unavailable_key_does_not_substitute(self, caplog) -> None:
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
            result = get_engine(cfg, engine_key="requested")

        assert result is None
        assert "Requested engine 'requested' is unavailable" in caplog.text

    def test_unknown_explicit_key_does_not_substitute(self, caplog) -> None:
        cfg = JarvisConfig()

        result = get_engine(cfg, engine_key="not-registered")

        assert result is None
        assert "not registered" in caplog.text

    def test_default_fallback_prefers_same_engine_class(self) -> None:
        _reg("bad-local", "bad-local")
        _reg("a-cloud", "a-cloud")
        _reg("z-local", "z-local")

        class _Cloud(_FakeEngine):
            is_cloud = True

        cfg = JarvisConfig()
        cfg.engine.default = "bad-local"

        def _make(k, c):  # noqa: ANN001
            if k == "bad-local":
                return _FakeEngine(healthy=False)
            if k == "a-cloud":
                return _Cloud(healthy=True)
            return _FakeEngine(healthy=(k == "z-local"))

        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=_make,
        ):
            result = get_engine(cfg)

        assert result is not None
        assert result[0] == "z-local"

    def test_cross_boundary_default_fallback_is_named(self, caplog) -> None:
        _reg("bad-local", "bad-local")
        _reg("cloud-only", "cloud-only")

        class _Cloud(_FakeEngine):
            is_cloud = True

        cfg = JarvisConfig()
        cfg.engine.default = "bad-local"

        def _make(k, c):  # noqa: ANN001
            if k == "bad-local":
                return _FakeEngine(healthy=False)
            return _Cloud(healthy=(k == "cloud-only"))

        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=_make,
        ):
            result = get_engine(cfg)

        assert result is not None
        assert result[0] == "cloud-only"
        assert "across the local/cloud boundary" in caplog.text

    def test_skips_engine_that_cannot_serve_model(self) -> None:
        """#532: a healthy engine that can't serve the requested model is
        skipped for one that can — this is what stops the cloud fallback being
        chosen (when the local engine is down) for a model whose provider
        client is missing.
        """
        _reg("picky", "picky")
        _reg("local", "local")

        class _Picky(_FakeEngine):
            def can_serve(self, model: str) -> bool:
                return model == "servable"

        cfg = JarvisConfig()
        cfg.engine.default = "picky"

        def _make(k, c):  # noqa: ANN001
            if k == "picky":
                return _Picky(healthy=True)
            return _FakeEngine(healthy=(k == "local"))

        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=_make,
        ):
            # "picky" is healthy but cannot serve "other" -> fall back to "local"
            result = get_engine(cfg, model="other")
        assert result is not None
        assert result[0] == "local"

    def test_dummy_openai_key_does_not_misroute_local_model(
        self, monkeypatch: object
    ) -> None:
        """#335: a present-but-dummy OPENAI_API_KEY + a down local engine must
        NOT cause a local Ollama model to be routed to the cloud engine.

        Before the fix, CloudEngine.can_serve('qwen3.5:0.8b') returned True
        whenever any OpenAI client existed (even a junk key), so get_engine
        picked 'cloud' and the request later died with "OpenAI client not
        available". With the strict _client_for_model fall-through it returns
        None for unrecognized names, so get_engine declines cloud and (with the
        local engine down) returns None — surfacing a "start your local engine"
        failure instead.
        """
        from openjarvis.engine.cloud import CloudEngine

        _reg("ollama", "ollama")
        EngineRegistry.register_value("cloud", CloudEngine)

        cfg = JarvisConfig()
        cfg.engine.default = "ollama"

        def _make(k, c):  # noqa: ANN001
            if k == "ollama":
                # Local engine is down (post-restart Ollama not yet up).
                return _FakeEngine(healthy=False, models=["qwen3.5:0.8b"])
            # Real CloudEngine with only a (dummy) OpenAI client wired.
            eng = CloudEngine.__new__(CloudEngine)
            for name in (
                "_openai_client",
                "_anthropic_client",
                "_google_client",
                "_openrouter_client",
                "_minimax_client",
                "_deepseek_client",
                "_codex_client",
            ):
                setattr(eng, name, object() if name == "_openai_client" else None)
            return eng

        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=_make,
        ):
            result = get_engine(cfg, model="qwen3.5:0.8b")
        # Cloud must NOT be selected for a local model name.
        assert result is None

    def test_model_none_preserves_model_agnostic_selection(self) -> None:
        """model=None keeps the legacy behaviour: first healthy engine wins."""
        _reg("primary", "primary")

        cfg = JarvisConfig()
        cfg.engine.default = "primary"

        with mock.patch(
            "openjarvis.engine._discovery._make_engine",
            side_effect=lambda k, c: _FakeEngine(healthy=True),  # noqa: ANN001
        ):
            result = get_engine(cfg, model=None)
        assert result is not None
        assert result[0] == "primary"


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
