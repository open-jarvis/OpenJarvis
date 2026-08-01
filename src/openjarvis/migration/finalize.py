"""Fail-closed helpers for the final, approved Markdown Vault migration.

The Phase 8B pilot deliberately kept the immutable identity mapping coupled to
the pilot's original file hashes.  This module keeps that approved mapping
immutable and creates a separate execution plan whose compare-and-swap hashes
are bound to a fresh, verified backup of the current Vault.  Nothing in this
module discovers or widens the approved set of notes.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from openjarvis.memory.frontmatter import parse_markdown
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_policy import NOTE_TYPES
from openjarvis.migration.backup import load_manifest, verify_manifest
from openjarvis.migration.vault_note_compatibility import (
    build_compatibility_review,
)
from openjarvis.migration.vault_schema_pilot import (
    KNOWN_ID_REFERENCE_FIELDS,
    MAPPING_VERSION,
    NAMESPACE_UUID,
    FileManifestEntry,
    MappingEntry,
    MappingTable,
    PatchResult,
    _atomic_replace,
    _body_bytes,
    _decode_markdown,
    _parser_report,
    analyze_references,
    build_manifest,
    patch_markdown,
)


class FinalMigrationError(RuntimeError):
    """Raised when a final migration gate cannot be proven."""


class FinalMigrationApplyError(FinalMigrationError):
    """Raised after a failed apply has been restored byte-for-byte."""

    def __init__(self, message: str, *, rollback_verified: bool) -> None:
        super().__init__(message)
        self.rollback_verified = rollback_verified


class FinalMigrationRollbackError(FinalMigrationError):
    """Raised when an apply fails and its mandatory rollback cannot be proven."""


@dataclass(frozen=True, slots=True)
class ApprovedNoteType:
    path: str
    note_type: str


@dataclass(frozen=True, slots=True)
class ApprovedMigrationArtifacts:
    """Immutable, integrity-checked Phase 8B approval evidence."""

    mapping: MappingTable
    baseline_manifest: tuple[FileManifestEntry, ...]
    baseline_manifest_sha256: str
    note_types: tuple[ApprovedNoteType, ...]


@dataclass(frozen=True, slots=True)
class ExecutionPatch:
    """One approved identity mutation bound to the current file's CAS hash."""

    path: str
    expected_before_sha256: str
    expected_after_sha256: str
    before_size: int
    after_size: int
    body_sha256: str
    approved_mapping_hash: str
    new_uuid: str
    source_id_state: str
    old_id: str | None
    legacy_id_written: bool
    schema_version_written: bool
    structured_references_updated: int
    payload: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class FinalExecutionPlan:
    """A fully preplanned migration with a full-tree CAS boundary."""

    vault_root: Path = field(repr=False)
    approved: ApprovedMigrationArtifacts = field(repr=False)
    before_manifest: tuple[FileManifestEntry, ...]
    before_manifest_sha256: str
    expected_after_manifest: tuple[FileManifestEntry, ...]
    expected_after_manifest_sha256: str
    patches: tuple[ExecutionPatch, ...] = field(repr=False)
    reference_report_before: Mapping[str, Any]
    plan_sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedFreshBackup:
    root: Path = field(repr=False)
    data_root: Path = field(repr=False)
    data_manifest: tuple[FileManifestEntry, ...]
    data_manifest_sha256: str
    source_manifest_sha256: str
    file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class FinalMigrationOutcome:
    changed: int
    unchanged: int
    before_manifest_sha256: str
    after_manifest_sha256: str
    approved_mapping_sha256: str
    plan_sha256: str
    validation: Mapping[str, Any]
    rollback_performed: bool = False


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _canonical_jsonl(values: Iterable[Any]) -> bytes:
    payload = bytearray()
    for value in values:
        item = asdict(value) if hasattr(value, "__dataclass_fields__") else value
        payload.extend(_canonical_json(item))
    return bytes(payload)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha256(value: str, *, label: str) -> str:
    lowered = value.strip().lower()
    if len(lowered) != 64 or any(
        character not in "0123456789abcdef" for character in lowered
    ):
        raise FinalMigrationError(f"{label} is not a SHA-256 digest")
    return lowered


def _safe_relative(value: str) -> str:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if (
        not value
        or candidate.is_absolute()
        or candidate.as_posix() != value.replace("\\", "/")
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or ":" in candidate.parts[0]
    ):
        raise FinalMigrationError("migration artifact contains an unsafe path")
    return candidate.as_posix()


def _entry_hash(entry: MappingEntry) -> str:
    payload = asdict(entry)
    payload.pop("mapping_hash")
    return _sha256(_canonical_json(payload))


