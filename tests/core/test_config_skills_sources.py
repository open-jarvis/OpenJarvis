"""Tests for skills.sources config section."""

from __future__ import annotations

from openjarvis.core.config import SkillsConfig, SkillSourceConfig


class TestSkillSourceConfig:
    def test_default_filter_empty(self):
        cfg = SkillSourceConfig(source="hermes")
        assert cfg.source == "hermes"
        assert cfg.filter == {}
        assert cfg.auto_update is False
        assert cfg.url == ""

    def test_with_filter(self):
        cfg = SkillSourceConfig(
            source="hermes",
            filter={"category": ["research", "coding"]},
        )
        assert cfg.filter["category"] == ["research", "coding"]


class TestSkillsConfigWithSources:
    def test_default_no_sources(self):
        cfg = SkillsConfig()
        assert cfg.enabled is True
        assert cfg.auto_sync is False
        assert cfg.sources == []

    def test_auto_sync_can_be_enabled(self):
        cfg = SkillsConfig(auto_sync=True)
        assert cfg.auto_sync is True

    def test_can_add_sources(self):
        cfg = SkillsConfig(
            sources=[
                SkillSourceConfig(source="hermes"),
                SkillSourceConfig(source="openclaw"),
            ]
        )
        assert len(cfg.sources) == 2
        assert cfg.sources[0].source == "hermes"
