"""Tests for LearningConfig and its integration into JarvisConfig."""

from __future__ import annotations

from pathlib import Path

from openjarvis.core.config import (
    HardwareInfo,
    JarvisConfig,
    LearningConfig,
    generate_default_toml,
    load_config,
)


class TestLearningConfig:
    def test_defaults(self) -> None:
        cfg = LearningConfig()
        assert cfg.enabled is False
        assert cfg.update_interval == 100
        assert cfg.auto_update is False
        assert cfg.routing.policy == "heuristic"
        assert cfg.intelligence.policy == "none"
        assert cfg.agent.policy == "none"
        assert cfg.metrics.accuracy_weight == 0.6
        # Backward-compat properties
        assert cfg.default_policy == "heuristic"

    def test_backward_compat_custom_values(self) -> None:
        cfg = LearningConfig()
        cfg.default_policy = "grpo"
        cfg.reward_weights = "latency=0.4,cost=0.3,efficiency=0.3"
        assert cfg.routing.policy == "grpo"
        assert cfg.metrics.latency_weight == 0.4
        assert cfg.metrics.cost_weight == 0.3
        assert cfg.metrics.efficiency_weight == 0.3

    def test_jarvis_config_has_learning(self) -> None:
        cfg = JarvisConfig()
        assert hasattr(cfg, "learning")
        assert isinstance(cfg.learning, LearningConfig)
        assert cfg.learning.routing.policy == "heuristic"
        assert cfg.learning.default_policy == "heuristic"  # backward-compat

    def test_toml_loading_with_learning(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[learning]\ndefault_policy = "grpo"\nreward_weights = "latency=0.5"\n'
        )
        cfg = load_config(toml_file)
        assert cfg.learning.routing.policy == "grpo"
        assert cfg.learning.metrics.latency_weight == 0.5

    def test_toml_loading_nested(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[learning]\nenabled = true\n\n"
            '[learning.routing]\npolicy = "learned"\n\n'
            "[learning.metrics]\nlatency_weight = 0.5\n"
        )
        cfg = load_config(toml_file)
        assert cfg.learning.enabled is True
        assert cfg.learning.routing.policy == "learned"
        assert cfg.learning.metrics.latency_weight == 0.5

    def test_toml_loading_without_learning(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text("[engine]\n")
        cfg = load_config(toml_file)
        assert cfg.learning.routing.policy == "heuristic"

    def test_generate_default_toml_includes_learning(self) -> None:
        hw = HardwareInfo()
        toml_str = generate_default_toml(hw)
        assert "[learning]" in toml_str
        assert "[learning.routing]" in toml_str
        assert 'policy = "heuristic"' in toml_str
