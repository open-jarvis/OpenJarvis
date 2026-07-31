"""End-to-end isolated Phase 8B note-type compatibility pilot tests."""

from __future__ import annotations

import json
import socket
from pathlib import Path

from openjarvis.migration.backup import BackupKind, create_verified_backup
from openjarvis.migration.vault_note_compatibility import (
    EXPECTED_COUNTS,
    run_note_type_compatibility_pilot,
)
from openjarvis.migration.vault_schema_pilot import build_mapping


def _pilot_vault(root: Path) -> None:
    types = [
        *("memory_proposal" for _ in range(12)),
        *("category" for _ in range(6)),
        *("navigation" for _ in range(2)),
        "project_profile",
        "system_policy",
        "system_profile",
        *("capture" for _ in range(23)),
    ]
    assert len(types) == 46
    for index, note_type in enumerate(types):
        path = root / f"notes/{index:02d}-{note_type}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        identifier = f"id: legacy-{index:02d}\n" if index < 41 else ""
        status = "proposed" if note_type == "memory_proposal" else "active"
        scope = "Project-Alpha" if note_type == "project_profile" else "personal"
        path.write_text(
            "---\n"
            f"{identifier}"
            f"type: {note_type}\n"
            f"status: {status}\n"
            f"scope: {scope}\n"
            "source: synthetic\n"
            "---\n"
            f"# Unique {note_type} {index}\n\n"
            f"Private synthetic body marker {index}. [[Index]]\n",
            encoding="utf-8",
        )
    for index in range(13):
        (root / f"asset-{index:02d}.txt").write_text(
            f"asset {index}\n", encoding="utf-8"
        )


def test_full_compatibility_pilot_is_offline_repeatable_and_cleans_up(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source-vault"
    source.mkdir()
    _pilot_vault(source)
    expected_mapping = build_mapping(source).mapping_sha256
    backup = tmp_path / "vault-backup"
    backup_result = create_verified_backup(
        source,
        backup,
        kind=BackupKind.VAULT,
        source_label="synthetic-vault",
    )
    forbidden_real_vault = tmp_path / "real-vault-must-not-open"
    forbidden_real_vault.mkdir()
    forbidden = forbidden_real_vault / "private.md"
    forbidden.write_text("forbidden real vault body\n", encoding="utf-8")
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):
        if path == forbidden or forbidden_real_vault in path.parents:
            raise AssertionError("real Vault was opened")
        return original_open(path, *args, **kwargs)

    def blocked_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(socket, "create_connection", blocked_network)
    output = tmp_path / "phase-8b-note-type-pilot"

    result = run_note_type_compatibility_pilot(
        backup,
        output,
        expected_source_manifest_sha256=backup_result.manifest_sha256,
        established_vault_backup_tree_sha256="b" * 64,
        expected_mapping_sha256=expected_mapping,
    )

    assert result["status"] == "passed"
    assert result["mapping_sha256"] == expected_mapping
    assert result["valid_legacy_id_mappings"] == 41
    assert result["missing_id_mappings"] == 5
    assert all(result["gates"].values())
    assert result["parser"]["discovered"] == 46
    assert result["parser"]["schema_valid"] == 46
    assert result["parser"]["type_supported"] == 46
    assert result["parser"]["parser_errors"] == 0
    assert result["parser"]["fts_documents"] == 46
    assert result["note_type_compatibility"]["legacy_type_counts"] == (EXPECTED_COUNTS)
    for name in (
        "note-type-inventory.json",
        "parser-status-report.json",
        "retrieval-classification-report.json",
        "authority-boundary-report.json",
        "pilot-summary-v2.json",
        "rollback-proof-v2.txt",
        "cleanup-proof-v2.json",
    ):
        assert (output / name).is_file()
    inventory = json.loads(
        (output / "note-type-inventory.json").read_text(encoding="utf-8")
    )
    assert inventory["affected_count"] == 23
    assert inventory["body_content_included"] is False
    assert inventory["type_counts"] == EXPECTED_COUNTS
    all_artifacts = "\n".join(
        path.read_text(encoding="utf-8") for path in output.iterdir()
    )
    assert "Private synthetic body marker" not in all_artifacts
    assert str(source) not in all_artifacts
    assert not list(tmp_path.glob(".phase8b-vault-*.tmp"))
