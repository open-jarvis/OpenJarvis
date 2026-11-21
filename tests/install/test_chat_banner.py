"""Tests for the chat startup banner."""

from __future__ import annotations

from pathlib import Path

from openjarvis.cli import _bg_state
from openjarvis.cli._chat_banner import render_startup_banner


def _model_state(home: Path, model_id: str, state: str) -> Path:
    models_dir = home / ".state" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / f"{_bg_state.encode_model_id(model_id)}.{state}"
    path.write_text("")
    return path


def test_banner_empty_when_all_ready(tmp_openjarvis_home: Path) -> None:
    (tmp_openjarvis_home / ".state" / "extension-built").write_text("")
    _model_state(tmp_openjarvis_home, "qwen3.5:9b", "ready")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert banner == ""


def test_banner_reports_missing_rust_extension(tmp_openjarvis_home: Path) -> None:
    """No marker and no import means "not installed", not "building"."""
    s = _bg_state.get_status()  # all pending
    banner = render_startup_banner(s)
    assert "Rust extension" in banner
    assert "not installed" in banner.lower()
    assert "building" not in banner.lower()


def test_banner_shows_model_downloading(tmp_openjarvis_home: Path) -> None:
    (tmp_openjarvis_home / ".state" / "extension-built").write_text("")
    _model_state(tmp_openjarvis_home, "qwen3.5:9b", "downloading")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert "qwen3.5:9b" in banner
    assert "downloading" in banner.lower()


def test_banner_shows_failed_in_dim_warning(tmp_openjarvis_home: Path) -> None:
    (tmp_openjarvis_home / ".state" / "extension-failed").write_text("error tail")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert "failed" in banner.lower()
    assert "doctor" in banner.lower()
