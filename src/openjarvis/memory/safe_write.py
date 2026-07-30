"""Root-bound, conflict-safe atomic Markdown writes."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

_MAX_DIFF_CHARS = 40_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class UnsafeMemoryPath(ValueError):
    """Raised when a candidate path could escape or traverse a reparse point."""


class ConcurrentMemoryWrite(RuntimeError):
    """Raised when the file changed after the candidate was prepared."""


@dataclass(frozen=True, slots=True)
class AtomicWriteResult:
    operation_id: str
    path: str
    before_hash: str | None
    after_hash: str
    diff: str
    restore_path: str
    created_at: str
    completed_at: str
    created_file: bool


def is_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink or Windows junction/reparse point."""

    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)


def safe_target(vault_root: Path, relative_path: str) -> Path:
    """Resolve a relative target while enforcing the configured vault root."""

    root = vault_root.expanduser().resolve(strict=True)
    if not root.is_dir() or is_reparse_point(root):
        raise UnsafeMemoryPath("vault root is unavailable or is a reparse point")
    text = (relative_path or "").strip()
    windows = PureWindowsPath(text)
    candidate = Path(text)
    if (
        not text
        or candidate.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
    ):
        raise UnsafeMemoryPath("memory path must be relative to the vault root")
    if any(part in {"", ".", ".."} for part in windows.parts):
        raise UnsafeMemoryPath("memory path cannot contain empty, dot, or parent parts")
    if candidate.suffix.casefold() not in {".md", ".markdown"}:
        raise UnsafeMemoryPath("memory writes are limited to Markdown files")

    target = root.joinpath(*windows.parts)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise UnsafeMemoryPath("memory path escapes the configured vault root") from exc

    current = root
    for part in windows.parts:
        current = current / part
        if current.exists() and is_reparse_point(current):
            raise UnsafeMemoryPath(
                "memory path crosses a symlink or Windows junction"
            )
    return resolved


def unified_diff(
    before: str,
    after: str,
    *,
    relative_path: str,
) -> str:
    """Return a bounded, reviewable unified diff."""

    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{relative_path}",
        tofile=f"b/{relative_path}",
    )
    result = "".join(lines)
    if len(result) > _MAX_DIFF_CHARS:
        return result[:_MAX_DIFF_CHARS].rstrip() + "\n... diff truncated ...\n"
    return result


class AtomicMarkdownWriter:
    """Apply one already-approved write and retain an external restore artifact."""

    def __init__(self, vault_root: str | Path, restore_root: str | Path) -> None:
        self.vault_root = Path(vault_root).expanduser().resolve(strict=True)
        self.restore_root = Path(restore_root).expanduser().resolve(strict=False)
        try:
            self.restore_root.relative_to(self.vault_root)
        except ValueError:
            pass
        else:
            raise ValueError("restore_root must be outside the vault")

    def inspect(self, relative_path: str) -> tuple[Path, bytes | None, str | None]:
        target = safe_target(self.vault_root, relative_path)
        before = target.read_bytes() if target.exists() else None
        return target, before, sha256_bytes(before) if before is not None else None

    def write(
        self,
        relative_path: str,
        content: str,
        *,
        expected_hash: str | None,
        operation_id: str | None = None,
    ) -> AtomicWriteResult:
        """Compare-and-swap one Markdown file using same-filesystem replace."""

        started_at = _now()
        actual_operation_id = operation_id or uuid.uuid4().hex
        target, before, current_hash = self.inspect(relative_path)
        if expected_hash is None and before is not None:
            raise ConcurrentMemoryWrite(
                "target was created after the candidate was prepared"
            )
        if expected_hash is not None and current_hash != expected_hash:
            raise ConcurrentMemoryWrite(
                "target changed after the candidate was prepared"
            )

        payload = content.encode("utf-8")
        after_hash = sha256_bytes(payload)
        before_text = before.decode("utf-8") if before is not None else ""
        diff = unified_diff(before_text, content, relative_path=relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._validate_created_parents(target)
        self.restore_root.mkdir(parents=True, exist_ok=True)
        restore_path = self.restore_root / f"{actual_operation_id}.restore"
        self._write_restore(
            restore_path,
            relative_path=relative_path,
            before=before,
            before_hash=current_hash,
            after_hash=after_hash,
        )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, target)
            temporary_path = None
            actual_after = target.read_bytes()
            if sha256_bytes(actual_after) != after_hash:
                raise OSError("post-write hash verification failed")
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

        return AtomicWriteResult(
            operation_id=actual_operation_id,
            path=relative_path,
            before_hash=current_hash,
            after_hash=after_hash,
            diff=diff,
            restore_path=str(restore_path),
            created_at=started_at,
            completed_at=_now(),
            created_file=before is None,
        )

    def restore(
        self,
        result: AtomicWriteResult,
        *,
        expected_after_hash: str | None = None,
    ) -> str | None:
        """Restore the prior bytes only if the applied file is still unchanged."""

        target, current, current_hash = self.inspect(result.path)
        expected = expected_after_hash or result.after_hash
        if current is None or current_hash != expected:
            raise ConcurrentMemoryWrite("target changed after the approved write")
        restore_path = Path(result.restore_path)
        manifest, before = self._read_restore(restore_path)
        if manifest["after_hash"] != result.after_hash:
            raise ConcurrentMemoryWrite("restore artifact does not match the write")
        if manifest["created_file"]:
            target.unlink()
            return None
        if before is None:
            raise OSError("restore artifact is missing prior file bytes")
        self._replace_bytes(target, before)
        restored_hash = sha256_bytes(target.read_bytes())
        if restored_hash != manifest["before_hash"]:
            raise OSError("restore hash verification failed")
        return restored_hash

    def _validate_created_parents(self, target: Path) -> None:
        current = target.parent
        while current != self.vault_root:
            if is_reparse_point(current):
                raise UnsafeMemoryPath(
                    "created path crosses a symlink or Windows junction"
                )
            current = current.parent

    @staticmethod
    def _replace_bytes(target: Path, payload: bytes) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.restore.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _write_restore(
        path: Path,
        *,
        relative_path: str,
        before: bytes | None,
        before_hash: str | None,
        after_hash: str,
    ) -> None:
        manifest = {
            "schema_version": 1,
            "relative_path": relative_path,
            "created_file": before is None,
            "before_hash": before_hash,
            "after_hash": after_hash,
        }
        header = json.dumps(manifest, sort_keys=True).encode("utf-8") + b"\n"
        with path.open("xb") as handle:
            handle.write(header)
            if before is not None:
                handle.write(before)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _read_restore(path: Path) -> tuple[dict[str, object], bytes | None]:
        payload = path.read_bytes()
        header, separator, body = payload.partition(b"\n")
        if not separator:
            raise OSError("invalid restore artifact")
        manifest = json.loads(header.decode("utf-8"))
        before = body if not manifest["created_file"] else None
        return manifest, before


__all__ = [
    "AtomicMarkdownWriter",
    "AtomicWriteResult",
    "ConcurrentMemoryWrite",
    "UnsafeMemoryPath",
    "is_reparse_point",
    "safe_target",
    "sha256_bytes",
    "unified_diff",
]
