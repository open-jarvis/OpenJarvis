from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

import openjarvis.migration.finalize as finalize_module
from openjarvis.migration.backup import (
    BackupKind,
    create_verified_backup,
)
from openjarvis.migration.finalize import (
    FinalMigrationApplyError,
    FinalMigrationError,
    apply_final_migration,
    build_final_execution_plan,
    emit_final_migration_artifacts,
    load_approved_artifacts,
    load_approved_mapping,
    run_verified_rollback_probe,
)
from openjarvis.migration.vault_schema_pilot import (
    build_manifest,
    build_mapping,
    mapping_to_bytes,
)

_TYPES = [
    *("memory_proposal" for _ in range(12)),
    *("category" for _ in range(6)),
    *("navigation" for _ in range(2)),
    "project_profile",
    "system_policy",
    "system_profile",
    *("capture" for _ in range(23)),
]


def _write_source(root: Path) -> None:
    root.mkdir()
    for index, note_type in enumerate(_TYPES):
        path = root / "notes" / f"note-{index:02d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        identifier = f"id: legacy-{index:02d}\n" if index < 41 else ""
        scope = "scope: exact-project\n" if note_type == "project_profile" else ""
        path.write_text(
            "---\n"
            f"{identifier}"
            f"type: {note_type}\n"
            f"title: Unique {note_type} {index}\n"
            f"{scope}"
            "source: synthetic\n"
            "---\n"
            f"# Unique {note_type} {index}\n\n"
            f"Synthetic approved body {index}.\n",
            encoding="utf-8",
        )
    for index in range(13):
        (root / f"asset-{index:02d}.txt").write_text(
            f"asset {index}\n", encoding="utf-8"
        )


