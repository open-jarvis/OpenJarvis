"""Read-only analysis for a future, explicitly approved vault migration."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openjarvis.memory.frontmatter import read_markdown, render_with_updates
from openjarvis.memory.safe_write import unified_diff

_PLANNED_ID = "<generate-uuid-during-approved-migration>"


@dataclass(frozen=True, slots=True)
class MigrationFinding:
    kind: str
    path: str
    detail: str


@dataclass(frozen=True, slots=True)
class PlannedMigrationChange:
    path: str
    reasons: tuple[str, ...]
    expected_before_hash: str
    diff: str


@dataclass(frozen=True, slots=True)
class MigrationDryRunReport:
    dry_run: bool
    vault_root: str
    markdown_files: int
    schema_counts: dict[str, int]
    missing_ids: int
    invalid_yaml: int
    duplicate_ids: int
    parallel_folder_schemas: dict[str, int]
    possible_duplicate_groups: int
    possible_conflicts: int
    findings: tuple[MigrationFinding, ...]
    planned_changes: tuple[PlannedMigrationChange, ...]
    rollback_plan: tuple[str, ...]
    source_hashes_unchanged: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_vault_migration(vault_root: str | Path) -> MigrationDryRunReport:
    """Analyze Markdown and prepare bounded diffs without changing any file."""

    root = Path(vault_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("vault root must be an existing directory")
    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".md", ".markdown"}
    )
    before = {_relative(root, path): _hash(path.read_bytes()) for path in paths}
    schemas: Counter[str] = Counter()
    folders: Counter[str] = Counter()
    findings: list[MigrationFinding] = []
    planned: list[PlannedMigrationChange] = []
    by_id: dict[str, list[str]] = defaultdict(list)
    by_body: dict[str, list[str]] = defaultdict(list)
    by_conflict: dict[str, list[tuple[str, str]]] = defaultdict(list)
    missing_ids = 0
    invalid_yaml = 0

    for path in paths:
        relative = _relative(root, path)
        parsed, content_hash, _size = read_markdown(path)
        top_folder = relative.split("/", 1)[0] if "/" in relative else "(root)"
        folders[top_folder] += 1
        if parsed.error:
            invalid_yaml += 1
            schemas["invalid"] += 1
            findings.append(MigrationFinding("invalid_yaml", relative, parsed.error))
            continue
        if not parsed.has_frontmatter:
            schemas["no_frontmatter"] += 1
        else:
            raw_version = parsed.metadata.get("schema_version")
            version_label = raw_version if raw_version is not None else "legacy"
            schemas[f"schema_{version_label}"] += 1

        raw_id = str(parsed.metadata.get("id") or "").strip()
        if raw_id:
            by_id[raw_id].append(relative)
        else:
            missing_ids += 1
            findings.append(
                MigrationFinding(
                    "missing_id",
                    relative,
                    "A UUID would be generated only during a later approved write.",
                )
            )

        normalized_body = "\n".join(
            line.rstrip() for line in parsed.body.strip().splitlines()
        )
        if normalized_body:
            by_body[_hash(normalized_body.encode("utf-8"))].append(relative)
        conflict_key = str(parsed.metadata.get("conflict_key") or "").strip()
        if conflict_key:
            by_conflict[conflict_key.casefold()].append(
                (relative, _hash(normalized_body.encode("utf-8")))
            )

        updates: dict[str, Any] = {}
        reasons: list[str] = []
        if not raw_id:
            updates["id"] = _PLANNED_ID
            reasons.append("add stable UUID at approved migration time")
        raw_version = parsed.metadata.get("schema_version")
        if raw_version is None:
            updates["schema_version"] = 1
            reasons.append("declare frontmatter schema version 1")
        elif not isinstance(raw_version, int):
            findings.append(
                MigrationFinding(
                    "invalid_schema_version",
                    relative,
                    f"schema_version is not an integer: {raw_version!r}",
                )
            )
        elif raw_version > 1:
            findings.append(
                MigrationFinding(
                    "newer_schema",
                    relative,
                    f"schema_version {raw_version} will not be downgraded",
                )
            )
        if updates:
            proposed = render_with_updates(parsed, updates)
            planned.append(
                PlannedMigrationChange(
                    path=relative,
                    reasons=tuple(reasons),
                    expected_before_hash=content_hash,
                    diff=unified_diff(
                        parsed.raw_text,
                        proposed,
                        relative_path=relative,
                    ),
                )
            )

    duplicate_ids = 0
    for note_id, duplicate_paths in sorted(by_id.items()):
        if len(duplicate_paths) < 2:
            continue
        duplicate_ids += 1
        detail = f"ID {note_id!r} occurs in: {', '.join(duplicate_paths)}"
        findings.extend(
            MigrationFinding("duplicate_id", path, detail)
            for path in duplicate_paths
        )

    duplicate_groups = 0
    for duplicate_paths in by_body.values():
        if len(duplicate_paths) < 2:
            continue
        duplicate_groups += 1
        detail = f"Same normalized body: {', '.join(duplicate_paths)}"
        findings.extend(
            MigrationFinding("possible_duplicate", path, detail)
            for path in duplicate_paths
        )

    conflict_groups = 0
    for key, entries in sorted(by_conflict.items()):
        if len(entries) < 2 or len({digest for _path, digest in entries}) < 2:
            continue
        conflict_groups += 1
        paths_for_key = [path for path, _digest in entries]
        detail = (
            f"Conflict key {key!r} has differing bodies: "
            f"{', '.join(paths_for_key)}"
        )
        findings.extend(
            MigrationFinding("possible_conflict", path, detail)
            for path in paths_for_key
        )

    after_paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".md", ".markdown"}
    )
    after = {
        _relative(root, path): _hash(path.read_bytes())
        for path in after_paths
    }
    unchanged = before == after
    if not unchanged:
        raise RuntimeError("vault contents changed while dry-run analysis was active")
    return MigrationDryRunReport(
        dry_run=True,
        vault_root=str(root),
        markdown_files=len(paths),
        schema_counts=dict(sorted(schemas.items())),
        missing_ids=missing_ids,
        invalid_yaml=invalid_yaml,
        duplicate_ids=duplicate_ids,
        parallel_folder_schemas=dict(sorted(folders.items())),
        possible_duplicate_groups=duplicate_groups,
        possible_conflicts=conflict_groups,
        findings=tuple(findings),
        planned_changes=tuple(planned),
        rollback_plan=(
            "This dry-run performed no writes, so no rollback is required.",
            "A future apply must capture every before-hash and an external "
            "restore artifact.",
            "A future apply must use compare-and-swap atomic writes and stop on drift.",
            "A future rollback must verify the after-hash before restoring "
            "original bytes.",
        ),
        source_hashes_unchanged=True,
    )


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "MigrationDryRunReport",
    "MigrationFinding",
    "PlannedMigrationChange",
    "analyze_vault_migration",
]
