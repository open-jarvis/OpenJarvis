"""Smoke test that the tmp_openjarvis_home fixture works."""

from __future__ import annotations

from pathlib import Path

from openjarvis.core import config as config_mod


def test_fixture_redirects_default_config_dir(tmp_openjarvis_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_DIR == tmp_openjarvis_home
    assert tmp_openjarvis_home.exists()
    assert (tmp_openjarvis_home / ".state").exists()
    assert (tmp_openjarvis_home / ".state" / "models").exists()


def test_fixture_redirects_config_path(tmp_openjarvis_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_PATH == tmp_openjarvis_home / "config.toml"
