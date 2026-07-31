from __future__ import annotations

import json
import subprocess
from pathlib import Path

from openjarvis.migration.archive_backup import create_atomic_archive_backup
from openjarvis.migration.backup import BackupKind, create_verified_backup
from openjarvis.migration.recovery_bundle import create_recovery_bundle


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        timeout=30,
    )


def test_recovery_bundle_is_atomic_relative_and_self_indexed(tmp_path: Path) -> None:
    output = tmp_path / "phase-8a"
    output.mkdir()
    legacy = tmp_path / "legacy"
    source_file = legacy / "src" / "main.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("value = 1\n", encoding="utf-8")
    create_atomic_archive_backup(
        legacy,
        output / "legacy-content-backup.zip",
        output / "legacy-runtime-metadata.json",
        output / "legacy-backup-proof.json",
        staging_root=tmp_path / "j8",
        source_label="synthetic-legacy",
        approved_plan_sha256="a" * 64,
    )

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Note\n", encoding="utf-8")
    create_verified_backup(
        vault,
        output / "vault-backup",
        kind=BackupKind.VAULT,
        source_label="synthetic-vault",
    )

    for name in (
        "backup-policy-plan.json",
        "backup-policy-plan-v2.json",
        "legacy-backup-failure.txt",
        "legacy-backup-retry-failure.txt",
    ):
        (output / name).write_text("historical\n", encoding="utf-8")
    _write_json(
        output / "legacy-function-inventory-v2.json",
        {
            "python_class_count": 1,
            "python_function_count": 1,
            "python_module_count": 1,
            "route_count": 0,
        },
    )
    _write_json(output / "runtime-conversion-dry-run.json", {"entry_count": 0})
    _write_json(
        output / "vault-pilot-dry-run.json",
        {
            "backup_unchanged": True,
            "index": {"indexed": 1},
            "pilot_removed": True,
        },
    )
    _write_json(
        output / "vault-compatibility-diagnostic-v2.json",
        {
            "backup_unchanged": True,
            "id_state_counts": {"missing": 1},
            "markdown_files": 1,
            "schema_version_counts": {"missing": 1},
        },
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    report = repo / "report.md"
    report.write_text("# Safe report\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "report.md")
    _git(repo, "commit", "-m", "test")

    target = output / "recovery-bundle"
    create_recovery_bundle(
        output,
        target,
        repo,
        [report],
        vault_backup_tree_sha256="b" * 64,
    )

    assert target.is_dir()
    assert (target / "bundle-index.json").is_file()
    assert (target / "artifact-manifest.json").is_file()
    assert (target / "summary.json").is_file()
    assert (target / "RESTORE.md").is_file()
    manifest = json.loads((target / "artifact-manifest.json").read_text())
    assert all(item["path"].startswith("../") for item in manifest)
    payload = "\n".join(
        path.read_text(encoding="utf-8") for path in target.rglob("*") if path.is_file()
    )
    assert str(tmp_path) not in payload
    assert not list(output.glob(".recovery-bundle-*.tmp"))
