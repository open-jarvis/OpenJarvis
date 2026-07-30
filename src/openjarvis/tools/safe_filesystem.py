"""Root-confined, restore-capable filesystem tools for Phase 5."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.security.file_policy import is_sensitive_file
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.apply_patch import _apply_hunks, _parse_patch
from openjarvis.tools.manifest import ToolManifest, manifest_from_spec

_READ_LIMIT = 1_048_576
_WRITE_LIMIT = 10_485_760
_SEARCH_LIMIT = 500
_REPARSE_ATTRIBUTE = 0x400
_BLOCKED_COMPONENTS = frozenset(
    {
        ".aws",
        ".azure",
        ".config/gcloud",
        ".gnupg",
        ".kube",
        ".ssh",
        "credential manager",
        "credentials",
        "user data",
    }
)


class FilesystemPolicyError(PermissionError):
    """Raised before a path outside the safe filesystem contract is opened."""


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_encoding(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "cp1252"
    return "utf-8"


def _normalised(path: Path) -> str:
    # Windows paths are case-insensitive.  ``casefold`` keeps synthetic tests
    # deterministic even when they run on a non-Windows CI host.
    return os.path.normpath(os.path.abspath(str(path))).casefold()


def _is_under(path: Path, root: Path) -> bool:
    candidate = _normalised(path)
    boundary = _normalised(root)
    try:
        return os.path.commonpath([candidate, boundary]) == boundary
    except ValueError:
        return False


def _has_ads(raw: str) -> bool:
    value = raw.replace("/", "\\")
    if re.match(r"^[a-zA-Z]:\\", value):
        value = value[3:]
    return any(":" in component for component in value.split("\\"))


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = int(getattr(info, "st_file_attributes", 0))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & _REPARSE_ATTRIBUTE)


class SecurePathPolicy:
    """Canonical path, root, secret, and reparse-point enforcement."""

    def __init__(self, roots: tuple[str | Path, ...], restore_root: str | Path) -> None:
        if not roots:
            raise ValueError("at least one filesystem root is required")
        self.roots = tuple(
            Path(root).expanduser().resolve(strict=True) for root in roots
        )
        if any(not root.is_dir() for root in self.roots):
            raise ValueError("every filesystem root must be a directory")
        self.restore_root = Path(restore_root).expanduser().resolve(strict=False)
        self.restore_root.mkdir(parents=True, exist_ok=True)
        if any(_is_under(self.restore_root, root) for root in self.roots):
            raise ValueError("restore_root must be outside writable roots")

    def resolve(
        self,
        raw_path: str,
        *,
        must_exist: bool = False,
        allow_directory: bool = True,
    ) -> Path:
        if not raw_path or "\x00" in raw_path:
            raise FilesystemPolicyError("path is empty or contains NUL")
        if _has_ads(raw_path):
            raise FilesystemPolicyError("alternate data streams are blocked")
        supplied = Path(raw_path)
        if ".." in supplied.parts:
            raise FilesystemPolicyError("parent traversal is blocked")
        lexical = supplied if supplied.is_absolute() else self.roots[0] / supplied
        lexical = Path(os.path.abspath(str(lexical)))
        matching_root = next(
            (root for root in self.roots if _is_under(lexical, root)),
            None,
        )
        if matching_root is None:
            raise FilesystemPolicyError("path is outside allowed roots")

        try:
            relative = lexical.relative_to(matching_root)
        except ValueError as exc:
            raise FilesystemPolicyError("path is outside allowed roots") from exc
        cursor = matching_root
        for component in relative.parts:
            cursor = cursor / component
            if cursor.exists() or cursor.is_symlink():
                if _is_reparse(cursor):
                    raise FilesystemPolicyError(
                        f"symlink, junction, or reparse point blocked: {cursor}"
                    )

        resolved = lexical.resolve(strict=False)
        if not _is_under(resolved, matching_root):
            raise FilesystemPolicyError("resolved path escaped allowed root")
        self._check_sensitive_and_system(resolved)
        if must_exist and not resolved.exists():
            raise FileNotFoundError(str(resolved))
        if not allow_directory and resolved.exists() and not resolved.is_file():
            raise FilesystemPolicyError("path must be a regular file")
        return resolved

    def _check_sensitive_and_system(self, path: Path) -> None:
        lowered = {part.casefold() for part in path.parts}
        if lowered & _BLOCKED_COMPONENTS or is_sensitive_file(path):
            raise FilesystemPolicyError("credential or browser-profile path blocked")
        blocked_roots = tuple(
            Path(value).resolve(strict=False)
            for value in (
                os.environ.get("SystemRoot", ""),
                os.environ.get("ProgramFiles", ""),
                os.environ.get("ProgramFiles(x86)", ""),
            )
            if value
        )
        if any(_is_under(path, blocked) for blocked in blocked_roots):
            raise FilesystemPolicyError("system path blocked")

    def prepare_restore(self, target: Path) -> Path:
        artifact_dir = self.restore_root / f"restore-{uuid.uuid4().hex}"
        artifact_dir.mkdir(parents=False, exist_ok=False)
        existed = target.exists()
        before_name = "before.bin" if existed and target.is_file() else "before"
        before_path = artifact_dir / before_name
        if existed:
            if target.is_dir():
                shutil.copytree(target, before_path)
            else:
                shutil.copy2(target, before_path)
        record = {
            "target": str(target),
            "existed": existed,
            "was_directory": existed and target.is_dir(),
            "before": before_name if existed else None,
        }
        (artifact_dir / "restore.json").write_text(
            json.dumps(record, indent=2),
            encoding="utf-8",
        )
        return artifact_dir / "restore.json"

    def restore(self, artifact: str | Path) -> Path:
        record_path = Path(artifact).resolve(strict=True)
        if not _is_under(record_path, self.restore_root):
            raise FilesystemPolicyError("restore artifact escaped restore root")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        target = self.resolve(str(record["target"]))
        existed = bool(record["existed"])
        if existed:
            source = record_path.parent / str(record["before"])
            if bool(record["was_directory"]):
                if target.exists():
                    raise FilesystemPolicyError(
                        "directory restore requires an absent target"
                    )
                shutil.copytree(source, target)
            else:
                _atomic_copy(source, target)
        elif target.exists():
            if target.is_dir():
                target.rmdir()
            else:
                target.unlink()
        return target


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=False, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".openjarvis-", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _atomic_copy(source: Path, target: Path) -> None:
    if source.stat().st_size > _WRITE_LIMIT:
        raise ValueError("source exceeds write limit")
    _atomic_write(target, source.read_bytes())


def _text_diff(before: bytes, after: bytes, path: Path) -> str:
    before_encoding = _detect_encoding(before)
    after_encoding = _detect_encoding(after)
    try:
        before_text = before.decode(before_encoding)
        after_text = after.decode(after_encoding)
    except UnicodeDecodeError:
        return "binary content changed"
    return "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=f"before/{path.name}",
            tofile=f"after/{path.name}",
        )
    )[:100_000]


class _FilesystemTool(BaseTool):
    def __init__(self, policy: SecurePathPolicy) -> None:
        self.policy = policy

    @property
    def manifest(self) -> ToolManifest:
        return manifest_from_spec(self.tool_id, self.spec).model_copy(
            update={"allowed_roots": tuple(str(root) for root in self.policy.roots)}
        )

    def _error(self, exc: Exception) -> ToolResult:
        return ToolResult(tool_name=self.tool_id, content=str(exc), success=False)


@ToolRegistry.register("file.read")
class SafeFileReadTool(_FilesystemTool):
    tool_id = "file.read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read one bounded file inside an explicitly allowed root.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "max_bytes": {"type": "integer"},
                },
                "required": ["path"],
            },
            category="filesystem",
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = self.policy.resolve(
                params["path"], must_exist=True, allow_directory=False
            )
            limit = min(max(int(params.get("max_bytes", _READ_LIMIT)), 1), _READ_LIMIT)
            size = path.stat().st_size
            if size > limit:
                raise ValueError(f"file exceeds read limit ({size} > {limit})")
            data = path.read_bytes()
            encoding = _detect_encoding(data)
            return ToolResult(
                tool_name=self.tool_id,
                content=data.decode(encoding, errors="replace"),
                metadata={
                    "path": str(path),
                    "size_bytes": size,
                    "encoding": encoding,
                    "sha256": hashlib.sha256(data).hexdigest(),
                },
            )
        except (OSError, ValueError, FilesystemPolicyError) as exc:
            return self._error(exc)


@ToolRegistry.register("file.list")
class SafeFileListTool(_FilesystemTool):
    tool_id = "file.list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List bounded entries inside an explicitly allowed root.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "recursive": {"type": "boolean"},
                    "max_entries": {"type": "integer"},
                },
                "required": ["path"],
            },
            category="filesystem",
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root = self.policy.resolve(params["path"], must_exist=True)
            if not root.is_dir():
                raise ValueError("list target must be a directory")
            limit = min(max(int(params.get("max_entries", 200)), 1), _SEARCH_LIMIT)
            iterator = (
                root.rglob("*") if params.get("recursive", False) else root.iterdir()
            )
            entries = []
            for child in iterator:
                self.policy.resolve(str(child), must_exist=True)
                entries.append(str(child.relative_to(root)))
                if len(entries) >= limit:
                    break
            return ToolResult(
                tool_name=self.tool_id,
                content="\n".join(entries),
                metadata={"count": len(entries), "root": str(root)},
            )
        except (OSError, ValueError, FilesystemPolicyError) as exc:
            return self._error(exc)


@ToolRegistry.register("file.stat")
class SafeFileStatTool(_FilesystemTool):
    tool_id = "file.stat"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Return metadata and an optional hash for one safe path.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
            },
            category="filesystem",
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = self.policy.resolve(params["path"], must_exist=True)
            info = path.stat()
            metadata = {
                "path": str(path),
                "is_file": path.is_file(),
                "is_directory": path.is_dir(),
                "size_bytes": info.st_size,
                "mtime_ns": info.st_mtime_ns,
            }
            if path.is_file() and info.st_size <= _READ_LIMIT:
                metadata["sha256"] = _hash_file(path)
            return ToolResult(
                tool_name=self.tool_id,
                content=json.dumps(metadata, sort_keys=True),
                metadata=metadata,
            )
        except (OSError, ValueError, FilesystemPolicyError) as exc:
            return self._error(exc)


@ToolRegistry.register("file.search")
class SafeFileSearchTool(_FilesystemTool):
    tool_id = "file.search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Search bounded text files below an allowed root.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "query": {"type": "string", "minLength": 1, "maxLength": 256},
                    "glob": {"type": "string", "maxLength": 128},
                    "max_results": {"type": "integer"},
                },
                "required": ["path", "query"],
            },
            category="filesystem",
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root = self.policy.resolve(params["path"], must_exist=True)
            if not root.is_dir():
                raise ValueError("search target must be a directory")
            limit = min(max(int(params.get("max_results", 50)), 1), _SEARCH_LIMIT)
            query = params["query"].casefold()
            matches = []
            for path in root.rglob(params.get("glob", "*")):
                if not path.is_file():
                    continue
                self.policy.resolve(str(path), must_exist=True, allow_directory=False)
                if path.stat().st_size > _READ_LIMIT:
                    continue
                data = path.read_bytes()
                text = data.decode(_detect_encoding(data), errors="replace")
                for number, line in enumerate(text.splitlines(), 1):
                    if query in line.casefold():
                        matches.append(
                            f"{path.relative_to(root)}:{number}:{line[:500]}"
                        )
                        if len(matches) >= limit:
                            break
                if len(matches) >= limit:
                    break
            return ToolResult(
                tool_name=self.tool_id,
                content="\n".join(matches),
                metadata={"count": len(matches), "root": str(root)},
            )
        except (OSError, ValueError, FilesystemPolicyError) as exc:
            return self._error(exc)


class _MutationTool(_FilesystemTool):
    def _mutation_result(
        self,
        *,
        path: Path,
        before: bytes,
        restore_path: Path,
        content: str,
    ) -> ToolResult:
        after = path.read_bytes() if path.is_file() else b""
        return ToolResult(
            tool_name=self.tool_id,
            content=content,
            metadata={
                "path": str(path),
                "before_sha256": hashlib.sha256(before).hexdigest() if before else None,
                "after_sha256": hashlib.sha256(after).hexdigest() if after else None,
                "diff": _text_diff(before, after, path),
                "restore_path": str(restore_path),
                "verified": path.exists(),
            },
        )


@ToolRegistry.register("file.write")
class SafeFileWriteTool(_MutationTool):
    tool_id = "file.write"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Atomically write a bounded UTF-8 file with restore evidence.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            category="filesystem",
            required_capabilities=["file:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = self.policy.resolve(params["path"], allow_directory=False)
            data = params["content"].encode("utf-8")
            if len(data) > _WRITE_LIMIT:
                raise ValueError("content exceeds write limit")
            if not path.parent.exists():
                raise FileNotFoundError(str(path.parent))
            before = path.read_bytes() if path.exists() else b""
            restore = self.policy.prepare_restore(path)
            _atomic_write(path, data)
            if path.read_bytes() != data:
                raise OSError("after-write verification failed")
            return self._mutation_result(
                path=path,
                before=before,
                restore_path=restore,
                content=f"Atomically wrote {len(data)} bytes.",
            )
        except (OSError, ValueError, FilesystemPolicyError) as exc:
            return self._error(exc)


@ToolRegistry.register("file.patch")
class SafeFilePatchTool(_MutationTool):
    tool_id = "file.patch"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Apply a verified unified patch atomically inside an allowed root."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "patch": {"type": "string", "minLength": 1},
                },
                "required": ["path", "patch"],
            },
            category="filesystem",
            required_capabilities=["file:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = self.policy.resolve(
                params["path"], must_exist=True, allow_directory=False
            )
            before = path.read_bytes()
            encoding = _detect_encoding(before)
            original = before.decode(encoding)
            _, hunks = _parse_patch(params["patch"])
            patched = _apply_hunks(original, hunks).encode(encoding)
            if len(patched) > _WRITE_LIMIT:
                raise ValueError("patched file exceeds write limit")
            restore = self.policy.prepare_restore(path)
            _atomic_write(path, patched)
            if path.read_bytes() != patched:
                raise OSError("after-patch verification failed")
            return self._mutation_result(
                path=path,
                before=before,
                restore_path=restore,
                content=f"Applied {len(hunks)} verified patch hunk(s).",
            )
        except (OSError, UnicodeError, ValueError, FilesystemPolicyError) as exc:
            return self._error(exc)


class _TwoPathMutation(_MutationTool):
    def _paths(self, params: dict[str, Any]) -> tuple[Path, Path]:
        source = self.policy.resolve(
            params["source"], must_exist=True, allow_directory=False
        )
        target = self.policy.resolve(params["target"], allow_directory=False)
        if source == target:
            raise ValueError("source and target must differ")
        if not target.parent.exists():
            raise FileNotFoundError(str(target.parent))
        return source, target

    def _two_path_spec(self, description: str) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "minLength": 1},
                    "target": {"type": "string", "minLength": 1},
                },
                "required": ["source", "target"],
            },
            category="filesystem",
            required_capabilities=["file:write"],
        )


@ToolRegistry.register("file.copy")
class SafeFileCopyTool(_TwoPathMutation):
    tool_id = "file.copy"

    @property
    def spec(self) -> ToolSpec:
        return self._two_path_spec(
            "Atomically copy one bounded file with restore evidence."
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            source, target = self._paths(params)
            before = target.read_bytes() if target.exists() else b""
            restore = self.policy.prepare_restore(target)
            _atomic_copy(source, target)
            if _hash_file(source) != _hash_file(target):
                raise OSError("copy verification failed")
            return self._mutation_result(
                path=target,
                before=before,
                restore_path=restore,
                content="Copied and hash-verified file.",
            )
        except (OSError, ValueError, FilesystemPolicyError) as exc:
            return self._error(exc)


@ToolRegistry.register("file.move")
class SafeFileMoveTool(_TwoPathMutation):
    tool_id = "file.move"

    @property
    def spec(self) -> ToolSpec:
        return self._two_path_spec(
            "Move one file with source and target restore evidence."
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            source, target = self._paths(params)
            if target.exists():
                raise FileExistsError(str(target))
            source_hash = _hash_file(source)
            source_restore = self.policy.prepare_restore(source)
            target_restore = self.policy.prepare_restore(target)
            os.replace(source, target)
            if source.exists() or _hash_file(target) != source_hash:
                raise OSError("move verification failed")
            return ToolResult(
                tool_name=self.tool_id,
                content="Moved and hash-verified file.",
                metadata={
                    "source": str(source),
                    "target": str(target),
                    "after_sha256": source_hash,
                    "source_restore_path": str(source_restore),
                    "target_restore_path": str(target_restore),
                    "verified": True,
                },
            )
        except (OSError, ValueError, FilesystemPolicyError) as exc:
            return self._error(exc)


@ToolRegistry.register("file.delete")
class SafeFileDeleteTool(_MutationTool):
    tool_id = "file.delete"

    @property
    def spec(self) -> ToolSpec:
        spec = ToolSpec(
            name=self.tool_id,
            description="Quarantine one path; permanent deletion is not available.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
            },
            category="filesystem",
            requires_confirmation=True,
            required_capabilities=["file:write"],
        )
        return spec

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = self.policy.resolve(params["path"], must_exist=True)
            restore = self.policy.prepare_restore(path)
            quarantine = self.policy.restore_root / "quarantine"
            quarantine.mkdir(parents=True, exist_ok=True)
            destination = quarantine / f"{uuid.uuid4().hex}-{path.name}"
            shutil.move(str(path), str(destination))
            if path.exists() or not destination.exists():
                raise OSError("quarantine verification failed")
            return ToolResult(
                tool_name=self.tool_id,
                content="Moved target to quarantine; no permanent delete occurred.",
                metadata={
                    "path": str(path),
                    "quarantine_path": str(destination),
                    "restore_path": str(restore),
                    "verified": True,
                },
            )
        except (OSError, ValueError, FilesystemPolicyError) as exc:
            return self._error(exc)


@ToolRegistry.register("directory.create")
class SafeDirectoryCreateTool(_MutationTool):
    tool_id = "directory.create"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create one directory inside an explicitly allowed root.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
            },
            category="filesystem",
            required_capabilities=["file:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = self.policy.resolve(params["path"])
            if path.exists():
                raise FileExistsError(str(path))
            if not path.parent.exists():
                raise FileNotFoundError(str(path.parent))
            restore = self.policy.prepare_restore(path)
            path.mkdir()
            return ToolResult(
                tool_name=self.tool_id,
                content="Created directory.",
                metadata={
                    "path": str(path),
                    "restore_path": str(restore),
                    "verified": path.is_dir(),
                },
            )
        except (OSError, ValueError, FilesystemPolicyError) as exc:
            return self._error(exc)


__all__ = [
    "FilesystemPolicyError",
    "SafeDirectoryCreateTool",
    "SafeFileCopyTool",
    "SafeFileDeleteTool",
    "SafeFileListTool",
    "SafeFileMoveTool",
    "SafeFilePatchTool",
    "SafeFileReadTool",
    "SafeFileSearchTool",
    "SafeFileStatTool",
    "SafeFileWriteTool",
    "SecurePathPolicy",
]
