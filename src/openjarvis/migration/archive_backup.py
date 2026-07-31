"""Atomic, policy-bound Phase 8A content archives and restore probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from openjarvis.migration.planner import (
    CONTENT_CATEGORIES,
    BackupPlan,
    PathCategory,
    PlanEntry,
    create_backup_plan,
    plan_to_dict,
)


class ArchiveBackupError(RuntimeError):
    """Raised when an archive cannot be proven policy-safe and restorable."""


RUNTIME_INVENTORY_CATEGORIES = frozenset(
    {
        PathCategory.RUNTIME_STATE_METADATA_ONLY,
        PathCategory.MODEL_ARTIFACT_METADATA_ONLY,
        PathCategory.TECHNICAL_CACHE_EXCLUDED,
        PathCategory.TEMPORARY_EXCLUDED,
        PathCategory.CREDENTIAL_OR_SESSION_PROHIBITED,
        PathCategory.BROWSER_RUNTIME_PROHIBITED,
    }
)
PROHIBITED_CATEGORIES = frozenset(
    {
        PathCategory.CREDENTIAL_OR_SESSION_PROHIBITED,
        PathCategory.BROWSER_RUNTIME_PROHIBITED,
    }
)
CONTENT_PREFIX = "content/"
CONTENT_MANIFEST_NAME = "manifest/content-manifest.jsonl"
ARCHIVE_METADATA_NAME = "manifest/archive-metadata.json"


@dataclass(frozen=True, slots=True)
class ContentManifestEntry:
    path: str
    size: int
    sha256: str
    category: str


@dataclass(frozen=True, slots=True)
class GitState:
    head: str
    status: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArchiveBackupResult:
    archive: Path
    runtime_inventory: Path
    proof: Path
    archive_sha256: str
    content_manifest_sha256: str
    content_file_count: int
    content_total_bytes: int
    runtime_inventory_entry_count: int
    source_stable: bool
    git_head: str | None
    git_status_count: int | None
    restore_verified: bool
    restore_probe_removed: bool


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
    chunks: list[bytes] = []
    for value in values:
        payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
        chunks.append(_canonical_json(payload))
    return b"".join(chunks)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    metadata = os.lstat(path)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def _safe_relative(value: str) -> PurePosixPath:
    if not value or value == "." or "\\" in value:
        raise ArchiveBackupError("archive path is not canonical POSIX-relative")
    relative = PurePosixPath(value)
    if relative.as_posix() != value:
        raise ArchiveBackupError("archive path is not canonical POSIX-relative")
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ArchiveBackupError("archive path contains an unsafe segment")
    if any(":" in part for part in relative.parts):
        raise ArchiveBackupError("archive path contains a drive prefix or ADS marker")
    return relative


def _source_path(source: Path, relative_text: str) -> Path:
    relative = _safe_relative(relative_text)
    return source.joinpath(*relative.parts)


def _ensure_no_reparse_ancestry(source: Path, relative_text: str) -> Path:
    current = source
    for part in _safe_relative(relative_text).parts:
        current = current / part
        if _is_reparse(current):
            raise ArchiveBackupError(
                f"reparse point appeared in content path: {relative_text}"
            )
    return current


def _identity(path: Path) -> tuple[int, int, int, int]:
    metadata = path.stat(follow_symlinks=False)
    return (
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ino,
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    return info


def _content_entries(plan: BackupPlan) -> tuple[PlanEntry, ...]:
    return tuple(
        entry
        for entry in plan.entries
        if entry.entry_type == "file" and entry.category in CONTENT_CATEGORIES
    )


def _validate_plan(plan: BackupPlan) -> None:
    if not plan.source_stable or not plan.simulation.passed:
        raise ArchiveBackupError("backup policy simulation did not pass")
    if plan.simulation.unknown_count or plan.simulation.unknown_long_path_count:
        raise ArchiveBackupError("backup policy contains unknown paths")
    if plan.simulation.migration_long_path_count:
        raise ArchiveBackupError("backup policy contains migration long paths")
    if plan.simulation.prohibited_content_backup_count:
        raise ArchiveBackupError("backup policy permits prohibited content")
    if plan.simulation.prohibited_descendant_entry_count:
        raise ArchiveBackupError("prohibited roots were recursively inventoried")

    prohibited_prefixes = tuple(
        f"{entry.path}/"
        for entry in plan.entries
        if entry.entry_type == "directory" and entry.category in PROHIBITED_CATEGORIES
    )
    for entry in plan.entries:
        _safe_relative(entry.path)
        is_content = entry.category in CONTENT_CATEGORIES
        if entry.backup_decision == "content_backup" and not is_content:
            raise ArchiveBackupError("non-migration category entered content backup")
        if is_content and (
            not entry.content_access_allowed or not entry.hashing_allowed
        ):
            raise ArchiveBackupError("migration content lacks explicit access policy")
        if not is_content and (entry.content_access_allowed or entry.hashing_allowed):
            raise ArchiveBackupError("excluded category permits content access")
        if any(entry.path.startswith(prefix) for prefix in prohibited_prefixes):
            raise ArchiveBackupError("prohibited descendant is present in the plan")


def _plan_digest(plan: BackupPlan) -> str:
    return _sha256_bytes(_canonical_json(plan_to_dict(plan)))


def _git_state(source: Path) -> GitState:
    def run(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", os.fspath(source), *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            timeout=60,
        )
        return completed.stdout

    head = run("rev-parse", "HEAD").strip()
    status = tuple(
        run("status", "--porcelain=v1", "--untracked-files=all").splitlines()
    )
    return GitState(head=head, status=status)


def _git_status_digest(state: GitState) -> str:
    return _sha256_bytes(("\n".join(state.status) + "\n").encode("utf-8"))


def _write_content_archive(
    source: Path,
    temporary_archive: Path,
    plan: BackupPlan,
    *,
    source_label: str,
) -> tuple[tuple[ContentManifestEntry, ...], bytes, bytes]:
    manifests: list[ContentManifestEntry] = []
    with zipfile.ZipFile(
        temporary_archive,
        "x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for entry in _content_entries(plan):
            source_file = _ensure_no_reparse_ancestry(source, entry.path)
            before = _identity(source_file)
            if not stat.S_ISREG(before[0]):
                raise ArchiveBackupError(
                    f"content path is not a regular file: {entry.path}"
                )
            if entry.size != before[1] or entry.mtime_ns != before[2]:
                raise ArchiveBackupError(
                    f"content changed after planning: {entry.path}"
                )

            digest = hashlib.sha256()
            archive_name = f"{CONTENT_PREFIX}{entry.path}"
            _safe_relative(archive_name)
            with source_file.open("rb") as source_stream:
                with archive.open(
                    _zip_info(archive_name), "w", force_zip64=True
                ) as target:
                    for block in iter(lambda: source_stream.read(1024 * 1024), b""):
                        digest.update(block)
                        target.write(block)
            if _identity(source_file) != before:
                raise ArchiveBackupError(
                    f"content changed while archiving: {entry.path}"
                )
            manifests.append(
                ContentManifestEntry(
                    path=entry.path,
                    size=before[1],
                    sha256=digest.hexdigest(),
                    category=entry.category.value,
                )
            )

        ordered = tuple(sorted(manifests, key=lambda item: item.path.casefold()))
        manifest_bytes = _canonical_jsonl(ordered)
        metadata_bytes = _canonical_json(
            {
                "archive_format": "phase8a-content-archive-v1",
                "content_categories": sorted(item.value for item in CONTENT_CATEGORIES),
                "content_file_count": len(ordered),
                "content_manifest_sha256": _sha256_bytes(manifest_bytes),
                "content_total_bytes": sum(item.size for item in ordered),
                "relative_paths_only": True,
                "skills_and_workflows_untrusted": True,
                "source_label": source_label,
            }
        )
        archive.writestr(_zip_info(CONTENT_MANIFEST_NAME), manifest_bytes)
        archive.writestr(_zip_info(ARCHIVE_METADATA_NAME), metadata_bytes)
    return ordered, manifest_bytes, metadata_bytes


def _parse_manifest(value: bytes) -> tuple[ContentManifestEntry, ...]:
    entries: list[ContentManifestEntry] = []
    for raw_line in value.splitlines():
        if not raw_line:
            continue
        try:
            entry = ContentManifestEntry(**json.loads(raw_line))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ArchiveBackupError("archive content manifest is invalid") from error
        _safe_relative(entry.path)
        if entry.category not in {item.value for item in CONTENT_CATEGORIES}:
            raise ArchiveBackupError("archive manifest contains a prohibited category")
        entries.append(entry)
    ordered = tuple(sorted(entries, key=lambda item: item.path.casefold()))
    if tuple(entries) != ordered or len({entry.path for entry in entries}) != len(
        entries
    ):
        raise ArchiveBackupError("archive content manifest is not canonical and unique")
    return ordered


def verify_content_archive(
    archive_path: Path,
    expected: tuple[ContentManifestEntry, ...] | None = None,
) -> tuple[tuple[ContentManifestEntry, ...], str]:
    """Fully read *archive_path* and verify its safe, manifest-bound contents."""

    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ArchiveBackupError("archive contains duplicate paths")
        for info in infos:
            _safe_relative(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ArchiveBackupError("archive contains a symbolic link")
            if info.flag_bits & 0x1:
                raise ArchiveBackupError("archive contains an encrypted member")

        if CONTENT_MANIFEST_NAME not in names or ARCHIVE_METADATA_NAME not in names:
            raise ArchiveBackupError("archive is missing its internal manifests")
        manifest_bytes = archive.read(CONTENT_MANIFEST_NAME)
        parsed = _parse_manifest(manifest_bytes)
        if expected is not None and parsed != expected:
            raise ArchiveBackupError("archive manifest differs from expected content")
        expected_names = {
            CONTENT_MANIFEST_NAME,
            ARCHIVE_METADATA_NAME,
            *(f"{CONTENT_PREFIX}{entry.path}" for entry in parsed),
        }
        if set(names) != expected_names:
            raise ArchiveBackupError("archive contains missing or additional members")

        metadata = json.loads(archive.read(ARCHIVE_METADATA_NAME))
        manifest_sha256 = _sha256_bytes(manifest_bytes)
        if metadata.get("content_manifest_sha256") != manifest_sha256:
            raise ArchiveBackupError("archive metadata does not bind the manifest")
        if metadata.get("content_file_count") != len(parsed):
            raise ArchiveBackupError("archive metadata contains a wrong file count")
        if metadata.get("content_total_bytes") != sum(item.size for item in parsed):
            raise ArchiveBackupError("archive metadata contains a wrong byte count")

        for entry in parsed:
            digest = hashlib.sha256()
            size = 0
            with archive.open(f"{CONTENT_PREFIX}{entry.path}", "r") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(block)
                    digest.update(block)
            if size != entry.size or digest.hexdigest() != entry.sha256:
                raise ArchiveBackupError(
                    f"archive member failed verification: {entry.path}"
                )
    return parsed, manifest_sha256


def _runtime_inventory(plan: BackupPlan, *, source_label: str) -> tuple[bytes, int]:
    entries = [
        {
            "category": entry.category.value,
            "entry_type": entry.entry_type,
            "exclusion_reason": entry.exclusion_reason,
            "path": entry.path,
            "size": entry.size,
        }
        for entry in plan.entries
        if entry.category in RUNTIME_INVENTORY_CATEGORIES
    ]
    payload = {
        "content_accessed": False,
        "entry_count": len(entries),
        "entries": entries,
        "prohibited_roots_recursive": False,
        "relative_paths_only": True,
        "source_label": source_label,
    }
    return _canonical_json(payload), len(entries)


def _hash_source_content(
    source: Path, expected: tuple[ContentManifestEntry, ...]
) -> None:
    for entry in expected:
        path = _ensure_no_reparse_ancestry(source, entry.path)
        before = _identity(path)
        if before[1] != entry.size or _hash_file(path) != entry.sha256:
            raise ArchiveBackupError(
                f"source content changed after archive: {entry.path}"
            )
        if _identity(path) != before:
            raise ArchiveBackupError(f"source changed during final hash: {entry.path}")


def _remove_tree(path: Path) -> None:
    def make_writable(function: Any, target: str, _error: Any) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onerror=make_writable)


def _restore_probe(
    archive_path: Path,
    expected: tuple[ContentManifestEntry, ...],
    staging_root: Path,
) -> bool:
    staging_root = staging_root.absolute()
    created_staging_root = False
    if staging_root.exists():
        if not staging_root.is_dir() or _is_reparse(staging_root):
            raise ArchiveBackupError("restore staging root is not a safe directory")
    else:
        staging_root.mkdir(parents=False)
        created_staging_root = True
    probe = staging_root / f"phase8a-restore-{uuid.uuid4().hex}"
    probe.mkdir()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            restored_paths: list[str] = []
            for entry in expected:
                relative = _safe_relative(entry.path)
                target = probe.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size = 0
                with archive.open(f"{CONTENT_PREFIX}{entry.path}", "r") as source:
                    with target.open("xb") as destination:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            size += len(block)
                            digest.update(block)
                            destination.write(block)
                if size != entry.size or digest.hexdigest() != entry.sha256:
                    raise ArchiveBackupError(
                        f"restore differs from manifest: {entry.path}"
                    )
                restored_paths.append(entry.path)

        actual_files = tuple(
            sorted(
                path.relative_to(probe).as_posix()
                for path in probe.rglob("*")
                if path.is_file()
            )
        )
        expected_paths = tuple(sorted(entry.path for entry in expected))
        if (
            actual_files != expected_paths
            or tuple(sorted(restored_paths)) != expected_paths
        ):
            raise ArchiveBackupError("restore contains missing or additional files")
        for path in probe.rglob("*"):
            if _is_reparse(path):
                raise ArchiveBackupError(
                    "restore unexpectedly contains a reparse point"
                )
        return True
    finally:
        _remove_tree(probe)
        if created_staging_root and staging_root.exists():
            try:
                staging_root.rmdir()
            except OSError:
                pass


def _write_temporary(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _validate_outputs(source: Path, outputs: tuple[Path, ...]) -> None:
    source = source.absolute()
    if not source.is_dir() or _is_reparse(source):
        raise ArchiveBackupError("source root must be an existing real directory")
    for output in outputs:
        output = output.absolute()
        if output.exists():
            raise ArchiveBackupError("final backup artifacts must not already exist")
        if output == source or source in output.parents or output in source.parents:
            raise ArchiveBackupError("source and output roots must be disjoint")
        output.parent.mkdir(parents=True, exist_ok=True)
        if _is_reparse(output.parent):
            raise ArchiveBackupError("output parent must not be a reparse point")


def create_atomic_archive_backup(
    source: Path,
    archive_path: Path,
    runtime_inventory_path: Path,
    proof_path: Path,
    *,
    staging_root: Path,
    source_label: str,
    approved_plan_sha256: str,
    expected_git_head: str | None = None,
) -> ArchiveBackupResult:
    """Create one atomic content archive plus a metadata-only runtime inventory."""

    source = source.absolute()
    archive_path = archive_path.absolute()
    runtime_inventory_path = runtime_inventory_path.absolute()
    proof_path = proof_path.absolute()
    staging_root = staging_root.absolute()
    finals = (archive_path, runtime_inventory_path, proof_path)
    _validate_outputs(source, finals)
    if (
        staging_root == source
        or source in staging_root.parents
        or staging_root in source.parents
    ):
        raise ArchiveBackupError("source and restore staging roots must be disjoint")
    if any(
        staging_root == output
        or staging_root in output.parents
        or output in staging_root.parents
        for output in finals
    ):
        raise ArchiveBackupError(
            "restore staging root must not contain final artifacts"
        )

    nonce = uuid.uuid4().hex
    temporary_archive = archive_path.with_name(f".{archive_path.name}.{nonce}.tmp")
    temporary_inventory = runtime_inventory_path.with_name(
        f".{runtime_inventory_path.name}.{nonce}.tmp"
    )
    temporary_proof = proof_path.with_name(f".{proof_path.name}.{nonce}.tmp")
    temporaries = (temporary_archive, temporary_inventory, temporary_proof)
    before_git = _git_state(source) if expected_git_head is not None else None
    try:
        if before_git is not None and before_git.head != expected_git_head:
            raise ArchiveBackupError("legacy HEAD does not match the approved commit")
        before_plan = create_backup_plan(
            source,
            archive_path,
            source_label=source_label,
            destination_label="phase-8a-atomic-content-archive",
        )
        _validate_plan(before_plan)
        before_plan_digest = _plan_digest(before_plan)

        manifests, manifest_bytes, _metadata_bytes = _write_content_archive(
            source,
            temporary_archive,
            before_plan,
            source_label=source_label,
        )
        verified, manifest_sha256 = verify_content_archive(temporary_archive, manifests)
        if verified != manifests or manifest_sha256 != _sha256_bytes(manifest_bytes):
            raise ArchiveBackupError("full archive verification did not converge")

        after_plan = create_backup_plan(
            source,
            archive_path,
            source_label=source_label,
            destination_label="phase-8a-atomic-content-archive",
        )
        _validate_plan(after_plan)
        if before_plan.entries != after_plan.entries:
            raise ArchiveBackupError("source metadata changed during archive creation")
        if before_plan_digest != _plan_digest(after_plan):
            raise ArchiveBackupError("source plan changed during archive creation")
        _hash_source_content(source, manifests)

        after_git = _git_state(source) if before_git is not None else None
        if before_git is not None and after_git != before_git:
            raise ArchiveBackupError("legacy Git state changed during archive creation")

        runtime_bytes, runtime_count = _runtime_inventory(
            after_plan, source_label=source_label
        )
        _write_temporary(temporary_inventory, runtime_bytes)
        os.replace(temporary_archive, archive_path)
        restore_verified = _restore_probe(archive_path, manifests, staging_root)
        restore_probe_removed = (
            not any(staging_root.glob("phase8a-restore-*"))
            if staging_root.exists()
            else True
        )
        if not restore_verified or not restore_probe_removed:
            raise ArchiveBackupError("restore probe was not verified and removed")

        archive_sha256 = _hash_file(archive_path)
        proof_payload = {
            "approved_plan_sha256": approved_plan_sha256,
            "archive_format": "phase8a-content-archive-v1",
            "archive_sha256": archive_sha256,
            "archive_verified": True,
            "content_file_count": len(manifests),
            "content_manifest_sha256": manifest_sha256,
            "content_total_bytes": sum(item.size for item in manifests),
            "git_head_after": after_git.head if after_git is not None else None,
            "git_head_before": before_git.head if before_git is not None else None,
            "git_status_count": len(before_git.status)
            if before_git is not None
            else None,
            "git_status_sha256": (
                _git_status_digest(before_git) if before_git is not None else None
            ),
            "plan_sha256": before_plan_digest,
            "prohibited_roots_recursive": False,
            "relative_paths_only": True,
            "restore_probe_removed": True,
            "restore_verified": True,
            "runtime_inventory_entry_count": runtime_count,
            "skills_and_workflows_untrusted": True,
            "source_label": source_label,
            "source_stable": True,
        }
        _write_temporary(temporary_proof, _canonical_json(proof_payload))
        os.replace(temporary_inventory, runtime_inventory_path)
        os.replace(temporary_proof, proof_path)
        return ArchiveBackupResult(
            archive=archive_path,
            runtime_inventory=runtime_inventory_path,
            proof=proof_path,
            archive_sha256=archive_sha256,
            content_manifest_sha256=manifest_sha256,
            content_file_count=len(manifests),
            content_total_bytes=sum(item.size for item in manifests),
            runtime_inventory_entry_count=runtime_count,
            source_stable=True,
            git_head=after_git.head if after_git is not None else None,
            git_status_count=len(after_git.status) if after_git is not None else None,
            restore_verified=True,
            restore_probe_removed=True,
        )
    except Exception:
        for path in (*temporaries, *finals):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--runtime-inventory", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--approved-plan-sha256", required=True)
    parser.add_argument("--expected-git-head")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = create_atomic_archive_backup(
        args.source,
        args.archive,
        args.runtime_inventory,
        args.proof,
        staging_root=args.staging_root,
        source_label=args.source_label,
        approved_plan_sha256=args.approved_plan_sha256,
        expected_git_head=args.expected_git_head,
    )
    print(
        json.dumps(
            {
                **asdict(result),
                "archive": os.fspath(result.archive),
                "proof": os.fspath(result.proof),
                "runtime_inventory": os.fspath(result.runtime_inventory),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
