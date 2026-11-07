"""Tests for channel configuration."""

from __future__ import annotations

import textwrap
from pathlib import Path

from friday_ai.core.config import ChannelConfig, FridayConfig, load_config


class TestChannelConfigDefaults:
    def test_channel_config_defaults(self) -> None:
        cfg = ChannelConfig()
        assert cfg.enabled is False
        assert cfg.default_agent == "simple"

    def test_channel_config_custom(self) -> None:
        cfg = ChannelConfig(
            enabled=True,
            default_agent="orchestrator",
        )
        assert cfg.enabled is True
        assert cfg.default_agent == "orchestrator"


class TestChannelConfigInFridayConfig:
    def test_channel_config_in_friday_config(self) -> None:
        cfg = FridayConfig()
        assert hasattr(cfg, "channel")
        assert isinstance(cfg.channel, ChannelConfig)

    def test_friday_config_channel_defaults(self) -> None:
        cfg = FridayConfig()
        assert cfg.channel.enabled is False
        assert cfg.channel.default_channel == ""


class TestLoadConfigWithChannel:
    def test_load_config_with_channel_section(self, tmp_path: Path) -> None:
        """Create a temp TOML with [channel] section and verify values."""
        toml_content = textwrap.dedent("""\
            [channel]
            enabled = true
            default_agent = "orchestrator"
        """)
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        cfg = load_config(path=config_file)
        assert cfg.channel.enabled is True
        assert cfg.channel.default_agent == "orchestrator"

    def test_load_config_without_channel_section(self, tmp_path: Path) -> None:
        """When no [channel] section, defaults should apply."""
        toml_content = textwrap.dedent("""\
            [engine]
            default = "ollama"
        """)
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        cfg = load_config(path=config_file)
        assert cfg.channel.enabled is False
        assert cfg.channel.default_channel == ""

    def test_load_config_partial_channel_section(self, tmp_path: Path) -> None:
        """Partial [channel] section overlays only specified fields."""
        toml_content = textwrap.dedent("""\
            [channel]
            enabled = true
        """)
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        cfg = load_config(path=config_file)
        assert cfg.channel.enabled is True
        # Non-specified fields keep defaults
        assert cfg.channel.default_agent == "simple"
