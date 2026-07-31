from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from openjarvis.migration import backup as backup_module
from openjarvis.migration.backup import (
    BackupError,
    BackupKind,
    create_verified_backup,
    load_manifest,
    verify_manifest,
)


def test_verified_backup_is_byte_identical_and_excludes_sensitive_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.md").write_bytes(b"# note\r\n")
    nested = source / "nested"
    nested.mkdir()
    (nested / "fixture.json").write_bytes(b'{"safe":true}\n')
    (source / ".env").write_bytes(b"TOKEN=must-not-be-copied\n")
    dependencies = source / "node_modules"
    dependencies.mkdir()
    (dependencies / "ignored.js").write_bytes(b"ignored")
    real_hash_stable = backup_module._hash_stable

    def reject_sensitive_hash(path: Path) -> tuple[int, int, str]:
        assert path.name != ".env"
        return real_hash_stable(path)

    monkeypatch.setattr(backup_module, "_hash_stable", reject_sensitive_hash)

    destination = tmp_path / "backup"
    result = create_verified_backup(
        source,
        destination,
        kind=BackupKind.LEGACY_PROJECT,
        source_label="synthetic-legacy",
    )

    assert result.file_count == 2
    assert result.restore_verified is True
    assert result.source_stable is True
    assert (destination / "data" / "note.md").read_bytes() == b"# note\r\n"
    assert not (destination / "data" / ".env").exists()
    assert not (destination / "data" / "node_modules").exists()

    manifest = load_manifest(destination / "manifests" / "backup.jsonl")
    assert verify_manifest(destination / "data", manifest)
    exclusions = [
        json.loads(line)
        for line in (destination / "manifests" / "exclusions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {item["path"] for item in exclusions} == {".env", "node_modules"}
    exclusion_text = (destination / "manifests" / "exclusions.jsonl").read_text(
        encoding="utf-8"
    )
    assert "must-not-be-copied" not in exclusion_text
    assert not list(tmp_path.glob("phase8a-restore-*"))


def test_vault_excludes_credentials_tokens_sessions_and_browser_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "vault"
    source.mkdir()
    (source / "note.md").write_bytes(b"---\nid: note-1\n---\nSafe note.\n")
    (source / ".env").write_bytes(b"PASSWORD=do-not-open\n")
    (source / "token.json").write_bytes(b'{"token":"do-not-open"}\n')
    credentials = source / "credentials"
    credentials.mkdir()
    (credentials / "account.json").write_bytes(b'{"password":"do-not-open"}\n')
    sessions = source / "sessions"
    sessions.mkdir()
    (sessions / "session.json").write_bytes(b'{"cookie":"do-not-open"}\n')
    browser = source / "browser-profile"
    browser.mkdir()
    (browser / "Cookies").write_bytes(b"do-not-open")
    real_hash_stable = backup_module._hash_stable

    def reject_sensitive_hash(path: Path) -> tuple[int, int, str]:
        assert path.name not in {
            ".env",
            "token.json",
            "account.json",
            "session.json",
            "Cookies",
        }
        return real_hash_stable(path)

    monkeypatch.setattr(backup_module, "_hash_stable", reject_sensitive_hash)
    destination = tmp_path / "backup"
    result = create_verified_backup(
        source,
        destination,
        kind=BackupKind.VAULT,
        source_label="synthetic-vault",
    )

    assert result.file_count == 1
    assert (destination / "data" / "note.md").read_bytes().endswith(b"Safe note.\n")
    assert not (destination / "data" / ".env").exists()
    assert not (destination / "data" / "token.json").exists()
    assert not (destination / "data" / "credentials").exists()
    assert not (destination / "data" / "sessions").exists()
    assert not (destination / "data" / "browser-profile").exists()
    exclusion_text = (destination / "manifests" / "exclusions.jsonl").read_text(
        encoding="utf-8"
    )
    assert "do-not-open" not in exclusion_text
    assert {item["path"] for item in map(json.loads, exclusion_text.splitlines())} == {
        ".env",
        "browser-profile",
        "credentials",
        "sessions",
        "token.json",
    }


def test_generated_caches_are_contextual_and_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    excluded_files = {
        source / "state" / "models" / "review-cache" / "nested" / "voice.bin",
        source / "state" / "example-cache" / "generated.bin",
        source / "state" / "example_cache" / "generated.bin",
    }
    included_files = {
        source / "src" / "cache" / "module.py",
        source / "tests" / "example-cache" / "test_fixture.py",
        source / "src" / "main.py",
    }
    for path in excluded_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"CACHE-CONTENT-MUST-NOT-BE-READ")
    for path in included_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("safe = True\n", encoding="utf-8")
    real_hash_stable = backup_module._hash_stable

    def reject_cache_hash(path: Path) -> tuple[int, int, str]:
        assert path not in excluded_files
        return real_hash_stable(path)

    monkeypatch.setattr(backup_module, "_hash_stable", reject_cache_hash)
    destination = tmp_path / "backup"
    result = create_verified_backup(
        source,
        destination,
        kind=BackupKind.LEGACY_PROJECT,
        source_label="synthetic-legacy",
    )

    assert result.file_count == 3
    for path in included_files:
        assert (destination / "data" / path.relative_to(source)).is_file()
    for path in excluded_files:
        assert not (destination / "data" / path.relative_to(source)).exists()
    exclusion_text = (destination / "manifests" / "exclusions.jsonl").read_text(
        encoding="utf-8"
    )
    assert "CACHE-CONTENT-MUST-NOT-BE-READ" not in exclusion_text
    assert {item["path"] for item in map(json.loads, exclusion_text.splitlines())} == {
        "state/example-cache",
        "state/example_cache",
        "state/models/review-cache",
    }


def test_backup_refuses_nested_or_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("safe", encoding="utf-8")

    with pytest.raises(BackupError, match="disjoint"):
        create_verified_backup(
            source,
            source / "backup",
            kind=BackupKind.VAULT,
            source_label="synthetic-vault",
        )

    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(BackupError, match="must not already exist"):
        create_verified_backup(
            source,
            destination,
            kind=BackupKind.VAULT,
            source_label="synthetic-vault",
        )


def test_symlink_is_never_followed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    (outside / "private.txt").write_text("outside", encoding="utf-8")
    link = source / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink creation is unavailable")

    destination = tmp_path / "backup"
    result = create_verified_backup(
        source,
        destination,
        kind=BackupKind.VAULT,
        source_label="synthetic-vault",
    )

    assert result.file_count == 0
    assert result.excluded_count == 1
    assert not (destination / "data" / "escape").exists()


def test_reparse_directory_is_excluded_without_reading_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    reparse = source / "escape"
    reparse.mkdir(parents=True)
    (reparse / "must-not-copy.txt").write_text("outside", encoding="utf-8")
    real_is_reparse = backup_module._is_reparse
    monkeypatch.setattr(
        backup_module,
        "_is_reparse",
        lambda path: path == reparse or real_is_reparse(path),
    )

    destination = tmp_path / "backup"
    result = create_verified_backup(
        source,
        destination,
        kind=BackupKind.VAULT,
        source_label="synthetic-vault",
    )

    assert result.file_count == 0
    assert result.excluded_count == 1
    assert not (destination / "data" / "escape").exists()


def test_manifest_verification_detects_changed_backup(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.md").write_text("original", encoding="utf-8")
    destination = tmp_path / "backup"
    create_verified_backup(
        source,
        destination,
        kind=BackupKind.VAULT,
        source_label="synthetic-vault",
    )
    manifest = load_manifest(destination / "manifests" / "backup.jsonl")

    (destination / "data" / "note.md").write_text("changed", encoding="utf-8")

    assert verify_manifest(destination / "data", manifest) is False


def test_source_change_during_backup_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    note = source / "note.md"
    note.write_text("before", encoding="utf-8")
    destination = tmp_path / "backup"
    real_scan = backup_module._scan
    calls = 0

    def mutate_before_final_scan(
        root: Path, kind: BackupKind, *, apply_policy: bool
    ) -> backup_module.ScanResult:
        nonlocal calls
        calls += 1
        if calls == 3:
            note.write_text("changed while copying", encoding="utf-8")
        return real_scan(root, kind, apply_policy=apply_policy)

    monkeypatch.setattr(backup_module, "_scan", mutate_before_final_scan)

    with pytest.raises(BackupError, match="source changed during backup"):
        create_verified_backup(
            source,
            destination,
            kind=BackupKind.VAULT,
            source_label="synthetic-vault",
        )

    assert not destination.exists()


def test_long_target_path_preflight_runs_before_copy_and_removes_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    relative = Path("nested") / ("x" * 40 + ".md")
    path = source / relative
    path.parent.mkdir()
    path.write_text("safe", encoding="utf-8")
    destination = tmp_path / "backup"
    limit = len(os.fspath(destination / "data" / "nested")) + 5
    monkeypatch.setattr(backup_module, "WINDOWS_SAFE_TARGET_PATH_LENGTH", limit)
    copy_called = False

    def unexpected_copy(*_args: object, **_kwargs: object) -> None:
        nonlocal copy_called
        copy_called = True

    monkeypatch.setattr(backup_module, "_copy_files", unexpected_copy)

    with pytest.raises(BackupError, match=relative.as_posix()) as error:
        create_verified_backup(
            source,
            destination,
            kind=BackupKind.LEGACY_PROJECT,
            source_label="synthetic-legacy",
        )

    assert copy_called is False
    assert str(destination) not in str(error.value)
    assert not destination.exists()


def test_copy_error_removes_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("safe", encoding="utf-8")
    destination = tmp_path / "backup"

    def partial_copy(_source: Path, data_root: Path, _scan: object) -> None:
        (data_root / "partial.txt").write_text("partial", encoding="utf-8")
        raise BackupError("synthetic copy failure")

    monkeypatch.setattr(backup_module, "_copy_files", partial_copy)

    with pytest.raises(BackupError, match="synthetic copy failure"):
        create_verified_backup(
            source,
            destination,
            kind=BackupKind.LEGACY_PROJECT,
            source_label="synthetic-legacy",
        )

    assert not destination.exists()
