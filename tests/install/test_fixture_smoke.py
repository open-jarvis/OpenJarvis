"""Smoke test that the tmp_friday_ai_home fixture works."""

from __future__ import annotations

from pathlib import Path

from friday_ai.core import config as config_mod


def test_fixture_redirects_default_config_dir(tmp_friday_ai_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_DIR == tmp_friday_ai_home
    assert tmp_friday_ai_home.exists()
    assert (tmp_friday_ai_home / ".state").exists()
    assert (tmp_friday_ai_home / ".state" / "models").exists()


def test_fixture_redirects_config_path(tmp_friday_ai_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_PATH == tmp_friday_ai_home / "config.toml"
