"""Tests for skills.sources config section."""

from __future__ import annotations

import openjarvis.core.config as config_module
from openjarvis.core.config import (
    DigestSectionConfig,
    SkillsConfig,
    SkillSourceConfig,
)


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


class TestSkillsSourcesTomlLoading:
    def test_loads_sources_as_dataclasses(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            """
[[skills.sources]]
source = "hermes"
filter = { category = ["research", "coding"] }

[[skills.sources]]
source = "github"
url = "https://github.com/example/skills"
auto_update = true
""".lstrip()
        )

        config_module.load_config.cache_clear()
        try:
            cfg = config_module.load_config(toml_file)
        finally:
            config_module.load_config.cache_clear()

        assert len(cfg.skills.sources) == 2

        hermes = cfg.skills.sources[0]
        assert isinstance(hermes, SkillSourceConfig)
        assert hermes.source == "hermes"
        assert hermes.filter == {"category": ["research", "coding"]}
        assert hermes.url == ""
        assert hermes.auto_update is False

        github = cfg.skills.sources[1]
        assert isinstance(github, SkillSourceConfig)
        assert github.source == "github"
        assert github.url == "https://github.com/example/skills"
        assert github.filter == {}
        assert github.auto_update is True

    def test_existing_instance_is_preserved(self):
        existing = SkillSourceConfig(source="hermes")
        target = SkillsConfig()

        config_module._apply_toml_section(target, {"sources": [existing]})

        assert target.sources[0] is existing

    def test_list_of_strings_remains_a_list(self):
        sources = ["gmail", "slack"]
        target = DigestSectionConfig()

        config_module._apply_toml_section(target, {"sources": sources})

        assert isinstance(target.sources, list)
        assert target.sources == sources