def _mapping_hash(entries: Sequence[MappingEntry]) -> str:
    return _sha256(
        _canonical_json(
            {
                "entries": [asdict(entry) for entry in entries],
                "mapping_version": MAPPING_VERSION,
                "namespace_uuid": str(NAMESPACE_UUID),
            }
        )
    )


def load_approved_mapping(
    path: Path,
    *,
    expected_mapping_sha256: str,
    expected_entries: int = 46,
) -> MappingTable:
    """Load and fully verify an approved mapping artifact."""

    expected = _require_sha256(
        expected_mapping_sha256, label="expected mapping SHA-256"
    )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FinalMigrationError("approved mapping cannot be read") from error
    if not isinstance(raw, dict) or set(raw) != {
        "entries",
        "mapping_sha256",
        "mapping_version",
        "namespace_uuid",
    }:
        raise FinalMigrationError("approved mapping has an unexpected shape")
    if raw["mapping_version"] != MAPPING_VERSION:
        raise FinalMigrationError("approved mapping version differs")
    if raw["namespace_uuid"] != str(NAMESPACE_UUID):
        raise FinalMigrationError("approved mapping namespace differs")
    if not isinstance(raw["entries"], list) or len(raw["entries"]) != expected_entries:
        raise FinalMigrationError("approved mapping entry count differs")

    entries: list[MappingEntry] = []
    fields = set(MappingEntry.__dataclass_fields__)
    for raw_entry in raw["entries"]:
        if not isinstance(raw_entry, dict) or set(raw_entry) != fields:
            raise FinalMigrationError("approved mapping entry has an unexpected shape")
        try:
            entry = MappingEntry(**raw_entry)
        except TypeError as error:
            raise FinalMigrationError("approved mapping entry is invalid") from error
        _safe_relative(entry.relative_path)
        if entry.mapping_version != MAPPING_VERSION:
            raise FinalMigrationError("mapping entry version differs")
        if entry.namespace_uuid != str(NAMESPACE_UUID):
            raise FinalMigrationError("mapping entry namespace differs")
        if entry.source_id_state not in {"invalid_existing", "missing"}:
            raise FinalMigrationError("mapping entry has an invalid source ID state")
        if (entry.source_id_state == "invalid_existing") != bool(entry.old_id):
            raise FinalMigrationError("mapping entry source ID state is inconsistent")
        try:
            canonical_uuid = str(uuid.UUID(entry.new_uuid))
        except ValueError as error:
            raise FinalMigrationError("mapping entry UUID is invalid") from error
        if canonical_uuid != entry.new_uuid:
            raise FinalMigrationError("mapping entry UUID is not canonical")
        _require_sha256(entry.before_sha256, label="mapping before SHA-256")
        _require_sha256(entry.mapping_hash, label="mapping entry SHA-256")
        if _entry_hash(entry) != entry.mapping_hash:
            raise FinalMigrationError("mapping entry hash differs")
        entries.append(entry)

    ordered = tuple(sorted(entries, key=lambda item: item.relative_path))
    if tuple(entries) != ordered:
        raise FinalMigrationError("approved mapping entries are not canonical")
    if len({entry.relative_path for entry in ordered}) != len(ordered):
        raise FinalMigrationError("approved mapping contains duplicate paths")
    if len({entry.new_uuid for entry in ordered}) != len(ordered):
        raise FinalMigrationError("approved mapping contains duplicate UUIDs")
    logical_sha256 = _mapping_hash(ordered)
    if raw["mapping_sha256"] != expected or logical_sha256 != expected:
        raise FinalMigrationError("approved mapping logical SHA-256 differs")
    return MappingTable(
        mapping_version=MAPPING_VERSION,
        namespace_uuid=str(NAMESPACE_UUID),
        entries=ordered,
        mapping_sha256=logical_sha256,
    )


def load_approved_baseline(
    path: Path,
    *,
    expected_manifest_sha256: str,
    expected_files: int = 59,
) -> tuple[tuple[FileManifestEntry, ...], str]:
    """Load the exact approved set of paths without treating hashes as current CAS."""

    expected = _require_sha256(
        expected_manifest_sha256, label="approved baseline SHA-256"
    )
    entries: list[FileManifestEntry] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict) or set(raw) != {"path", "sha256", "size"}:
                raise FinalMigrationError("approved baseline entry shape differs")
            entry = FileManifestEntry(**raw)
            _safe_relative(entry.path)
            _require_sha256(entry.sha256, label="approved baseline file SHA-256")
            if entry.size < 0:
                raise FinalMigrationError("approved baseline contains a negative size")
            entries.append(entry)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
        if isinstance(error, FinalMigrationError):
            raise
        raise FinalMigrationError("approved baseline cannot be read") from error
    ordered = tuple(sorted(entries, key=lambda item: item.path))
    if tuple(entries) != ordered or len({entry.path for entry in ordered}) != len(
        ordered
    ):
        raise FinalMigrationError("approved baseline paths are not canonical")
    if len(ordered) != expected_files:
        raise FinalMigrationError("approved baseline file count differs")
    digest = _sha256(_canonical_jsonl(ordered))
    if digest != expected:
        raise FinalMigrationError("approved baseline manifest SHA-256 differs")
    return ordered, digest


