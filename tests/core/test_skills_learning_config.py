"""Tests for SkillsLearningConfig and its wiring into LearningConfig."""

from __future__ import annotations

from openjarvis.core.config import LearningConfig, SkillsLearningConfig


class TestSkillsLearningConfig:
    def test_defaults(self):
        cfg = SkillsLearningConfig()
        assert cfg.auto_optimize is False
        assert cfg.optimizer == "dspy"
        assert cfg.min_traces_per_skill == 20
        assert cfg.optimization_interval_seconds == 86400
        assert cfg.overlay_dir == "~/.openjarvis/learning/skills/"

    def test_can_be_constructed_with_all_fields(self):
        cfg = SkillsLearningConfig(
            auto_optimize=True,
            optimizer="gepa",
            min_traces_per_skill=10,
            optimization_interval_seconds=3600,
            overlay_dir="/tmp/overlays/",
        )
        assert cfg.auto_optimize is True
        assert cfg.optimizer == "gepa"
        assert cfg.min_traces_per_skill == 10
        assert cfg.optimization_interval_seconds == 3600
        assert cfg.overlay_dir == "/tmp/overlays/"


class TestLearningConfigSkillsField:
    def test_skills_field_present(self):
        cfg = LearningConfig()
        assert hasattr(cfg, "skills")
        assert isinstance(cfg.skills, SkillsLearningConfig)

    def test_skills_field_default_disabled(self):
        cfg = LearningConfig()
        assert cfg.skills.auto_optimize is False
