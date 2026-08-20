"""Phase 5 foundation tests — BenchmarkRegistry and config."""

from __future__ import annotations

import pytest

from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.core.registry import BenchmarkRegistry


class TestBenchmarkRegistry:
    def test_register_and_get(self):
        BenchmarkRegistry.register_value("test-bench", "dummy")
        assert BenchmarkRegistry.get("test-bench") == "dummy"

    def test_keys(self):
        BenchmarkRegistry.register_value("a", 1)
        BenchmarkRegistry.register_value("b", 2)
        assert set(BenchmarkRegistry.keys()) == {"a", "b"}

    def test_contains(self):
        BenchmarkRegistry.register_value("present", True)
        assert BenchmarkRegistry.contains("present")
        assert not BenchmarkRegistry.contains("absent")

    def test_duplicate_raises(self):
        BenchmarkRegistry.register_value("dup", 1)
        with pytest.raises(ValueError, match="already has an entry"):
            BenchmarkRegistry.register_value("dup", 2)


class TestConfigPhase5:
    def test_jarvis_config_loads(self):
        cfg = JarvisConfig()
        assert cfg.engine is not None
        assert cfg.learning is not None

    def test_benchmark_registry_importable(self):
        from openjarvis.core.registry import BenchmarkRegistry

        assert BenchmarkRegistry is not None

    def test_registry_isolation(self):
        """BenchmarkRegistry entries don't leak into other registries."""
        from openjarvis.core.registry import ModelRegistry

        BenchmarkRegistry.register_value("iso-test", "bench-value")
        with pytest.raises(KeyError):
            ModelRegistry.get("iso-test")

    def test_load_config_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "home"))
        cfg = load_config(tmp_path / "missing-config.toml")
        assert isinstance(cfg, JarvisConfig)
