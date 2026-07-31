from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from openjarvis.migration import archive_backup
from openjarvis.migration.archive_backup import (
    ARCHIVE_METADATA_NAME,
    CONTENT_MANIFEST_NAME,
    ArchiveBackupError,
    create_atomic_archive_backup,
    verify_content_archive,
)


def _source(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    source = tmp_path / "source"
    paths = {
        "source": source / "src" / "main.py",
        "test": source / "tests" / "example-cache" / "test_main.py",
        "docs": source / "docs" / "guide.md",
        "config": source / "config" / "settings.json",
        "skill": source / "skills" / "demo" / "SKILL.md",
        "workflow": source / "automations" / "job.json",
        "model": source / "state" / "models" / "voice.onnx",
        "cache": source / "state" / "models" / ".cache" / "download.bin",
        "browser": source / "state" / "browser-profile" / "Default" / "Cookies",
        "credential": source / "state" / "credentials" / "token.json",
        "build": source / ".venv" / "generated.py",
    }
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"synthetic-{name}\n".encode())
    return source, paths


def _outputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    output = tmp_path / "output"
    return (
        output / "legacy-content.zip",
        output / "legacy-runtime.json",
        output / "legacy-proof.json",
    )


def _create(tmp_path: Path, source: Path):
    archive, inventory, proof = _outputs(tmp_path)
    return create_atomic_archive_backup(
        source,
        archive,
        inventory,
        proof,
        staging_root=tmp_path / "j8",
        source_label="synthetic-legacy",
        approved_plan_sha256="a" * 64,
    )


