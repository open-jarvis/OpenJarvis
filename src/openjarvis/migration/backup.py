"""Verified, read-only source backups for controlled migrations.

The source tree is scanned before and after copying. Reparse points are never
followed. Technical artifacts and credential/session material are excluded by
name without opening their contents. The retained backup is verified through
an ephemeral restore probe that is removed before returning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable


class BackupError(RuntimeError):
    """Raised when a backup cannot be proven stable and restorable."""


class BackupKind(StrEnum):
    LEGACY_PROJECT = "legacy_project"
    VAULT = "vault"


TECHNICAL_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "target",
    }
)

SENSITIVE_DIRECTORY_NAMES = frozenset(
    {
        ".credentials",
        ".secrets",
        "auth-data",
        "auth_data",
        "browser-profile",
        "browser-profiles",
        "browser_profile",
        "browser_profiles",
        "cookie-data",
        "cookie_data",
        "cookies",
        "credentials",
        "playwright-profile",
        "playwright_profile",
        "session-data",
        "session-state",
        "session_data",
        "session_state",
        "sessions",
        "token-data",
        "token_data",
        "tokens",
        "user data",
    }
)

SENSITIVE_FILE_NAMES = frozenset(
    {
        ".env",
        "cookies",
        "cookies.sqlite",
        "credentials.json",
        "login data",
        "local state",
        "secrets.json",
        "token.json",
        "web data",
    }
)


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    path: str
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ExclusionEntry:
    path: str
    kind: str
    reason: str
    size: int | None = None


@dataclass(frozen=True, slots=True)
class ScanResult:
    files: tuple[ManifestEntry, ...]
    directories: tuple[tuple[str, int], ...]
    exclusions: tuple[ExclusionEntry, ...]


@dataclass(frozen=True, slots=True)
class BackupResult:
    destination: Path
    file_count: int
    total_bytes: int
    excluded_count: int
    manifest_sha256: str
    restore_verified: bool
    source_stable: bool


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_reparse(path: Path) -> bool:
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _is_sensitive_file(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered in SENSITIVE_FILE_NAMES
        or lowered.startswith(".env.")
        or lowered.endswith((".cookie", ".cookies", ".session"))
        or lowered.startswith(("credential.", "credentials.", "secret.", "token."))
    )


def _excluded_directory(relative: Path) -> str | None:
    name = relative.name.casefold()
    if name in TECHNICAL_DIRECTORIES:
        return "technical_or_build_artifact"
    if name in SENSITIVE_DIRECTORY_NAMES:
        return "credential_session_or_browser_runtime"
    return None


def _hash_stable(path: Path) -> tuple[int, int, str]:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat(follow_symlinks=False)
    identity_before = (before.st_size, before.st_mtime_ns, before.st_ino)
    identity_after = (after.st_size, after.st_mtime_ns, after.st_ino)
    if identity_before != identity_after:
        raise BackupError(f"source changed while hashing: {path.name}")
    return before.st_size, before.st_mtime_ns, digest.hexdigest()


def _scan(root: Path, kind: BackupKind, *, apply_policy: bool) -> ScanResult:
    files: list[ManifestEntry] = []
    directories: list[tuple[str, int]] = []
    exclusions: list[ExclusionEntry] = []
    pending = [root]

    while pending:
        current = pending.pop()
        with os.scandir(current) as iterator:
            children = sorted(iterator, key=lambda item: item.name.casefold())
        for child in children:
            path = Path(child.path)
            relative = path.relative_to(root)
            relative_text = relative.as_posix()
            try:
                if _is_reparse(path):
                    exclusions.append(
                        ExclusionEntry(
                            path=relative_text,
                            kind="reparse_point",
                            reason="symlink_or_junction_not_followed",
                        )
                    )
                    continue
                if child.is_dir(follow_symlinks=False):
                    reason = _excluded_directory(relative) if apply_policy else None
                    if reason is not None:
                        exclusions.append(
                            ExclusionEntry(
                                path=relative_text,
                                kind="directory",
                                reason=reason,
                            )
                        )
                        continue
                    directories.append((relative_text, path.stat().st_mtime_ns))
                    pending.append(path)
                    continue
                if not child.is_file(follow_symlinks=False):
                    exclusions.append(
                        ExclusionEntry(
                            path=relative_text,
                            kind="special_file",
                            reason="unsupported_file_type",
                        )
                    )
                    continue
                if apply_policy and _is_sensitive_file(child.name):
                    # Do not hash or copy credentials, cookies, tokens, or sessions.
                    exclusions.append(
                        ExclusionEntry(
                            path=relative_text,
                            kind="sensitive_file",
                            reason="content_access_and_copy_prohibited",
                            size=path.stat(follow_symlinks=False).st_size,
                        )
                    )
                    continue
                size, mtime_ns, digest = _hash_stable(path)
                files.append(
                    ManifestEntry(
                        path=relative_text,
                        size=size,
                        mtime_ns=mtime_ns,
                        sha256=digest,
                    )
                )
            except OSError as error:
                raise BackupError(
                    f"cannot safely scan {relative_text}: {error}"
                ) from error

    return ScanResult(
        files=tuple(sorted(files, key=lambda item: item.path.casefold())),
        directories=tuple(sorted(directories, key=lambda item: item[0].casefold())),
        exclusions=tuple(sorted(exclusions, key=lambda item: item.path.casefold())),
    )


def _manifest_digest(entries: Iterable[ManifestEntry]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(
            json.dumps(asdict(entry), sort_keys=True, separators=(",", ":")).encode()
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: Iterable[Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
            stream.write(json.dumps(payload, sort_keys=True, ensure_ascii=False))
            stream.write("\n")


def load_manifest(path: Path) -> tuple[ManifestEntry, ...]:
    entries: list[ManifestEntry] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                entries.append(ManifestEntry(**json.loads(line)))
    return tuple(entries)


def verify_manifest(root: Path, expected: tuple[ManifestEntry, ...]) -> bool:
    actual = _scan(root, BackupKind.VAULT, apply_policy=False).files
    return actual == expected


def _copy_files(source: Path, data_root: Path, scan: ScanResult) -> None:
    for directory, _mtime_ns in scan.directories:
        (data_root / Path(directory)).mkdir(parents=True, exist_ok=True)
    for entry in scan.files:
        source_file = source / Path(entry.path)
        target_file = data_root / Path(entry.path)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
    for directory, mtime_ns in sorted(
        scan.directories,
        key=lambda item: len(Path(item[0]).parts),
        reverse=True,
    ):
        os.utime(data_root / Path(directory), ns=(mtime_ns, mtime_ns))


def _remove_tree(path: Path) -> None:
    def make_writable(function: Any, target: str, _error: Any) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    shutil.rmtree(path, onerror=make_writable)


def create_verified_backup(
    source: Path,
    destination: Path,
    *,
    kind: BackupKind,
    source_label: str,
) -> BackupResult:
    """Create and restore-probe a stable backup without mutating *source*."""

    source = source.absolute()
    destination = destination.absolute()
    if not source.is_dir():
        raise BackupError("source must be an existing directory")
    if _is_reparse(source):
        raise BackupError("source root must not be a symlink or junction")
    if destination.exists():
        raise BackupError("destination must not already exist")
    if (
        destination == source
        or source in destination.parents
        or destination in source.parents
    ):
        raise BackupError("source and destination roots must be disjoint")

    destination.mkdir(parents=True)
    data_root = destination / "data"
    manifests_root = destination / "manifests"
    data_root.mkdir()
    manifests_root.mkdir()
    started_at = _utc_now()

    try:
        before = _scan(source, kind, apply_policy=True)
        _copy_files(source, data_root, before)
        backup_scan = _scan(data_root, kind, apply_policy=False)
        if backup_scan.files != before.files:
            raise BackupError("backup differs from the source manifest")

        after = _scan(source, kind, apply_policy=True)
        if after.files != before.files or after.exclusions != before.exclusions:
            raise BackupError("source changed during backup")

        restore_root = Path(
            tempfile.mkdtemp(prefix="phase8a-restore-", dir=destination.parent)
        )
        try:
            restore_data = restore_root / "data"
            shutil.copytree(data_root, restore_data, copy_function=shutil.copy2)
            restored = _scan(restore_data, kind, apply_policy=False)
            if restored.files != before.files:
                raise BackupError("restore probe differs from the source manifest")
        finally:
            _remove_tree(restore_root)

        _write_jsonl(manifests_root / "source-before.jsonl", before.files)
        _write_jsonl(manifests_root / "source-after.jsonl", after.files)
        _write_jsonl(manifests_root / "backup.jsonl", backup_scan.files)
        _write_jsonl(manifests_root / "restore.jsonl", restored.files)
        _write_jsonl(manifests_root / "exclusions.jsonl", before.exclusions)
        _write_jsonl(manifests_root / "errors.jsonl", [])
        manifest_sha256 = _manifest_digest(before.files)
        summary = {
            "backup_kind": kind.value,
            "completed_at": _utc_now(),
            "excluded_count": len(before.exclusions),
            "file_count": len(before.files),
            "manifest_sha256": manifest_sha256,
            "relative_paths_only": True,
            "restore_probe_removed": not restore_root.exists(),
            "restore_verified": True,
            "source_label": source_label,
            "source_stable": True,
            "started_at": started_at,
            "total_bytes": sum(entry.size for entry in before.files),
        }
        _write_json(manifests_root / "summary.json", summary)
        return BackupResult(
            destination=destination,
            file_count=summary["file_count"],
            total_bytes=summary["total_bytes"],
            excluded_count=summary["excluded_count"],
            manifest_sha256=manifest_sha256,
            restore_verified=True,
            source_stable=True,
        )
    except Exception as error:
        _write_jsonl(
            manifests_root / "errors.jsonl",
            [{"error_type": type(error).__name__, "message": str(error)}],
        )
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--kind", choices=[item.value for item in BackupKind], required=True
    )
    parser.add_argument("--source-label", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = create_verified_backup(
        args.source,
        args.destination,
        kind=BackupKind(args.kind),
        source_label=args.source_label,
    )
    print(json.dumps({**asdict(result), "destination": str(result.destination)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
