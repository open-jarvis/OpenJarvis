"""Test fixtures for installer / cold-start refresh tests."""

from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def tmp_openjarvis_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``DEFAULT_CONFIG_DIR`` at a tmpdir for isolated tests.

    Returns the directory; teardown is automatic via tmp_path.
    """
    home = tmp_path / ".openjarvis"
    home.mkdir()
    (home / ".state").mkdir()
    (home / ".state" / "models").mkdir()
    (home / ".scripts").mkdir()
    config_path = home / "config.toml"
    monkeypatch.setattr("openjarvis.core.config.DEFAULT_CONFIG_DIR", home)
    monkeypatch.setattr("openjarvis.core.config.DEFAULT_CONFIG_PATH", config_path)
    # Also patch init_cmd's module-level bindings (imported with ``from ... import``).
    monkeypatch.setattr("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", home)
    monkeypatch.setattr("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path)
    # Patch doctor_cmd's module-level bindings.
    monkeypatch.setattr("openjarvis.cli.doctor_cmd.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    # These tests drive state purely via marker files; pin the runtime Rust
    # import check off so a built extension in the dev venv can't flip
    # "pending"/"failed" to "ready" behind their backs.
    monkeypatch.setattr("openjarvis._rust_bridge.RUST_AVAILABLE", False)
    return home


@pytest.fixture
def write_model_marker(tmp_openjarvis_home: Path) -> Callable[[str, str], Path]:
    """Write a portable model-state marker and return its path."""

    def write(model_id: str, state: str) -> Path:
        key = base64.urlsafe_b64encode(model_id.encode("utf-8")).decode().rstrip("=")
        marker_dir = tmp_openjarvis_home / ".state" / "models" / "v1"
        marker_dir.mkdir(exist_ok=True)
        marker = marker_dir / f"{key}.{state}"
        marker.write_text("")
        return marker

    return write
