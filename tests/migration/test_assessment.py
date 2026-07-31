from __future__ import annotations

import json
from pathlib import Path

import pytest

from openjarvis.migration.archive_backup import create_atomic_archive_backup
from openjarvis.migration.assessment import (
    AssessmentError,
    assess_legacy_archive,
    assess_runtime_metadata,
    run_vault_pilot,
)
from openjarvis.migration.backup import BackupKind, create_verified_backup


def _legacy_backup(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "legacy"
    files = {
        "backend/jarvis_backend/app.py": (
            "@app.get('/health')\ndef health():\n    return {'ok': True}\n"
        ),
        "backend/jarvis_backend/tasks/store.py": "class TaskStore:\n    pass\n",
        "config/memory.json": '{"enabled": true, "path": "test"}\n',
        "skills/example.json": '{"name": "untrusted"}\n',
        "tests/test_app.py": "def test_app():\n    assert True\n",
        "src/cache/main.py": "raise RuntimeError('must never execute')\n",
    }
    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    runtime = source / "state" / "models" / ".cache" / "weight.bin"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"not-content")

    output = tmp_path / "output"
    archive = output / "legacy.zip"
    inventory = output / "runtime.json"
    create_atomic_archive_backup(
        source,
        archive,
        inventory,
        output / "proof.json",
        staging_root=tmp_path / "j8",
        source_label="synthetic-legacy",
        approved_plan_sha256="a" * 64,
    )
    return archive, inventory


def _vault_backup(tmp_path: Path) -> Path:
    source = tmp_path / "vault-source"
    source.mkdir()
    (source / "legacy.md").write_text("# Legacy\n\nBody\n", encoding="utf-8")
    (source / "valid.md").write_text(
        "---\n"
        "id: 11111111-1111-4111-8111-111111111111\n"
        "schema_version: 1\n"
        "type: fact\n"
        "status: active\n"
        "scope: personal\n"
        "---\n"
        "Python is preferred.\n",
        encoding="utf-8",
    )
    destination = tmp_path / "vault-backup"
    create_verified_backup(
        source,
        destination,
        kind=BackupKind.VAULT,
        source_label="synthetic-vault",
    )
    return destination


def test_legacy_inventory_is_static_and_archive_bound(tmp_path: Path) -> None:
    archive, _runtime = _legacy_backup(tmp_path)

    result = assess_legacy_archive(archive)

    assert result["static_analysis_only"] is True
    assert result["route_count"] == 1
    assert result["routes"] == [
        {"function": "health", "method": "GET", "path": "/health"}
    ]
    assert result["skill_definition_count"] == 1
    assert result["skills_untrusted"] is True
    assert result["python_class_count"] == 1
    assert result["configuration_keys"]["config/memory.json"] == [
        "enabled",
        "path",
    ]


def test_runtime_assessment_uses_metadata_only(tmp_path: Path) -> None:
    _archive, runtime = _legacy_backup(tmp_path)

    result = assess_runtime_metadata(runtime)

    assert result["metadata_only"] is True
    assert result["category_counts"]["technical_cache_excluded"] >= 1
    assert result["actions"]["technical_cache_excluded"] == "discard_and_regenerate"


def test_runtime_assessment_rejects_unsafe_paths(tmp_path: Path) -> None:
    inventory = tmp_path / "runtime.json"
    inventory.write_text(
        json.dumps(
            {
                "content_accessed": False,
                "entries": [
                    {
                        "path": "../escape",
                        "category": "runtime_state_metadata_only",
                        "entry_type": "file",
                        "size": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AssessmentError, match="unsafe relative path"):
        assess_runtime_metadata(inventory)


def test_vault_pilot_indexes_copy_and_removes_it(tmp_path: Path) -> None:
    backup = _vault_backup(tmp_path)
    backup_data = backup / "data"
    before = {
        path: path.read_bytes() for path in backup_data.rglob("*") if path.is_file()
    }
    workspace = tmp_path / "pilot-workspace"

    result = run_vault_pilot(backup, workspace)

    assert result["dry_run"] is True
    assert result["real_vault_accessed"] is False
    assert result["restore_or_write_applied"] is False
    assert result["backup_unchanged"] is True
    assert result["pilot_unchanged"] is True
    assert result["migration"]["markdown_files"] == 2
    assert result["index"]["indexed"] == 2
    assert result["index"]["fts5_available"] is True
    assert not list(workspace.glob("phase8a-vault-pilot-*"))
    assert {path: path.read_bytes() for path in before} == before