def load_approved_note_types(
    path: Path,
    *,
    expected_notes: int = 46,
) -> tuple[ApprovedNoteType, ...]:
    """Load the approved path-to-type relation from the metadata-only report."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FinalMigrationError("approved parser report cannot be read") from error
    records = raw.get("records") if isinstance(raw, dict) else None
    if not isinstance(records, list) or len(records) != expected_notes:
        raise FinalMigrationError("approved parser report note count differs")
    entries: list[ApprovedNoteType] = []
    for record in records:
        if not isinstance(record, dict):
            raise FinalMigrationError("approved parser report record is invalid")
        relative = _safe_relative(str(record.get("relative_path", "")))
        note_type = str(record.get("note_type", ""))
        if note_type not in NOTE_TYPES:
            raise FinalMigrationError("approved parser report contains an unknown type")
        if record.get("type_supported") is not True:
            raise FinalMigrationError(
                "approved parser report contains an unsupported type"
            )
        entries.append(ApprovedNoteType(relative, note_type))
    ordered = tuple(sorted(entries, key=lambda item: item.path))
    if len({entry.path for entry in ordered}) != len(ordered):
        raise FinalMigrationError("approved parser report contains duplicate paths")
    return ordered


def load_approved_artifacts(
    review_root: Path,
    *,
    expected_mapping_sha256: str,
    expected_baseline_sha256: str,
) -> ApprovedMigrationArtifacts:
    """Load the three immutable Phase 8B artifacts needed by the final plan."""

    mapping = load_approved_mapping(
        review_root / "mapping.json",
        expected_mapping_sha256=expected_mapping_sha256,
    )
    baseline, baseline_hash = load_approved_baseline(
        review_root / "before-manifest.jsonl",
        expected_manifest_sha256=expected_baseline_sha256,
    )
    note_types = load_approved_note_types(review_root / "parser-status-report.json")
    mapping_paths = {entry.relative_path for entry in mapping.entries}
    markdown_paths = {
        entry.path
        for entry in baseline
        if PurePosixPath(entry.path).suffix.casefold() in {".md", ".markdown"}
    }
    type_paths = {entry.path for entry in note_types}
    if mapping_paths != markdown_paths or mapping_paths != type_paths:
        raise FinalMigrationError("approved mapping, baseline, and type paths differ")
    return ApprovedMigrationArtifacts(
        mapping=mapping,
        baseline_manifest=baseline,
        baseline_manifest_sha256=baseline_hash,
        note_types=note_types,
    )


def _backup_manifest_digest(entries: Iterable[Any]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(
            json.dumps(asdict(entry), sort_keys=True, separators=(",", ":")).encode()
        )
        digest.update(b"\n")
    return digest.hexdigest()


def verify_fresh_vault_backup(
    backup_root: Path,
    *,
    expected_data_manifest: tuple[FileManifestEntry, ...] | None = None,
) -> VerifiedFreshBackup:
    """Verify every retained backup copy and its source-stability evidence."""

    backup_root = backup_root.absolute()
    data = backup_root / "data"
    manifests = backup_root / "manifests"
    if (
        not backup_root.is_dir()
        or _is_reparse(backup_root)
        or not data.is_dir()
        or _is_reparse(data)
        or not manifests.is_dir()
        or _is_reparse(manifests)
    ):
        raise FinalMigrationError("fresh Vault backup roots are not safe directories")
    try:
        summary = json.loads((manifests / "summary.json").read_text(encoding="utf-8"))
        source_before = load_manifest(manifests / "source-before.jsonl")
        source_after = load_manifest(manifests / "source-after.jsonl")
        copied = load_manifest(manifests / "backup.jsonl")
        restored = load_manifest(manifests / "restore.jsonl")
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
        raise FinalMigrationError(
            "fresh Vault backup evidence cannot be read"
        ) from error
    if summary.get("backup_kind") != "vault":
        raise FinalMigrationError("fresh backup kind is not Vault")
    if not all(
        summary.get(field) is True
        for field in ("source_stable", "restore_verified", "restore_probe_removed")
    ):
        raise FinalMigrationError("fresh Vault backup stability proof is incomplete")
    if not source_before or not (source_before == source_after == copied == restored):
        raise FinalMigrationError("fresh Vault backup manifests differ")
    if summary.get("manifest_sha256") != _backup_manifest_digest(source_before):
        raise FinalMigrationError("fresh Vault source manifest digest differs")
    if not verify_manifest(data, source_before):
        raise FinalMigrationError("fresh Vault backup data differs from its manifest")
    data_manifest, data_hash = build_manifest(data)
    if expected_data_manifest is not None and data_manifest != expected_data_manifest:
        raise FinalMigrationError(
            "fresh Vault backup is not byte-equal to current Before"
        )
    if summary.get("file_count") != len(data_manifest):
        raise FinalMigrationError("fresh Vault backup file count differs")
    total_bytes = sum(entry.size for entry in data_manifest)
    if summary.get("total_bytes") != total_bytes:
        raise FinalMigrationError("fresh Vault backup byte count differs")
    return VerifiedFreshBackup(
        root=backup_root,
        data_root=data,
        data_manifest=data_manifest,
        data_manifest_sha256=data_hash,
        source_manifest_sha256=str(summary["manifest_sha256"]),
        file_count=len(data_manifest),
        total_bytes=total_bytes,
    )


def _iter_scalar_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _iter_scalar_strings(child)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for child in value:
            yield from _iter_scalar_strings(child)


def _current_note_metadata(
    root: Path,
    approved: ApprovedMigrationArtifacts,
) -> dict[str, Mapping[str, Any]]:
    type_by_path = {entry.path: entry.note_type for entry in approved.note_types}
    metadata_by_path: dict[str, Mapping[str, Any]] = {}
    for entry in approved.mapping.entries:
        path = root.joinpath(*PurePosixPath(entry.relative_path).parts)
        try:
            text, _bom = _decode_markdown(path.read_bytes())
        except OSError as error:
            raise FinalMigrationError("an approved note cannot be read") from error
        parsed = parse_markdown(text)
        if parsed.error:
            raise FinalMigrationError("current note frontmatter cannot be parsed")
        metadata = parsed.metadata
        current_type = str(metadata.get("type") or "capture").strip()
        if (
            current_type not in NOTE_TYPES
            or current_type != type_by_path[entry.relative_path]
        ):
            raise FinalMigrationError("current note type differs from the approval")
        raw_id = metadata.get("id")
        current_id = str(raw_id) if raw_id not in (None, "") else None
        current_legacy = metadata.get("legacy_id")
        schema = metadata.get("schema_version")
        if schema not in (None, 1):
            raise FinalMigrationError("current note has a conflicting schema_version")
        if entry.source_id_state == "invalid_existing":
            if current_id != entry.old_id:
                raise FinalMigrationError(
                    "current legacy ID state differs from approval"
                )
            if current_legacy not in (None, entry.old_id):
                raise FinalMigrationError("current note has a conflicting legacy_id")
        else:
            if current_id is not None:
                raise FinalMigrationError(
                    "current missing-ID state differs from approval"
                )
            if current_legacy not in (None, ""):
                raise FinalMigrationError("missing-ID note has a conflicting legacy_id")
        metadata_by_path[entry.relative_path] = metadata
    return metadata_by_path


def _reference_gates(
    root: Path,
    approved: ApprovedMigrationArtifacts,
    metadata_by_path: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    old_to_entry = {
        entry.old_id: entry
        for entry in approved.mapping.entries
        if entry.old_id is not None
    }
    structured_counts: Counter[str] = Counter()
    for metadata in metadata_by_path.values():
        for key, value in metadata.items():
            if str(key).casefold() not in KNOWN_ID_REFERENCE_FIELDS:
                continue
            for scalar in _iter_scalar_strings(value):
                if scalar in old_to_entry:
                    structured_counts[scalar] += 1
    if any(
        structured_counts.get(old_id, 0) != entry.detected_reference_count
        for old_id, entry in old_to_entry.items()
    ):
        raise FinalMigrationError("structured ID references differ from approval")
    report = analyze_references(root, approved.mapping)
    totals = report["totals"]
    unknown = sum(
        int(totals.get(field, 0))
        for field in (
            "unknown_frontmatter_references",
            "wikilink_references",
            "markdown_link_references",
            "free_text_references",
            "code_block_references",
        )
    )
    if unknown:
        raise FinalMigrationError("current Vault has an unapproved reference blocker")
    return report


def _execution_patch(patch: PatchResult, entry: MappingEntry) -> ExecutionPatch:
    return ExecutionPatch(
        path=patch.path,
        expected_before_sha256=patch.before_sha256,
        expected_after_sha256=patch.after_sha256,
        before_size=patch.before_size,
        after_size=patch.after_size,
        body_sha256=patch.body_sha256,
        approved_mapping_hash=entry.mapping_hash,
        new_uuid=entry.new_uuid,
        source_id_state=entry.source_id_state,
        old_id=entry.old_id,
        legacy_id_written=patch.legacy_id_written,
        schema_version_written=patch.schema_version_written,
        structured_references_updated=patch.structured_references_updated,
        payload=patch.payload,
    )


def _patch_metadata(patch: ExecutionPatch) -> dict[str, Any]:
    return {
        "after_sha256": patch.expected_after_sha256,
        "after_size": patch.after_size,
        "approved_mapping_hash": patch.approved_mapping_hash,
        "before_sha256": patch.expected_before_sha256,
        "before_size": patch.before_size,
        "body_sha256": patch.body_sha256,
        "legacy_id_written": patch.legacy_id_written,
        "path": patch.path,
        "schema_version_written": patch.schema_version_written,
        "structured_references_updated": patch.structured_references_updated,
    }


def build_final_execution_plan(
    current_root: Path,
    approved: ApprovedMigrationArtifacts,
    fresh_backup_root: Path,
) -> FinalExecutionPlan:
    """Perform the complete read-only delta check and preplan all mutations."""

    current_root = current_root.absolute()
    if not current_root.is_dir():
        raise FinalMigrationError("current Vault root is not a directory")
    backup_absolute = fresh_backup_root.absolute()
    if (
        current_root == backup_absolute
        or current_root in backup_absolute.parents
        or backup_absolute in current_root.parents
    ):
        raise FinalMigrationError("current Vault and fresh backup roots overlap")
    before, before_hash = build_manifest(current_root)
    approved_paths = {entry.path for entry in approved.baseline_manifest}
    current_paths = {entry.path for entry in before}
    if current_paths != approved_paths or len(before) != 59:
        raise FinalMigrationError(
            "current Vault paths differ from the 59-file approval"
        )
    markdown_paths = {
        entry.path
        for entry in before
        if PurePosixPath(entry.path).suffix.casefold() in {".md", ".markdown"}
    }
    mapping_paths = {entry.relative_path for entry in approved.mapping.entries}
    if markdown_paths != mapping_paths or len(markdown_paths) != 46:
        raise FinalMigrationError(
            "current Markdown paths differ from the 46-note approval"
        )
    verified_backup = verify_fresh_vault_backup(
        fresh_backup_root, expected_data_manifest=before
    )
    if verified_backup.data_manifest_sha256 != before_hash:
        raise FinalMigrationError("fresh backup and current Before hashes differ")

    metadata = _current_note_metadata(current_root, approved)
    reference_report = _reference_gates(current_root, approved, metadata)
    current_by_path = {entry.path: entry for entry in before}
    replacements = {
        entry.old_id: entry.new_uuid
        for entry in approved.mapping.entries
        if entry.old_id is not None
    }
    patches: list[ExecutionPatch] = []
    for approved_entry in approved.mapping.entries:
        current_entry = current_by_path[approved_entry.relative_path]
        cas_entry = replace(
            approved_entry,
            before_sha256=current_entry.sha256,
            # This is an execution-only binding.  The approved entry hash and
            # table hash remain immutable and are recorded separately.
            mapping_hash=approved_entry.mapping_hash,
        )
        path = current_root.joinpath(*PurePosixPath(approved_entry.relative_path).parts)
        planned = patch_markdown(path.read_bytes(), cas_entry, replacements)
        patches.append(_execution_patch(planned, approved_entry))
    ordered_patches = tuple(sorted(patches, key=lambda item: item.path))
    patch_by_path = {patch.path: patch for patch in ordered_patches}
    expected_after = tuple(
        FileManifestEntry(
            path=entry.path,
            size=(
                patch_by_path[entry.path].after_size
                if entry.path in patch_by_path
                else entry.size
            ),
            sha256=(
                patch_by_path[entry.path].expected_after_sha256
                if entry.path in patch_by_path
                else entry.sha256
            ),
        )
        for entry in before
    )
    expected_after_hash = _sha256(_canonical_jsonl(expected_after))
    plan_payload = {
        "approved_baseline_sha256": approved.baseline_manifest_sha256,
        "approved_mapping_sha256": approved.mapping.mapping_sha256,
        "before_manifest_sha256": before_hash,
        "expected_after_manifest_sha256": expected_after_hash,
        "patches": [_patch_metadata(item) for item in ordered_patches],
    }
    return FinalExecutionPlan(
        vault_root=current_root,
        approved=approved,
        before_manifest=before,
        before_manifest_sha256=before_hash,
        expected_after_manifest=expected_after,
        expected_after_manifest_sha256=expected_after_hash,
        patches=ordered_patches,
        reference_report_before=reference_report,
        plan_sha256=_sha256(_canonical_json(plan_payload)),
    )


def _is_reparse(path: Path) -> bool:
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & flag)


def _assert_safe_target(root: Path, relative: str) -> Path:
    current = root
    if _is_reparse(current):
        raise FinalMigrationError("Vault root became a reparse point")
    for part in PurePosixPath(relative).parts:
        current = current / part
        if not current.exists() or _is_reparse(current):
            raise FinalMigrationError("approved file ancestry became unsafe")
    resolved_root = root.resolve(strict=True)
    resolved = current.resolve(strict=True)
    if resolved_root not in resolved.parents:
        raise FinalMigrationError("approved file escaped the Vault root")
    return current


def _remove_tree(path: Path) -> None:
    def writable(function: Any, target: str, _error: Any) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onerror=writable)


def _copy_tree_verified(
    source: Path,
    destination: Path,
    expected: tuple[FileManifestEntry, ...],
) -> None:
    if destination.exists():
        raise FinalMigrationRollbackError("rollback destination already exists")
    build_manifest(source)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    copied, _copied_hash = build_manifest(destination)
    if copied != expected:
        _remove_tree(destination)
        raise FinalMigrationRollbackError("rollback copy is not byte-equal to Before")


def _restore_in_place(
    root: Path,
    backup: VerifiedFreshBackup,
    expected: tuple[FileManifestEntry, ...],
) -> None:
    parent = root.parent
    restore = parent / f".{root.name}.restore-{uuid.uuid4().hex}.tmp"
    quarantine = parent / f".{root.name}.failed-{uuid.uuid4().hex}.tmp"
    _copy_tree_verified(backup.data_root, restore, expected)
    moved_original = False
    rollback_verified = False
    try:
        os.replace(root, quarantine)
        moved_original = True
        try:
            os.replace(restore, root)
        except Exception:
            os.replace(quarantine, root)
            moved_original = False
            raise
        restored, _restored_hash = build_manifest(root)
        if restored != expected:
            raise FinalMigrationRollbackError("in-place rollback differs from Before")
        rollback_verified = True
        _remove_tree(quarantine)
        moved_original = False
    finally:
        _remove_tree(restore)
        if moved_original and quarantine.exists() and not root.exists():
            os.replace(quarantine, root)
            moved_original = False
        if (
            moved_original
            and rollback_verified
            and quarantine.exists()
            and root.exists()
        ):
            # The verified Before is already live at *root*.  The quarantine
            # contains only the failed partial state and is safe to remove.
            _remove_tree(quarantine)
        elif moved_original and quarantine.exists() and root.exists():
            failed_restore = parent / f".{root.name}.unverified-{uuid.uuid4().hex}.tmp"
            os.replace(root, failed_restore)
            try:
                os.replace(quarantine, root)
                moved_original = False
            finally:
                _remove_tree(failed_restore)


def _note_validation(plan: FinalExecutionPlan) -> Mapping[str, Any]:
    type_by_path = {entry.path: entry.note_type for entry in plan.approved.note_types}
    valid_uuid = exact_legacy = schema_v1 = body_equal = type_equal = 0
    ids: list[str] = []
    for patch in plan.patches:
        path = plan.vault_root.joinpath(*PurePosixPath(patch.path).parts)
        payload = path.read_bytes()
        text, _bom = _decode_markdown(payload)
        parsed = parse_markdown(text)
        if parsed.error:
            continue
        current_id = str(parsed.metadata.get("id") or "")
        try:
            parsed_uuid = str(uuid.UUID(current_id))
        except ValueError:
            parsed_uuid = ""
        valid_uuid += int(parsed_uuid == patch.new_uuid)
        ids.append(current_id)
        schema_v1 += int(parsed.metadata.get("schema_version") == 1)
        if patch.old_id is not None:
            exact_legacy += int(parsed.metadata.get("legacy_id") == patch.old_id)
        body_equal += int(_sha256(_body_bytes(payload)) == patch.body_sha256)
        note_type = str(parsed.metadata.get("type") or "capture").strip()
        type_equal += int(note_type == type_by_path[patch.path])
    return {
        "body_equal": body_equal,
        "duplicate_ids": len(ids) - len(set(ids)),
        "exact_legacy_ids": exact_legacy,
        "schema_v1": schema_v1,
        "type_equal": type_equal,
        "valid_approved_uuid": valid_uuid,
    }


def validate_final_state(
    plan: FinalExecutionPlan,
    state_root: Path,
    *,
    cleanup_state: bool = True,
) -> Mapping[str, Any]:
    """Validate file, parser, index, retrieval, and authority boundaries."""

    state_root = state_root.absolute()
    if state_root.exists():
        raise FinalMigrationError("validation state root must not already exist")
    if (
        plan.vault_root == state_root
        or plan.vault_root in state_root.parents
        or state_root in plan.vault_root.parents
    ):
        raise FinalMigrationError("validation state must be outside the Vault")
    try:
        after, after_hash = build_manifest(plan.vault_root)
        if after != plan.expected_after_manifest:
            raise FinalMigrationError(
                "After manifest differs from the preplanned result"
            )
        note_validation = _note_validation(plan)
        parser = _parser_report(plan.vault_root, state_root)
        compatibility = build_compatibility_review(
            plan.vault_root,
            state_root,
            plan.approved.mapping,
            parser,
        )
        references = analyze_references(plan.vault_root, plan.approved.mapping)
        reference_total = sum(int(value) for value in references["totals"].values())
        gates = {
            "after_manifest_exact": after_hash == plan.expected_after_manifest_sha256,
            "all_46_approved_uuid": note_validation["valid_approved_uuid"] == 46,
            "all_46_body_bytes_equal": note_validation["body_equal"] == 46,
            "all_46_schema_v1": note_validation["schema_v1"] == 46,
            "all_46_types_unchanged": note_validation["type_equal"] == 46,
            "exact_41_legacy_ids": note_validation["exact_legacy_ids"] == 41,
            "files_59": len(after) == 59,
            "no_duplicate_ids": note_validation["duplicate_ids"] == 0,
            "no_remaining_legacy_references": reference_total == 0,
            "parser_errors_zero": parser["parser_errors"] == 0,
            "process_restart_readback_46": parser["process_restart_readback_indexed"]
            == 46,
        }
        gates.update(
            {
                f"compatibility_{name}": bool(value)
                for name, value in compatibility["gates"].items()
            }
        )
        result = {
            "after_manifest_sha256": after_hash,
            "approved_mapping_sha256": plan.approved.mapping.mapping_sha256,
            "compatibility_summary": compatibility["summary"],
            "gates": gates,
            "note_validation": note_validation,
            "parser": parser,
            "reference_totals": references["totals"],
            "status": "passed" if all(gates.values()) else "failed_gates",
        }
        return result
    finally:
        if cleanup_state:
            _remove_tree(state_root)


def apply_final_migration(
    plan: FinalExecutionPlan,
    fresh_backup_root: Path,
    validation_state_root: Path,
    *,
    _fail_after: int | None = None,
) -> FinalMigrationOutcome:
    """Apply the complete plan and roll the whole Vault back on any later error."""

    current, current_hash = build_manifest(plan.vault_root)
    if current != plan.before_manifest or current_hash != plan.before_manifest_sha256:
        raise FinalMigrationError("full-tree compare-and-swap failed before Apply")
    backup = verify_fresh_vault_backup(
        fresh_backup_root, expected_data_manifest=plan.before_manifest
    )
    changed = 0
    mutated = False
    try:
        for position, patch in enumerate(plan.patches, start=1):
            path = _assert_safe_target(plan.vault_root, patch.path)
            current_payload = path.read_bytes()
            if _sha256(current_payload) != patch.expected_before_sha256:
                raise FinalMigrationError("per-file compare-and-swap failed")
            if current_payload != patch.payload:
                _atomic_replace(path, patch.payload)
                mutated = True
                changed += 1
            if _sha256(path.read_bytes()) != patch.expected_after_sha256:
                raise FinalMigrationError("post-replace file hash differs")
            if _fail_after is not None and position >= _fail_after:
                raise FinalMigrationError("synthetic final migration failure")
        after, after_hash = build_manifest(plan.vault_root)
        if after != plan.expected_after_manifest:
            raise FinalMigrationError("full After manifest differs")
        validation = validate_final_state(plan, validation_state_root)
        if validation["status"] != "passed":
            raise FinalMigrationError("post-Apply migration validation failed")
        return FinalMigrationOutcome(
            changed=changed,
            unchanged=len(plan.patches) - changed,
            before_manifest_sha256=plan.before_manifest_sha256,
            after_manifest_sha256=after_hash,
            approved_mapping_sha256=plan.approved.mapping.mapping_sha256,
            plan_sha256=plan.plan_sha256,
            validation=validation,
        )
    except Exception as error:
        if not mutated:
            raise
        try:
            _restore_in_place(plan.vault_root, backup, plan.before_manifest)
        except Exception as rollback_error:
            raise FinalMigrationRollbackError(
                "final migration failed and byte-exact rollback could not be proven"
            ) from rollback_error
        raise FinalMigrationApplyError(
            "final migration failed; byte-exact in-place rollback completed",
            rollback_verified=True,
        ) from error


def _exclusive_write(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def emit_final_migration_artifacts(
    output_root: Path,
    plan: FinalExecutionPlan,
    outcome: FinalMigrationOutcome,
) -> tuple[Path, ...]:
    """Emit content-free final manifests, diff, and proof with relative paths only."""

    output_root = output_root.absolute()
    if output_root == plan.vault_root or plan.vault_root in output_root.parents:
        raise FinalMigrationError("final migration artifacts must be outside the Vault")
    output_root.mkdir(parents=True, exist_ok=True)
    names = (
        "vault-before-manifest.jsonl",
        "vault-after-manifest.jsonl",
        "vault-migration-diff.jsonl",
        "real-vault-migration-proof.txt",
    )
    if any((output_root / name).exists() for name in names):
        raise FinalMigrationError("final migration artifact already exists")
    staging = Path(tempfile.mkdtemp(prefix=".final-migration-", dir=output_root))
    try:
        _exclusive_write(staging / names[0], _canonical_jsonl(plan.before_manifest))
        _exclusive_write(
            staging / names[1], _canonical_jsonl(plan.expected_after_manifest)
        )
        _exclusive_write(
            staging / names[2],
            _canonical_jsonl(_patch_metadata(patch) for patch in plan.patches),
        )
        proof = (
            "OpenJarvis final real Vault migration proof\n"
            f"approved_mapping_sha256: {outcome.approved_mapping_sha256}\n"
            f"before_manifest_sha256: {outcome.before_manifest_sha256}\n"
            f"after_manifest_sha256: {outcome.after_manifest_sha256}\n"
            f"plan_sha256: {outcome.plan_sha256}\n"
            f"changed_files: {outcome.changed}\n"
            f"unchanged_files: {outcome.unchanged}\n"
            f"validation_status: {outcome.validation['status']}\n"
            "relative_paths_only: true\n"
            "rollback_performed: false\n"
        ).encode("utf-8")
        _exclusive_write(staging / names[3], proof)
        published: list[Path] = []
        try:
            for name in names:
                destination = output_root / name
                if destination.exists():
                    raise FinalMigrationError(
                        "final migration artifact appeared during publish"
                    )
                os.rename(staging / name, destination)
                published.append(destination)
            return tuple(published)
        except Exception:
            for path in published:
                path.unlink(missing_ok=True)
            raise
    finally:
        _remove_tree(staging)


def run_verified_rollback_probe(
    fresh_backup_root: Path,
    restore_root: Path,
    *,
    approved: ApprovedMigrationArtifacts | None = None,
    cleanup: bool = True,
) -> Mapping[str, Any]:
    """Restore the fresh Before into a new root, diagnose, optionally replan, clean."""

    backup = verify_fresh_vault_backup(fresh_backup_root)
    restore_root = restore_root.absolute()
    if restore_root.exists():
        raise FinalMigrationError("rollback probe root must not already exist")
    if (
        backup.root == restore_root
        or backup.root in restore_root.parents
        or restore_root in backup.root.parents
    ):
        raise FinalMigrationError("rollback probe and backup roots overlap")
    state = restore_root.parent / f".{restore_root.name}.state-{uuid.uuid4().hex}.tmp"
    result: dict[str, Any] | None = None
    try:
        _copy_tree_verified(backup.data_root, restore_root, backup.data_manifest)
        restored, restored_hash = build_manifest(restore_root)
        with VaultIndex(
            restore_root,
            state / "memory.sqlite3",
            mode="read-only",
            embeddings_enabled=False,
        ) as index:
            diagnostic = index.rebuild()
        replanned_sha256: str | None = None
        if approved is not None:
            replanned = build_final_execution_plan(
                restore_root, approved, fresh_backup_root
            )
            replanned_sha256 = replanned.plan_sha256
        result = {
            "before_manifest_sha256": restored_hash,
            "byte_exact": restored == backup.data_manifest,
            "diagnostic_mode": "read-only",
            "diagnostic_scanned": diagnostic.scanned,
            "file_count": len(restored),
            "replanned_sha256": replanned_sha256,
            "restore_removed": False,
        }
        return result
    finally:
        _remove_tree(state)
        if cleanup:
            _remove_tree(restore_root)
        if result is not None:
            result["restore_removed"] = not restore_root.exists()


__all__ = [
    "ApprovedMigrationArtifacts",
    "ApprovedNoteType",
    "ExecutionPatch",
    "FinalExecutionPlan",
    "FinalMigrationApplyError",
    "FinalMigrationError",
    "FinalMigrationOutcome",
    "FinalMigrationRollbackError",
    "VerifiedFreshBackup",
    "apply_final_migration",
    "build_final_execution_plan",
    "emit_final_migration_artifacts",
    "load_approved_artifacts",
    "load_approved_baseline",
    "load_approved_mapping",
    "load_approved_note_types",
    "run_verified_rollback_probe",
    "validate_final_state",
    "verify_fresh_vault_backup",
]
