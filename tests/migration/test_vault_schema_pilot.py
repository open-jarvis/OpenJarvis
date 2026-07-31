from __future__ import annotations

import os
import shutil
import socket
import uuid
from pathlib import Path

import pytest

from openjarvis.memory.vault_index import VaultIndex
from openjarvis.migration import vault_schema_pilot as pilot
from openjarvis.migration.backup import BackupKind, create_verified_backup
from openjarvis.migration.vault_schema_pilot import (
    MAPPING_VERSION,
    NAMESPACE_UUID,
    VaultSchemaPilotError,
    analyze_references,
    apply_mapping,
    build_manifest,
    build_mapping,
    patch_markdown,
    plan_patches,
    uuid_for_legacy_id,
    uuid_for_missing_id,
)


def _note(
    root: Path,
    relative: str,
    *,
    note_id: str | None,
    newline: str = "\n",
    bom: bool = False,
    extra: str = "",
    body: str = "Body\n",
) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if note_id is None:
        text = body.replace("\n", newline)
    else:
        text = (f"---\nid: {note_id}\ntype: capture\n{extra}---\n{body}").replace(
            "\n", newline
        )
    payload = text.encode("utf-8")
    if bom:
        payload = b"\xef\xbb\xbf" + payload
    path.write_bytes(payload)
    return path


def _entry(table, path: str):
    return next(item for item in table.entries if item.relative_path == path)


def test_namespace_is_fixed_and_documented_name_is_reproducible() -> None:
    assert MAPPING_VERSION == "openjarvis-vault-schema-migration-v1"
    assert NAMESPACE_UUID == uuid.uuid5(uuid.NAMESPACE_URL, MAPPING_VERSION)
    assert str(NAMESPACE_UUID) == "4898f42f-c416-5ea1-9e0e-1bafd4d2e206"


def test_uuid_v5_for_legacy_id_is_deterministic_and_nfc_normalized() -> None:
    first = uuid_for_legacy_id("  legacy-e\u0301  ")
    second = uuid_for_legacy_id("legacy-é")

    assert first == second
    assert first.version == 5


def test_uuid_v5_for_missing_id_is_path_and_hash_deterministic() -> None:
    digest = "a" * 64

    first = uuid_for_missing_id("Folder/Note.md", digest)
    second = uuid_for_missing_id("Folder/Note.md", digest)

    assert first == second
    assert first != uuid_for_missing_id("Folder/Other.md", digest)
    assert first != uuid_for_missing_id("Folder/Note.md", "b" * 64)


def test_mapping_is_independent_of_directory_enumeration_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "vault"
    _note(root, "z.md", note_id="legacy-z")
    _note(root, "a.md", note_id=None)
    first = build_mapping(root)
    original = pilot._markdown_files
    monkeypatch.setattr(
        pilot, "_markdown_files", lambda value: tuple(reversed(original(value)))
    )

    second = build_mapping(root)

    assert first == second
    assert first.mapping_sha256 == second.mapping_sha256


