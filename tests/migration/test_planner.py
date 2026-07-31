from __future__ import annotations

import shutil
import socket
from pathlib import Path

import pytest

from openjarvis.migration import planner
from openjarvis.migration.planner import PathCategory, create_backup_plan


def _plan(tmp_path: Path, source: Path):
    return create_backup_plan(
        source,
        tmp_path / "planned-destination",
        source_label="synthetic-legacy",
        destination_label="synthetic-plan",
    )


def test_collects_all_long_paths_without_stopping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    first = source / "src" / ("a" * 40) / "one.py"
    second = source / "src" / ("b" * 40) / "two.py"
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("safe = True\n", encoding="utf-8")
    monkeypatch.setattr(planner, "WINDOWS_SAFE_TARGET_PATH_LENGTH", 45)

    result = _plan(tmp_path, source)

    assert len(result.long_paths) >= 2
    assert result.migration_long_path_count >= 2
    assert {entry.path for entry in result.long_paths} >= {
        first.relative_to(source).as_posix(),
        second.relative_to(source).as_posix(),
    }


def test_runtime_caches_models_and_protected_content_are_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    paths = {
        "huggingface": source
        / "state"
        / "models"
        / ".cache"
        / "huggingface"
        / "download"
        / "model.bin",
        "piper": source / "state" / "models" / "piper" / "cache" / "voice.onnx",
        "weight": source / "state" / "models" / "approved" / "model.onnx",
        "source_cache": source / "src" / "cache" / "module.py",
        "test_cache": source / "tests" / "example-cache" / "test_case.py",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"metadata-only-plan")

    def prohibit_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("planning mode must not open source content")

    monkeypatch.setattr(Path, "open", prohibit_open)
    result = _plan(tmp_path, source)
    by_path = {entry.path: entry for entry in result.entries}

    assert by_path[paths["huggingface"].relative_to(source).as_posix()].category is (
        PathCategory.TECHNICAL_CACHE_EXCLUDED
    )
    assert by_path[paths["piper"].relative_to(source).as_posix()].category is (
        PathCategory.TECHNICAL_CACHE_EXCLUDED
    )
    assert by_path[paths["weight"].relative_to(source).as_posix()].category is (
        PathCategory.MODEL_ARTIFACT_METADATA_ONLY
    )
    assert by_path[paths["source_cache"].relative_to(source).as_posix()].category is (
        PathCategory.MIGRATION_SOURCE_CODE
    )
    assert by_path[paths["test_cache"].relative_to(source).as_posix()].category is (
        PathCategory.MIGRATION_TEST
    )


def test_credentials_are_metadata_only_and_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    secret = source / "state" / "sessions" / "token.json"
    secret.parent.mkdir(parents=True)
    secret.write_bytes(b"SECRET-MUST-NOT-BE-READ")

    def prohibit_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("planning mode must not open credentials")

    monkeypatch.setattr(Path, "open", prohibit_open)
    result = _plan(tmp_path, source)
    entry = next(item for item in result.entries if item.path == "state/sessions")

    assert entry.category is PathCategory.CREDENTIAL_OR_SESSION_PROHIBITED
    assert entry.content_access_allowed is False
    assert entry.hashing_allowed is False
    assert not any(item.path.endswith("token.json") for item in result.entries)


