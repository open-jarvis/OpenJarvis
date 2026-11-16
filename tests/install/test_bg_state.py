"""Tests for openjarvis.cli._bg_state."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from openjarvis import _rust_bridge
from openjarvis.cli import _bg_state


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


def test_get_status_model_downloading(write_model_marker) -> None:
    write_model_marker("qwen3.5:9b", "downloading")
    s = _bg_state.get_status()
    assert s.models == {"qwen3.5:9b": "downloading"}


def test_get_status_model_ready(write_model_marker) -> None:
    write_model_marker("qwen3.5:9b", "ready")
    s = _bg_state.get_status()
    assert s.models == {"qwen3.5:9b": "ready"}


def test_get_status_model_failed(write_model_marker) -> None:
    write_model_marker("qwen3.5:9b", "failed")
    s = _bg_state.get_status()
    assert s.models == {"qwen3.5:9b": "failed"}


def test_get_status_ready_supersedes_downloading(write_model_marker) -> None:
    """If both .downloading and .ready exist (race window), .ready wins."""
    write_model_marker("qwen3.5:9b", "downloading")
    write_model_marker("qwen3.5:9b", "ready")
    s = _bg_state.get_status()
    assert s.models["qwen3.5:9b"] == "ready"


def test_all_ready_true_when_all_ready(
    tmp_openjarvis_home: Path, write_model_marker
) -> None:
    (tmp_openjarvis_home / ".state" / "extension-built").write_text("")
    write_model_marker("qwen3.5:9b", "ready")
    s = _bg_state.get_status()
    assert s.all_ready() is True


def test_all_ready_false_when_anything_pending(
    tmp_openjarvis_home: Path, write_model_marker
) -> None:
    (tmp_openjarvis_home / ".state" / "extension-built").write_text("")
    write_model_marker("qwen3.5:9b", "downloading")
    s = _bg_state.get_status()
    assert s.all_ready() is False


def test_get_status_reads_legacy_model_marker(tmp_openjarvis_home: Path) -> None:
    (tmp_openjarvis_home / ".state" / "models" / "legacy-model.ready").write_text("")
    s = _bg_state.get_status()
    assert s.models == {"legacy-model": "ready"}


@pytest.mark.parametrize("new_state", ["downloading", "failed"])
def test_current_marker_overrides_stale_legacy_ready(
    tmp_openjarvis_home: Path, write_model_marker, new_state
) -> None:
    legacy = tmp_openjarvis_home / ".state" / "models" / "legacy-model.ready"
    legacy.write_text("")
    write_model_marker("legacy-model", new_state)

    assert _bg_state.get_status().models == {"legacy-model": new_state}


def test_versioned_provider_model_id_round_trips(write_model_marker) -> None:
    model = "hf.co/team/model:tag"
    marker = write_model_marker(model, "ready")
    assert all(char not in marker.name for char in '/\\:<>"|?*')
    assert _bg_state.get_status().models == {model: "ready"}


def test_invalid_versioned_markers_are_ignored(tmp_openjarvis_home: Path) -> None:
    directory = tmp_openjarvis_home / ".state" / "models" / "v1"
    directory.mkdir()
    for token in ("not@base64", "dGVzdA=", "__8"):
        (directory / f"{token}.ready").write_text("")

    assert _bg_state.get_status().models == {}


def test_marker_contents_must_match_the_filename(write_model_marker) -> None:
    marker = write_model_marker("expected-model", "ready")
    marker.write_text("a-different-model\n", encoding="utf-8")
    assert _bg_state.get_status().models == {}


def test_marker_names_are_case_insensitive_safe_and_bounded(write_model_marker) -> None:
    # These IDs produce case-fold-equal base64 encodings (YWFH / YWFh).
    ids = ("aaG", "aaa", "hf.co/team/" + "long-model-" * 30 + ":tag")
    markers = [write_model_marker(model, "ready") for model in ids]
    assert len({marker.name.casefold() for marker in markers}) == len(ids)
    assert all(len(marker.stem) == 64 for marker in markers)
    assert _bg_state.get_status().models == dict.fromkeys(ids, "ready")


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="Bash writer")
def test_bash_writer_and_python_reader_share_the_marker_protocol(
    tmp_openjarvis_home: Path, monkeypatch
) -> None:
    root = Path(__file__).resolve().parents[2]
    stubs = root / "tests" / "install" / "bash" / "stubs"
    assert os.access(stubs / "ollama", os.X_OK)
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_openjarvis_home))
    monkeypatch.setenv("PATH", str(stubs) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("OLLAMA_STUB_EXIT", "0")
    ids = ("aaG", "aaa", "hf.co/team/" + "long-model-" * 30 + ":tag")

    for model in ids:
        subprocess.run(
            ["bash", str(root / "scripts" / "install" / "pull-model.sh"), model],
            check=True,
            timeout=10,
        )

    assert _bg_state.get_status().models == dict.fromkeys(ids, "ready")


@pytest.mark.parametrize(
    "raw,expected",
    [("failure ❤".encode("utf-8"), "failure ❤"), (b"failure\xff", "failure�")],
)
def test_status_error_logs_ignore_windows_locale(
    tmp_openjarvis_home: Path, monkeypatch, raw, expected
) -> None:
    marker = tmp_openjarvis_home / ".state" / "extension-failed"
    marker.write_bytes(raw)
    original_read = Path.read_text

    def read_with_windows_default(path, encoding=None, errors=None):
        return original_read(path, encoding=encoding or "cp1252", errors=errors)

    monkeypatch.setattr(Path, "read_text", read_with_windows_default)

    assert _bg_state.get_status().rust_error == expected


def test_get_status_handles_deleted_file_race(tmp_openjarvis_home: Path) -> None:
    """File present at glob-time, gone at read-time = treat as missing."""
    f = tmp_openjarvis_home / ".state" / "extension-failed"
    f.write_text("oops")
    f.unlink()  # simulate race
    # No assertion error expected
    s = _bg_state.get_status()
    assert s.rust_extension == "pending"