def test_distinct_legacy_ids_produce_distinct_uuids(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _note(root, "one.md", note_id="Legacy-One")
    _note(root, "two.md", note_id="legacy-one")

    table = build_mapping(root)

    assert len({entry.new_uuid for entry in table.entries}) == 2


def test_collision_with_existing_valid_uuid_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "vault"
    existing = uuid.uuid4()
    _note(root, "existing.md", note_id=str(existing))
    _note(root, "legacy.md", note_id="legacy")
    monkeypatch.setattr(pilot, "uuid_for_legacy_id", lambda _value: existing)

    with pytest.raises(VaultSchemaPilotError, match="overlaps"):
        build_mapping(root)


def test_existing_valid_uuid_remains_outside_mapping_and_unchanged(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vault"
    note_id = str(uuid.uuid4())
    path = _note(root, "valid.md", note_id=note_id, extra="schema_version: 1\n")
    before = path.read_bytes()

    table = build_mapping(root)

    assert table.entries == ()
    assert path.read_bytes() == before


def test_matching_legacy_id_is_preserved_without_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    path = _note(
        root,
        "note.md",
        note_id="legacy-value",
        extra="legacy_id: legacy-value\n",
    )
    table = build_mapping(root)
    entry = table.entries[0]

    patched = patch_markdown(path.read_bytes(), entry, {})

    assert patched.payload.count(b"legacy_id: legacy-value") == 1
    assert entry.legacy_id_written is False


def test_conflicting_legacy_id_stops(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _note(
        root,
        "note.md",
        note_id="legacy-value",
        extra="legacy_id: different-value\n",
    )

    with pytest.raises(VaultSchemaPilotError, match="conflicting legacy_id"):
        build_mapping(root)


@pytest.mark.parametrize("value", [2, "legacy"])
def test_conflicting_schema_version_stops(tmp_path: Path, value: object) -> None:
    root = tmp_path / "vault"
    _note(
        root,
        "note.md",
        note_id="legacy-value",
        extra=f"schema_version: {value}\n",
    )

    with pytest.raises(VaultSchemaPilotError, match="schema_version"):
        build_mapping(root)


def test_unknown_fields_comments_and_body_are_preserved(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    path = root / "note.md"
    path.parent.mkdir()
    before = (
        "---\n"
        "# header comment\n"
        "id: 'legacy-one' # id comment\n"
        "unknown: keep-me # unknown comment\n"
        "type: capture\n"
        "---\n"
        "Body stays exactly.\n"
    ).encode()
    path.write_bytes(before)
    table = build_mapping(root)

    patch = plan_patches(root, table)[0]

    assert b"# header comment" in patch.payload
    assert b"unknown: keep-me # unknown comment" in patch.payload
    assert b"id: '" in patch.payload
    assert pilot._body_bytes(patch.payload) == pilot._body_bytes(before)


@pytest.mark.parametrize(
    ("newline", "bom"),
    [("\n", False), ("\r\n", False), ("\n", True), ("\r\n", True)],
)
def test_line_endings_bom_and_body_remain_byte_exact(
    tmp_path: Path, newline: str, bom: bool
) -> None:
    root = tmp_path / "vault"
    path = _note(
        root,
        "note.md",
        note_id="legacy",
        newline=newline,
        bom=bom,
        body="Line one\nLine two\n",
    )
    before = path.read_bytes()
    table = build_mapping(root)

    patch = plan_patches(root, table)[0]

    assert patch.payload.startswith(b"\xef\xbb\xbf") is bom
    assert (b"\r\n" in patch.payload) is (newline == "\r\n")
    assert pilot._body_bytes(patch.payload) == pilot._body_bytes(before)


def test_missing_id_frontmatter_keeps_original_document_as_body(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    path = _note(root, "missing.md", note_id=None, body="# Heading\nText\n")
    before = path.read_bytes()
    table = build_mapping(root)

    patch = plan_patches(root, table)[0]

    assert pilot._body_bytes(patch.payload) == before
    assert b"schema_version: 1" in patch.payload


def test_reference_classes_are_detected_and_only_structured_field_changes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vault"
    _note(root, "target.md", note_id="legacy-target")
    source = _note(
        root,
        "source.md",
        note_id="legacy-source",
        extra=("replaces: legacy-target\nunknown_ref: legacy-target\n"),
        body=(
            "[[legacy-target]]\n"
            "[link](legacy-target)\n"
            "Free legacy-target text.\n"
            "```text\nlegacy-target\n```\n"
        ),
    )
    table = build_mapping(root)
    target = _entry(table, "target.md")
    source_entry = _entry(table, "source.md")
    before_report = analyze_references(root, table)

    patch = patch_markdown(
        source.read_bytes(),
        source_entry,
        {target.old_id: target.new_uuid},
    )

    assert f"replaces: {target.new_uuid}".encode() in patch.payload
    assert b"unknown_ref: legacy-target" in patch.payload
    assert b"[[legacy-target]]" in patch.payload
    assert b"[link](legacy-target)" in patch.payload
    assert b"Free legacy-target text." in patch.payload
    assert b"```text\nlegacy-target\n```" in patch.payload
    assert patch.structured_references_updated == 1
    assert target.detected_reference_count == 1
    totals = before_report["totals"]
    assert totals["structured_id_references"] == 1
    assert totals["unknown_frontmatter_references"] == 1
    assert totals["wikilink_references"] == 1
    assert totals["markdown_link_references"] == 1
    assert totals["free_text_references"] == 1
    assert totals["code_block_references"] == 1


def test_compare_and_swap_stops_on_before_hash_drift(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    path = _note(root, "note.md", note_id="legacy")
    table = build_mapping(root)
    path.write_bytes(path.read_bytes() + b"drift")

    with pytest.raises(VaultSchemaPilotError, match="compare-and-swap"):
        apply_mapping(root, table)


def test_apply_uses_atomic_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "vault"
    _note(root, "note.md", note_id="legacy")
    table = build_mapping(root)
    real_replace = os.replace
    calls: list[tuple[Path, Path]] = []

    def tracked(source: str | Path, target: str | Path) -> None:
        calls.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(pilot.os, "replace", tracked)

    result = apply_mapping(root, table)

    assert result.changed == 1
    assert len(calls) == 1
    assert calls[0][0].parent == calls[0][1].parent


def test_partial_failure_is_raised_and_never_reported_success(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _note(root, "one.md", note_id="legacy-one")
    _note(root, "two.md", note_id="legacy-two")
    table = build_mapping(root)

    with pytest.raises(VaultSchemaPilotError, match="partial apply failure"):
        apply_mapping(root, table, fail_after=1)


def test_second_apply_is_idempotent_noop(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _note(root, "one.md", note_id="legacy-one")
    _note(root, "two.md", note_id=None)
    table = build_mapping(root)

    first = apply_mapping(root, table)
    second = apply_mapping(root, table)

    assert first.changed == 2
    assert second.changed == 0
    assert second.unchanged == 2


def test_phase4_reindex_has_zero_errors_for_supported_synthetic_notes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vault"
    _note(root, "one.md", note_id="legacy-one")
    _note(root, "two.md", note_id=None)
    table = build_mapping(root)
    apply_mapping(root, table)

    with VaultIndex(root, tmp_path / "state" / "memory.sqlite3") as index:
        report = index.rebuild()

    assert report.indexed == 2
    assert report.parser_errors == 0


def test_rollback_copy_is_byte_exact(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _note(root, "one.md", note_id="legacy-one")
    _note(root, "two.md", note_id=None)
    before, before_hash = build_manifest(root)
    restore = tmp_path / "restore"
    shutil.copytree(root, restore, copy_function=shutil.copy2)
    table = build_mapping(root)
    apply_mapping(root, table)
    rollback = tmp_path / "rollback"
    shutil.copytree(restore, rollback, copy_function=shutil.copy2)

    restored, restored_hash = build_manifest(rollback)

    assert restored == before
    assert restored_hash == before_hash


def test_mapping_and_apply_do_not_use_network_or_external_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "vault"
    _note(root, "note.md", note_id="legacy")

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", blocked)
    table = build_mapping(root)
    result = apply_mapping(root, table)

    assert result.changed == 1


def test_full_46_note_pilot_passes_and_never_opens_real_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "backup-source"
    for index in range(41):
        _note(source, f"legacy/{index:02d}.md", note_id=f"legacy-{index:02d}")
    for index in range(5):
        _note(source, f"missing/{index:02d}.md", note_id=None)
    backup = tmp_path / "vault-backup"
    backup_result = create_verified_backup(
        source,
        backup,
        kind=BackupKind.VAULT,
        source_label="synthetic-vault",
    )
    real_vault = tmp_path / "real-vault-must-not-open"
    real_vault.mkdir()
    forbidden = real_vault / "private.md"
    forbidden.write_text("private\n", encoding="utf-8")
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):
        if path == forbidden or real_vault in path.parents:
            raise AssertionError("real Vault was opened")
        return original_open(path, *args, **kwargs)

    def blocked_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(socket, "create_connection", blocked_network)
    output = tmp_path / "phase-8b-review"

    result = pilot.run_isolated_pilot(
        backup,
        output,
        expected_source_manifest_sha256=backup_result.manifest_sha256,
        established_vault_backup_tree_sha256="b" * 64,
    )

    assert result["status"] == "passed"
    assert result["valid_legacy_id_mappings"] == 41
    assert result["missing_id_mappings"] == 5
    assert all(result["gates"].values())
    assert result["pilot_copy_removed"] is True
    assert result["restore_copy_removed"] is True
    assert result["second_apply_changed"] == 0
    assert (output / "mapping.json").is_file()
    assert (output / "before-manifest.jsonl").is_file()
    assert (output / "after-manifest.jsonl").is_file()
    assert (output / "rollback-proof.txt").is_file()
    assert not list(tmp_path.glob(".phase8b-vault-*.tmp"))
