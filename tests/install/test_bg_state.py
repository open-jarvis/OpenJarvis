"""Tests for openjarvis.cli._bg_state."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis import _rust_bridge
from openjarvis.cli import _bg_state


def test_encode_model_id_is_filesystem_safe() -> None:
    """':' is illegal in Windows file names, so ids are percent-encoded."""
    encoded = _bg_state.encode_model_id("qwen3.5:9b")
    assert ":" not in encoded
    assert _bg_state.decode_model_id(encoded) == "qwen3.5:9b"


def test_decode_model_id_keeps_legacy_names() -> None:
    """Plain on-disk names from POSIX installs must still resolve."""
    assert _bg_state.decode_model_id("llama3.2-3b") == "llama3.2-3b"


def _state_file(home: Path, model_id: str, state: str) -> Path:
    """Create a model state marker using the filesystem-safe id encoding."""
    models_dir = home / ".state" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / f"{_bg_state.encode_model_id(model_id)}.{state}"
    path.write_text("")
    return path


def test_get_status_rust_importable_without_marker(
    tmp_openjarvis_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Editable installs have no installer marker but the ext imports fine."""
    monkeypatch.setattr(_rust_bridge, "RUST_AVAILABLE", True)
    s = _bg_state.get_status()
    assert s.rust_extension == "ready"


def test_get_status_rust_importable_supersedes_failed_marker(
    tmp_openjarvis_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale extension-failed marker must not mask a working extension."""
    monkeypatch.setattr(_rust_bridge, "RUST_AVAILABLE", True)
    (tmp_openjarvis_home / ".state" / "extension-failed").write_text("old error")
    s = _bg_state.get_status()
    assert s.rust_extension == "ready"
    assert s.rust_error == ""


def test_get_status_empty(tmp_openjarvis_home: Path) -> None:
    """No state files = everything 'pending'."""
    s = _bg_state.get_status()
    assert s.rust_extension == "pending"
    assert s.models == {}


def test_get_status_rust_built(tmp_openjarvis_home: Path) -> None:
    (tmp_openjarvis_home / ".state" / "extension-built").write_text("")
    s = _bg_state.get_status()
    assert s.rust_extension == "ready"


def test_get_status_rust_failed(tmp_openjarvis_home: Path) -> None:
    (tmp_openjarvis_home / ".state" / "extension-failed").write_text("error tail here")
    s = _bg_state.get_status()
    assert s.rust_extension == "failed"
    assert s.rust_error == "error tail here"


def test_get_status_model_downloading(tmp_openjarvis_home: Path) -> None:
    _state_file(tmp_openjarvis_home, "qwen3.5:9b", "downloading")
    s = _bg_state.get_status()
    assert s.models == {"qwen3.5:9b": "downloading"}


def test_get_status_model_ready(tmp_openjarvis_home: Path) -> None:
    _state_file(tmp_openjarvis_home, "qwen3.5:9b", "ready")
    s = _bg_state.get_status()
    assert s.models == {"qwen3.5:9b": "ready"}


def test_get_status_model_failed(tmp_openjarvis_home: Path) -> None:
    _state_file(tmp_openjarvis_home, "qwen3.5:9b", "failed")
    s = _bg_state.get_status()
    assert s.models == {"qwen3.5:9b": "failed"}


def test_get_status_ready_supersedes_downloading(tmp_openjarvis_home: Path) -> None:
    """If both .downloading and .ready exist (race window), .ready wins."""
    _state_file(tmp_openjarvis_home, "qwen3.5:9b", "downloading")
    _state_file(tmp_openjarvis_home, "qwen3.5:9b", "ready")
    s = _bg_state.get_status()
    assert s.models["qwen3.5:9b"] == "ready"


def test_all_ready_true_when_all_ready(tmp_openjarvis_home: Path) -> None:
    (tmp_openjarvis_home / ".state" / "extension-built").write_text("")
    _state_file(tmp_openjarvis_home, "qwen3.5:9b", "ready")
    s = _bg_state.get_status()
    assert s.all_ready() is True


def test_all_ready_false_when_anything_pending(tmp_openjarvis_home: Path) -> None:
    (tmp_openjarvis_home / ".state" / "extension-built").write_text("")
    _state_file(tmp_openjarvis_home, "qwen3.5:9b", "downloading")
    s = _bg_state.get_status()
    assert s.all_ready() is False


def test_get_status_handles_deleted_file_race(tmp_openjarvis_home: Path) -> None:
    """File present at glob-time, gone at read-time = treat as missing."""
    f = tmp_openjarvis_home / ".state" / "extension-failed"
    f.write_text("oops")
    f.unlink()  # simulate race
    # No assertion error expected
    s = _bg_state.get_status()
    assert s.rust_extension == "pending"