def _jsonl(values: object) -> bytes:
    return b"".join(
        json.dumps(
            asdict(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
        for value in values  # type: ignore[union-attr]
    )


def _approved_review(source: Path, review: Path):
    review.mkdir()
    mapping = build_mapping(source)
    manifest, manifest_sha256 = build_manifest(source)
    (review / "mapping.json").write_bytes(mapping_to_bytes(mapping))
    (review / "before-manifest.jsonl").write_bytes(_jsonl(manifest))
    records = [
        {
            "relative_path": f"notes/note-{index:02d}.md",
            "note_type": note_type,
            "type_supported": True,
        }
        for index, note_type in enumerate(_TYPES)
    ]
    (review / "parser-status-report.json").write_text(
        json.dumps({"records": records}), encoding="utf-8"
    )
    approved = load_approved_artifacts(
        review,
        expected_mapping_sha256=mapping.mapping_sha256,
        expected_baseline_sha256=manifest_sha256,
    )
    return approved, mapping


def _case(tmp_path: Path, *, body_drift: bool = True):
    baseline = tmp_path / "approved-baseline"
    _write_source(baseline)
    approved, mapping = _approved_review(baseline, tmp_path / "approved-review")
    current = tmp_path / "current-vault"
    shutil.copytree(baseline, current)
    if body_drift:
        for index in (0, 45):
            path = current / "notes" / f"note-{index:02d}.md"
            path.write_bytes(path.read_bytes() + b"Current body-only delta.\n")
    backup = tmp_path / "fresh-backup"
    create_verified_backup(
        current,
        backup,
        kind=BackupKind.VAULT,
        source_label="synthetic-current-vault",
    )
    return approved, mapping, current, backup


def test_approved_mapping_verifies_logical_and_per_entry_hashes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_source(source)
    review = tmp_path / "review"
    _approved, mapping = _approved_review(source, review)

    loaded = load_approved_mapping(
        review / "mapping.json",
        expected_mapping_sha256=mapping.mapping_sha256,
    )
    assert loaded == mapping

    tampered = json.loads((review / "mapping.json").read_text(encoding="utf-8"))
    tampered["entries"][0]["new_uuid"] = tampered["entries"][1]["new_uuid"]
    (review / "mapping-tampered.json").write_text(
        json.dumps(tampered), encoding="utf-8"
    )
    with pytest.raises(FinalMigrationError, match="entry hash differs"):
        load_approved_mapping(
            review / "mapping-tampered.json",
            expected_mapping_sha256=mapping.mapping_sha256,
        )


def test_plan_allows_body_drift_but_preserves_approved_mapping_and_uuids(
    tmp_path: Path,
) -> None:
    approved, mapping, current, backup = _case(tmp_path)

    plan = build_final_execution_plan(current, approved, backup)

    assert len(plan.before_manifest) == 59
    assert len(plan.patches) == 46
    assert approved.mapping.mapping_sha256 == mapping.mapping_sha256
    assert [patch.new_uuid for patch in plan.patches] == [
        entry.new_uuid for entry in mapping.entries
    ]
    missing = next(patch for patch in plan.patches if patch.path.endswith("45.md"))
    approved_missing = next(
        entry for entry in mapping.entries if entry.relative_path.endswith("45.md")
    )
    assert missing.new_uuid == approved_missing.new_uuid
    assert missing.expected_before_sha256 != approved_missing.before_sha256


@pytest.mark.parametrize("case", ["extra_path", "type_change", "reference_blocker"])
def test_delta_conflicts_fail_before_apply(tmp_path: Path, case: str) -> None:
    baseline = tmp_path / "baseline"
    _write_source(baseline)
    approved, _mapping = _approved_review(baseline, tmp_path / "review")
    current = tmp_path / "current"
    shutil.copytree(baseline, current)
    if case == "extra_path":
        (current / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    elif case == "type_change":
        path = current / "notes" / "note-00.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "type: memory_proposal", "type: capture"
            ),
            encoding="utf-8",
        )
    else:
        path = current / "notes" / "note-00.md"
        path.write_bytes(path.read_bytes() + b"Unapproved legacy-01 reference.\n")
    backup = tmp_path / "backup"
    create_verified_backup(
        current,
        backup,
        kind=BackupKind.VAULT,
        source_label="synthetic-current-vault",
    )

    with pytest.raises(FinalMigrationError):
        build_final_execution_plan(current, approved, backup)


def test_successful_transaction_validates_and_emits_content_free_artifacts(
    tmp_path: Path,
) -> None:
    approved, _mapping, current, backup = _case(tmp_path)
    plan = build_final_execution_plan(current, approved, backup)

    outcome = apply_final_migration(
        plan,
        backup,
        tmp_path / "validation-state",
    )
    artifacts = emit_final_migration_artifacts(tmp_path / "final-output", plan, outcome)

    assert outcome.changed == 46
    assert outcome.validation["status"] == "passed"
    assert outcome.after_manifest_sha256 == plan.expected_after_manifest_sha256
    assert not (tmp_path / "validation-state").exists()
    assert {path.name for path in artifacts} == {
        "vault-before-manifest.jsonl",
        "vault-after-manifest.jsonl",
        "vault-migration-diff.jsonl",
        "real-vault-migration-proof.txt",
    }
    combined = b"\n".join(path.read_bytes() for path in artifacts)
    assert b"Synthetic approved body" not in combined
    assert str(tmp_path).encode() not in combined


def test_apply_failure_restores_entire_vault_byte_exact(tmp_path: Path) -> None:
    approved, _mapping, current, backup = _case(tmp_path)
    plan = build_final_execution_plan(current, approved, backup)
    before, before_hash = build_manifest(current)

    with pytest.raises(FinalMigrationApplyError) as captured:
        apply_final_migration(
            plan,
            backup,
            tmp_path / "validation-state",
            _fail_after=1,
        )

    restored, restored_hash = build_manifest(current)
    assert captured.value.rollback_verified is True
    assert restored == before
    assert restored_hash == before_hash
    assert not list(tmp_path.glob(".current-vault.*.tmp"))


def test_post_apply_validation_failure_also_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved, _mapping, current, backup = _case(tmp_path)
    plan = build_final_execution_plan(current, approved, backup)
    before, before_hash = build_manifest(current)
    monkeypatch.setattr(
        finalize_module,
        "validate_final_state",
        lambda *_args, **_kwargs: {"status": "failed_gates"},
    )

    with pytest.raises(FinalMigrationApplyError) as captured:
        apply_final_migration(plan, backup, tmp_path / "validation-state")

    restored, restored_hash = build_manifest(current)
    assert captured.value.rollback_verified is True
    assert restored == before
    assert restored_hash == before_hash


def test_full_tree_cas_stops_before_any_migration_write(tmp_path: Path) -> None:
    approved, _mapping, current, backup = _case(tmp_path)
    plan = build_final_execution_plan(current, approved, backup)
    drift = current / "asset-00.txt"
    drift.write_text("concurrent drift\n", encoding="utf-8")

    with pytest.raises(FinalMigrationError, match="full-tree compare-and-swap"):
        apply_final_migration(plan, backup, tmp_path / "validation-state")

    assert drift.read_text(encoding="utf-8") == "concurrent drift\n"
    assert b"legacy-00" in (current / "notes" / "note-00.md").read_bytes()


def test_verified_rollback_probe_replans_and_cleans_new_root(tmp_path: Path) -> None:
    approved, _mapping, _current, backup = _case(tmp_path)
    restore = tmp_path / "rollback-probe"

    result = run_verified_rollback_probe(
        backup,
        restore,
        approved=approved,
        cleanup=True,
    )

    assert result["byte_exact"] is True
    assert result["file_count"] == 59
    assert result["diagnostic_mode"] == "read-only"
    assert result["replanned_sha256"]
    assert result["restore_removed"] is True
    assert not restore.exists()
    assert not list(tmp_path.glob(".rollback-probe.state-*.tmp"))
