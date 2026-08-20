"""Tests for Deep Research planner configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.core.config import (
    DeepResearchConfig,
    HardwareInfo,
    JarvisConfig,
    generate_default_toml,
    load_config,
    validate_config_key,
)


def test_deep_research_config_defaults_to_chat_selection() -> None:
    cfg = JarvisConfig()

    assert isinstance(cfg.deep_research, DeepResearchConfig)
    assert cfg.deep_research.engine == ""
    assert cfg.deep_research.model == ""


def test_loads_deep_research_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "home"))
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "\n".join(
            [
                "[deep_research]",
                'engine = "lmstudio"',
                'model = "qwen/qwen3-14b"',
            ]
        )
    )

    cfg = load_config(config_file)

    assert cfg.deep_research.engine == "lmstudio"
    assert cfg.deep_research.model == "qwen/qwen3-14b"


def test_deep_research_keys_are_settable() -> None:
    assert validate_config_key("deep_research.engine") is str
    assert validate_config_key("deep_research.model") is str


def test_default_toml_documents_deep_research_override() -> None:
    toml = generate_default_toml(HardwareInfo())

    assert "# [deep_research]" in toml
    assert '# engine = ""' in toml
    assert '# model = ""' in toml
