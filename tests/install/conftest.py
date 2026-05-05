"""Test fixtures for installer / cold-start refresh tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_openjarvis_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``DEFAULT_CONFIG_DIR`` at a tmpdir for isolated tests.

    Yields the directory; teardown is automatic via tmp_path.
    """
    home = tmp_path / ".openjarvis"
    home.mkdir()
    (home / ".state").mkdir()
    (home / ".state" / "models").mkdir()
    monkeypatch.setattr(
        "openjarvis.core.config.DEFAULT_CONFIG_DIR", home
    )
    monkeypatch.setattr(
        "openjarvis.core.config.DEFAULT_CONFIG_PATH", home / "config.toml"
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    return home