def test_atomic_archive_contains_only_policy_content_and_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, paths = _source(tmp_path)
    original_open = Path.open
    prohibited = {paths["model"], paths["cache"], paths["browser"], paths["credential"]}

    def guarded_open(path: Path, *args: object, **kwargs: object):
        if path in prohibited:
            raise AssertionError("non-content source was opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = _create(tmp_path, source)

    assert result.restore_verified is True
    assert result.restore_probe_removed is True
    assert not (tmp_path / "j8").exists()
    manifest, digest = verify_content_archive(result.archive)
    assert digest == result.content_manifest_sha256
    assert {entry.path for entry in manifest} == {
        "automations/job.json",
        "config/settings.json",
        "docs/guide.md",
        "skills/demo/SKILL.md",
        "src/main.py",
        "tests/example-cache/test_main.py",
    }
    assert all(not entry.path.startswith("state/") for entry in manifest)
    with zipfile.ZipFile(result.archive) as archive:
        assert set(archive.namelist()) == {
            CONTENT_MANIFEST_NAME,
            ARCHIVE_METADATA_NAME,
            *(f"content/{entry.path}" for entry in manifest),
        }

    inventory = json.loads(result.runtime_inventory.read_text(encoding="utf-8"))
    inventory_paths = {entry["path"] for entry in inventory["entries"]}
    assert "state/models/voice.onnx" in inventory_paths
    assert "state/models/.cache/download.bin" in inventory_paths
    assert "state/browser-profile" in inventory_paths
    assert "state/credentials" in inventory_paths
    assert not any(
        path.startswith("state/browser-profile/") for path in inventory_paths
    )
    assert not any(path.startswith("state/credentials/") for path in inventory_paths)
    assert inventory["content_accessed"] is False
    assert all(
        not os.path.isabs(path) and ".." not in Path(path).parts
        for path in inventory_paths
    )


def test_source_change_removes_all_partial_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, paths = _source(tmp_path)
    original = archive_backup._write_content_archive

    def mutate_after_archive(*args: object, **kwargs: object):
        result = original(*args, **kwargs)
        paths["source"].write_text("changed\n", encoding="utf-8")
        return result

    monkeypatch.setattr(archive_backup, "_write_content_archive", mutate_after_archive)

    with pytest.raises(ArchiveBackupError, match="source metadata changed"):
        _create(tmp_path, source)

    archive, inventory, proof = _outputs(tmp_path)
    assert not archive.exists()
    assert not inventory.exists()
    assert not proof.exists()
    assert not list(archive.parent.glob(".*.tmp"))


def test_unknown_policy_blocks_before_source_content_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    unknown = source / "mystery" / "payload.dat"
    unknown.parent.mkdir(parents=True)
    unknown.write_bytes(b"unknown")
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):
        if path == unknown:
            raise AssertionError("unknown content must not be opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(ArchiveBackupError, match="simulation did not pass"):
        _create(tmp_path, source)


@pytest.mark.parametrize(
    "value",
    [
        "../escape.txt",
        "/absolute.txt",
        "C:/drive.txt",
        "src/file.py:stream",
        ".",
        "./src/main.py",
        "src//main.py",
    ],
)
def test_unsafe_archive_paths_are_rejected(value: str) -> None:
    with pytest.raises(ArchiveBackupError):
        archive_backup._safe_relative(value)


def test_archive_traversal_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.txt", b"escape")
        archive.writestr(CONTENT_MANIFEST_NAME, b"")
        archive.writestr(ARCHIVE_METADATA_NAME, b"{}")

    with pytest.raises(ArchiveBackupError, match="unsafe"):
        verify_content_archive(archive_path)


def test_tampered_member_fails_full_archive_verification(tmp_path: Path) -> None:
    archive_path = tmp_path / "tampered.zip"
    manifest = archive_backup._canonical_jsonl(
        [
            archive_backup.ContentManifestEntry(
                path="src/main.py",
                size=4,
                sha256="0" * 64,
                category="migration_source_code",
            )
        ]
    )
    metadata = archive_backup._canonical_json(
        {
            "content_file_count": 1,
            "content_manifest_sha256": archive_backup._sha256_bytes(manifest),
            "content_total_bytes": 4,
        }
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("content/src/main.py", b"safe")
        archive.writestr(CONTENT_MANIFEST_NAME, manifest)
        archive.writestr(ARCHIVE_METADATA_NAME, metadata)

    with pytest.raises(ArchiveBackupError, match="failed verification"):
        verify_content_archive(archive_path)


def test_existing_final_artifact_blocks_without_overwrite(tmp_path: Path) -> None:
    source, _paths = _source(tmp_path)
    archive, _inventory, _proof = _outputs(tmp_path)
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"keep")

    with pytest.raises(ArchiveBackupError, match="must not already exist"):
        _create(tmp_path, source)

    assert archive.read_bytes() == b"keep"


def test_restore_staging_must_be_disjoint_from_source(tmp_path: Path) -> None:
    source, _paths = _source(tmp_path)
    archive, inventory, proof = _outputs(tmp_path)

    with pytest.raises(ArchiveBackupError, match="staging roots must be disjoint"):
        create_atomic_archive_backup(
            source,
            archive,
            inventory,
            proof,
            staging_root=source / "restore",
            source_label="synthetic-legacy",
            approved_plan_sha256="a" * 64,
        )


def test_reparse_content_is_never_archived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, paths = _source(tmp_path)
    original_is_reparse = archive_backup._is_reparse

    def synthetic_reparse(path: Path) -> bool:
        return path == paths["source"] or original_is_reparse(path)

    monkeypatch.setattr(archive_backup, "_is_reparse", synthetic_reparse)
    with pytest.raises(ArchiveBackupError, match="reparse point appeared"):
        _create(tmp_path, source)


def test_restore_probe_is_removed_when_restore_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _paths = _source(tmp_path)
    original = archive_backup._restore_probe

    def fail_after_restore(*args: object, **kwargs: object) -> bool:
        assert original(*args, **kwargs) is True
        raise ArchiveBackupError("synthetic restore failure")

    monkeypatch.setattr(archive_backup, "_restore_probe", fail_after_restore)
    with pytest.raises(ArchiveBackupError, match="synthetic restore failure"):
        _create(tmp_path, source)

    archive, inventory, proof = _outputs(tmp_path)
    assert not archive.exists()
    assert not inventory.exists()
    assert not proof.exists()
    assert not (tmp_path / "j8").exists()