def test_browser_and_credential_roots_are_inherited_but_not_enumerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    browser = source / "state" / "browser-profile"
    browser_secret = browser / ".cache" / "Default" / "Cookies"
    credential = source / "state" / "credentials"
    credential_secret = credential / "nested" / "token.json"
    for path in (browser_secret, credential_secret):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"MUST-NOT-BE-OPENED-OR-LISTED")

    def prohibit_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("planning mode must not open prohibited content")

    monkeypatch.setattr(Path, "open", prohibit_open)
    result = _plan(tmp_path, source)
    by_path = {entry.path: entry for entry in result.entries}

    assert by_path["state/browser-profile"].category is (
        PathCategory.BROWSER_RUNTIME_PROHIBITED
    )
    assert by_path["state/credentials"].category is (
        PathCategory.CREDENTIAL_OR_SESSION_PROHIBITED
    )
    assert not any(
        entry.path.startswith("state/browser-profile/") for entry in result.entries
    )
    assert not any(
        entry.path.startswith("state/credentials/") for entry in result.entries
    )
    assert result.simulation.prohibited_root_count == 2
    assert result.simulation.prohibited_descendant_entry_count == 0
    assert result.simulation.passed is True

    assert (
        planner.classify_path(
            Path("state/browser-profile/.cache/item.bin"),
            is_directory=False,
            is_reparse=False,
        )
        is PathCategory.BROWSER_RUNTIME_PROHIBITED
    )
    assert (
        planner.classify_path(
            Path("state/browser-profile/sessions/item.bin"),
            is_directory=False,
            is_reparse=False,
        )
        is PathCategory.BROWSER_RUNTIME_PROHIBITED
    )
    assert (
        planner.classify_path(
            Path("state/credentials/browser-profile/item.bin"),
            is_directory=False,
            is_reparse=False,
        )
        is PathCategory.CREDENTIAL_OR_SESSION_PROHIBITED
    )


def test_unknown_technical_root_blocks_simulation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    path = source / "mystery-runtime" / "cache" / "data.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"unknown")

    result = _plan(tmp_path, source)

    assert any(
        entry.path == "mystery-runtime"
        and entry.category is PathCategory.UNKNOWN_REVIEW_REQUIRED
        for entry in result.entries
    )
    assert result.simulation.passed is False
    assert result.simulation.unknown_count > 0


def test_known_git_dotfiles_are_configuration(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    (source / ".gitignore").write_text(".venv/\n", encoding="utf-8")

    result = _plan(tmp_path, source)

    assert result.simulation.passed is True
    assert {
        entry.category for entry in result.entries if entry.entry_type == "file"
    } == {PathCategory.MIGRATION_CONFIGURATION}


def test_unknown_long_path_blocks_simulation_until_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    unknown = source / "mystery" / ("x" * 50 + ".dat")
    unknown.parent.mkdir(parents=True)
    unknown.write_bytes(b"unknown")
    monkeypatch.setattr(planner, "WINDOWS_SAFE_TARGET_PATH_LENGTH", 40)

    blocked = _plan(tmp_path, source)

    assert blocked.simulation.passed is False
    assert blocked.simulation.unknown_long_path_count >= 1

    shutil.rmtree(source)
    safe = source / "src" / "main.py"
    safe.parent.mkdir(parents=True)
    safe.write_text("safe = True\n", encoding="utf-8")
    monkeypatch.setattr(planner, "WINDOWS_SAFE_TARGET_PATH_LENGTH", 247)
    passed = _plan(tmp_path, source)
    assert passed.simulation.passed is True
    assert passed.simulation.unknown_count == 0


def test_planning_never_copies_or_uses_network_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    file = source / "src" / "main.py"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"safe = True\n")
    before = (file.read_bytes(), file.stat().st_mtime_ns)

    monkeypatch.setattr(
        shutil,
        "copy2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("copy called")),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("network called")
        ),
    )

    result = _plan(tmp_path, source)

    assert result.source_stable is True
    assert (file.read_bytes(), file.stat().st_mtime_ns) == before
    assert not (tmp_path / "planned-destination").exists()


def test_reparse_point_is_recorded_and_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    reparse = source / "state" / "external"
    reparse.mkdir(parents=True)
    hidden = reparse / "must-not-enumerate.bin"
    hidden.write_bytes(b"outside")
    real_is_reparse = planner._is_reparse
    monkeypatch.setattr(
        planner,
        "_is_reparse",
        lambda path: path == reparse or real_is_reparse(path),
    )

    result = _plan(tmp_path, source)

    assert any(
        entry.path == "state/external" and entry.reparse_point
        for entry in result.entries
    )
    assert not any(
        entry.path.endswith("must-not-enumerate.bin") for entry in result.entries
    )
    assert result.simulation.reparse_points_not_followed == 1
