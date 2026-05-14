
"""Native Serena local file operator tools.

Serena Files Full Operator v1 foundation:
- inspect local folders
- index files
- search by name/content
- read safe text files
- snapshot before risky operations
- copy safely
- move only with approval
- audit folders
- find cleanup candidates
- plan/create backups
- never permanently delete in v1
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


SAFE_TEXT_SUFFIXES = {
    ".txt", ".md", ".rtf", ".json", ".yaml", ".yml", ".csv", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".xml",
    ".toml", ".ini", ".cfg", ".ps1", ".bat", ".sh", ".sql",
}

COMMON_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".docx",
    ".xlsx", ".pptx", ".zip", ".7z", ".rar", ".exe", ".dll", ".bin",
}

MAX_READ_BYTES = 2_000_000


def _files_root() -> Path:
    root = Path("outputs/files")
    root.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "snapshots", "backups", "indexes"]:
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "file"


def _resolve_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Path not found: {p}")
    return p


def _safe_unique_target(folder: Path, filename: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    counter = 2

    while True:
        candidate = folder / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _hash_file(path: Path, limit_bytes: int | None = None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        remaining = limit_bytes
        while True:
            if remaining is not None and remaining <= 0:
                break
            chunk_size = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return h.hexdigest()


def _is_safe_text(path: Path) -> bool:
    return path.suffix.lower() in SAFE_TEXT_SUFFIXES


def _read_text_file(path: Path, max_chars: int = 8000) -> str:
    if not path.is_file():
        raise RuntimeError(f"Not a file: {path}")

    if path.stat().st_size > MAX_READ_BYTES:
        raise RuntimeError(f"File too large to read safely: {path.stat().st_size} bytes")

    if not _is_safe_text(path):
        raise RuntimeError(f"Unsupported safe text read type: {path.suffix.lower()}")

    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            return text[:max_chars]
        except UnicodeDecodeError:
            continue

    return data.decode("utf-8", errors="replace")[:max_chars]


def _snapshot_file(path: Path, reason: str) -> Path:
    root = _files_root() / "snapshots"
    root.mkdir(parents=True, exist_ok=True)

    timestamp = _timestamp()
    target = root / f"{timestamp}-{_safe_slug(path.stem)}-{_safe_slug(reason)}{path.suffix}"

    if path.exists() and path.is_file():
        shutil.copy2(path, target)

    meta = {
        "source": str(path),
        "snapshot": str(target),
        "reason": reason,
        "timestamp": timestamp,
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "sha256": _hash_file(path) if path.exists() and path.is_file() else "",
    }

    meta_path = target.with_suffix(target.suffix + ".json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return target


def _save_json_artifact(kind: str, source: Path, payload: dict[str, Any]) -> Path:
    root = _files_root()
    out_dir = root / kind
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_timestamp()}-{_safe_slug(source.stem if source.is_file() else source.name)}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _collect_files(folder: Path, recursive: bool, limit: int) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    files = [p for p in folder.glob(pattern) if p.is_file()]
    return files[:limit]


class _FilesBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_files_status")
class SerenaFilesStatusTool(_FilesBaseTool):
    tool_id = "serena_files_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Files Full Operator v1 status.",
            parameters={"type": "object", "properties": {}},
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _files_root()
        return self._result(
            "Serena Files status\n\n"
            "- Status: active\n"
            "- Safe read types: " + ", ".join(sorted(SAFE_TEXT_SUFFIXES)) + "\n"
            "- Copy: allowed\n"
            "- Move: requires explicit approval\n"
            "- Delete/permanent cleanup: excluded from v1\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Indexes: {root / 'indexes'}\n"
            f"- Snapshots: {root / 'snapshots'}\n"
            f"- Backups: {root / 'backups'}",
            metadata={"root": str(root), "safe_text_suffixes": sorted(SAFE_TEXT_SUFFIXES)},
        )


@ToolRegistry.register("serena_files_index")
class SerenaFilesIndexTool(_FilesBaseTool):
    tool_id = "serena_files_index"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Index files in a folder and save a JSON index.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["folder"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            folder = _resolve_path(str(params.get("folder") or ""))
            recursive = bool(params.get("recursive", True))
            limit = int(params.get("limit") or 500)

            if not folder.is_dir():
                return self._result(f"Not a folder: {folder}", success=False)

            files = _collect_files(folder, recursive, limit)

            records = []
            for file in files:
                records.append(
                    {
                        "path": str(file),
                        "name": file.name,
                        "suffix": file.suffix.lower(),
                        "size_bytes": file.stat().st_size,
                        "safe_text": _is_safe_text(file),
                        "modified_at": file.stat().st_mtime,
                    }
                )

            suffix_counts: dict[str, int] = {}
            for r in records:
                suffix = r["suffix"] or "(none)"
                suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1

            out_path = _save_json_artifact(
                "indexes",
                folder,
                {
                    "report_type": "serena_files_index",
                    "created_at": _timestamp(),
                    "folder": str(folder),
                    "recursive": recursive,
                    "count": len(records),
                    "suffix_counts": suffix_counts,
                    "files": records,
                },
            )

            lines = [
                "Serena file index",
                "",
                f"- Folder: {folder}",
                f"- Recursive: {'yes' if recursive else 'no'}",
                f"- Files indexed: {len(records)}",
                f"- Index saved: {out_path}",
                "",
                "File types:",
            ]

            if suffix_counts:
                for suffix, count in sorted(suffix_counts.items()):
                    lines.append(f"- {suffix}: {count}")
            else:
                lines.append("- none")

            lines.extend(["", "Files:"])
            for r in records[:30]:
                lines.append(f"- {r['name']} | {r['suffix']} | {r['size_bytes']} bytes | {r['path']}")

            if len(records) > 30:
                lines.append(f"- ... plus {len(records) - 30} more")

            return self._result(
                "\n".join(lines),
                metadata={"folder": str(folder), "count": len(records), "index_path": str(out_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to index files: {exc}", success=False)


@ToolRegistry.register("serena_files_search")
class SerenaFilesSearchTool(_FilesBaseTool):
    tool_id = "serena_files_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Search files by name and optionally safe text content.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "query": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "content": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["folder", "query"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            folder = _resolve_path(str(params.get("folder") or ""))
            query = str(params.get("query") or "").strip()
            recursive = bool(params.get("recursive", True))
            search_content = bool(params.get("content", False))
            limit = int(params.get("limit") or 100)

            if not folder.is_dir():
                return self._result(f"Not a folder: {folder}", success=False)
            if not query:
                return self._result("Query is required.", success=False)

            files = _collect_files(folder, recursive, limit * 5)
            q = query.lower()

            matches: list[dict[str, Any]] = []

            for file in files:
                name_match = q in file.name.lower()
                content_match = False
                content_preview = ""

                if search_content and _is_safe_text(file) and file.stat().st_size <= MAX_READ_BYTES:
                    try:
                        text = _read_text_file(file, max_chars=20000)
                        idx = text.lower().find(q)
                        if idx >= 0:
                            content_match = True
                            start = max(0, idx - 120)
                            end = min(len(text), idx + len(query) + 120)
                            content_preview = text[start:end].replace("\n", " ")
                    except Exception:
                        pass

                if name_match or content_match:
                    matches.append(
                        {
                            "path": str(file),
                            "name": file.name,
                            "suffix": file.suffix.lower(),
                            "size_bytes": file.stat().st_size,
                            "name_match": name_match,
                            "content_match": content_match,
                            "preview": content_preview,
                        }
                    )

                if len(matches) >= limit:
                    break

            lines = [
                "Serena file search",
                "",
                f"- Folder: {folder}",
                f"- Query: {query}",
                f"- Recursive: {'yes' if recursive else 'no'}",
                f"- Content search: {'yes' if search_content else 'no'}",
                f"- Matches: {len(matches)}",
                "",
                "Matches:",
            ]

            if matches:
                for item in matches:
                    lines.append(
                        f"- {item['name']} | name_match={item['name_match']} | content_match={item['content_match']} | {item['path']}"
                    )
                    if item["preview"]:
                        lines.append(f"  preview: {item['preview']}")
            else:
                lines.append("- none")

            return self._result(
                "\n".join(lines),
                metadata={"folder": str(folder), "query": query, "matches": matches},
            )
        except Exception as exc:
            return self._result(f"Failed to search files: {exc}", success=False)


@ToolRegistry.register("serena_files_read")
class SerenaFilesReadTool(_FilesBaseTool):
    tool_id = "serena_files_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read a safe text file preview.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "preview_chars": {"type": "integer"},
                },
                "required": ["path"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = _resolve_path(str(params.get("path") or ""))
            preview_chars = int(params.get("preview_chars") or 4000)
            text = _read_text_file(path, max_chars=preview_chars)

            return self._result(
                "Serena file read\n\n"
                f"- Source: {path}\n"
                f"- Size: {path.stat().st_size} bytes\n"
                f"- Preview chars: {preview_chars}\n\n"
                "Preview:\n"
                f"{text}",
                metadata={"source": str(path), "size_bytes": path.stat().st_size, "preview_chars": preview_chars},
            )
        except Exception as exc:
            return self._result(f"Failed to read file: {exc}", success=False)


@ToolRegistry.register("serena_files_audit")
class SerenaFilesAuditTool(_FilesBaseTool):
    tool_id = "serena_files_audit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Audit a folder for file counts, sizes, types, and cleanup signals.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["folder"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            folder = _resolve_path(str(params.get("folder") or ""))
            recursive = bool(params.get("recursive", True))
            limit = int(params.get("limit") or 1000)

            if not folder.is_dir():
                return self._result(f"Not a folder: {folder}", success=False)

            files = _collect_files(folder, recursive, limit)

            total_size = sum(p.stat().st_size for p in files)
            suffix_counts: dict[str, int] = {}
            large_files = []
            empty_files = []
            safe_text_count = 0
            binary_count = 0

            for file in files:
                size = file.stat().st_size
                suffix = file.suffix.lower() or "(none)"
                suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1

                if _is_safe_text(file):
                    safe_text_count += 1
                else:
                    binary_count += 1

                if size == 0:
                    empty_files.append(str(file))
                if size >= 50 * 1024 * 1024:
                    large_files.append({"path": str(file), "size_bytes": size})

            report = {
                "report_type": "serena_files_audit",
                "created_at": _timestamp(),
                "folder": str(folder),
                "recursive": recursive,
                "files_scanned": len(files),
                "total_size_bytes": total_size,
                "safe_text_files": safe_text_count,
                "binary_or_unsupported_files": binary_count,
                "suffix_counts": suffix_counts,
                "empty_files": empty_files,
                "large_files": large_files,
            }

            report_path = _save_json_artifact("reports", folder, report)

            lines = [
                "Serena file audit",
                "",
                f"- Folder: {folder}",
                f"- Recursive: {'yes' if recursive else 'no'}",
                f"- Files scanned: {len(files)}",
                f"- Total size: {total_size} bytes",
                f"- Safe text files: {safe_text_count}",
                f"- Binary/unsupported files: {binary_count}",
                f"- Empty files: {len(empty_files)}",
                f"- Large files >= 50MB: {len(large_files)}",
                f"- Audit report: {report_path}",
                "",
                "File types:",
            ]

            if suffix_counts:
                for suffix, count in sorted(suffix_counts.items()):
                    lines.append(f"- {suffix}: {count}")
            else:
                lines.append("- none")

            return self._result(
                "\n".join(lines),
                metadata={**report, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to audit files: {exc}", success=False)


@ToolRegistry.register("serena_files_snapshot")
class SerenaFilesSnapshotTool(_FilesBaseTool):
    tool_id = "serena_files_snapshot"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a safety snapshot of one file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["path"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            source = _resolve_path(str(params.get("path") or ""))
            reason = str(params.get("reason") or "manual-snapshot").strip() or "manual-snapshot"

            if not source.is_file():
                return self._result(f"Not a file: {source}", success=False)

            snapshot = _snapshot_file(source, reason)

            return self._result(
                "Serena file snapshot created\n\n"
                f"- Source: {source}\n"
                f"- Snapshot: {snapshot}\n"
                f"- Reason: {reason}",
                metadata={"source": str(source), "snapshot": str(snapshot), "reason": reason},
            )
        except Exception as exc:
            return self._result(f"Failed to snapshot file: {exc}", success=False)


@ToolRegistry.register("serena_files_snapshots")
class SerenaFilesSnapshotsTool(_FilesBaseTool):
    tool_id = "serena_files_snapshots"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List Serena file snapshots.",
            parameters={"type": "object", "properties": {"limit": {"type": "integer"}}},
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        limit = int(params.get("limit") or 50)
        folder = _files_root() / "snapshots"

        files = [
            p for p in folder.glob("*")
            if p.is_file() and not p.name.endswith(".json")
        ]

        files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]

        lines = [
            "Serena file snapshots",
            "",
            f"- Folder: {folder}",
            f"- Snapshots found: {len(files)}",
            "",
            "Snapshots:",
        ]

        if files:
            for file in files:
                lines.append(f"- {file.name} | {file.stat().st_size} bytes | {file}")
        else:
            lines.append("- none")

        return self._result("\n".join(lines), metadata={"folder": str(folder), "count": len(files)})


@ToolRegistry.register("serena_files_copy")
class SerenaFilesCopyTool(_FilesBaseTool):
    tool_id = "serena_files_copy"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Copy a file without modifying the original.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "target_folder": {"type": "string"},
                },
                "required": ["path", "target_folder"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            source = _resolve_path(str(params.get("path") or ""))
            target_folder = Path(str(params.get("target_folder") or ""))

            if not source.is_file():
                return self._result(f"Not a file: {source}", success=False)

            target = _safe_unique_target(target_folder, source.name)
            shutil.copy2(source, target)

            return self._result(
                "Serena file copied\n\n"
                f"- Source: {source}\n"
                f"- Target: {target}\n"
                f"- Original preserved: yes",
                metadata={"source": str(source), "target": str(target), "original_preserved": True},
            )
        except Exception as exc:
            return self._result(f"Failed to copy file: {exc}", success=False)


@ToolRegistry.register("serena_files_move")
class SerenaFilesMoveTool(_FilesBaseTool):
    tool_id = "serena_files_move"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Move a file only with explicit approval. Creates snapshot first.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "target_folder": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["path", "target_folder", "approved"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            source = _resolve_path(str(params.get("path") or ""))
            target_folder = Path(str(params.get("target_folder") or ""))
            approved = bool(params.get("approved", False))

            if not approved:
                return self._result(
                    "File move blocked. Moving an original file requires explicit approval.",
                    success=False,
                    metadata={"source": str(source), "approved": False},
                )

            if not source.is_file():
                return self._result(f"Not a file: {source}", success=False)

            snapshot = _snapshot_file(source, "before-move")
            target = _safe_unique_target(target_folder, source.name)

            shutil.move(str(source), str(target))

            return self._result(
                "Serena file moved with approval\n\n"
                f"- Source: {source}\n"
                f"- Target: {target}\n"
                f"- Snapshot before move: {snapshot}",
                metadata={"source": str(source), "target": str(target), "snapshot": str(snapshot), "approved": True},
            )
        except Exception as exc:
            return self._result(f"Failed to move file: {exc}", success=False)


@ToolRegistry.register("serena_files_cleanup_candidates")
class SerenaFilesCleanupCandidatesTool(_FilesBaseTool):
    tool_id = "serena_files_cleanup_candidates"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Find duplicate, empty, large, and unsupported cleanup candidates without deleting anything.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["folder"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            folder = _resolve_path(str(params.get("folder") or ""))
            recursive = bool(params.get("recursive", True))
            limit = int(params.get("limit") or 1000)

            if not folder.is_dir():
                return self._result(f"Not a folder: {folder}", success=False)

            files = _collect_files(folder, recursive, limit)

            empty = []
            large = []
            unsupported = []
            by_name_size: dict[tuple[str, int], list[Path]] = {}

            for file in files:
                size = file.stat().st_size
                by_name_size.setdefault((file.name.lower(), size), []).append(file)

                if size == 0:
                    empty.append(str(file))
                if size >= 50 * 1024 * 1024:
                    large.append({"path": str(file), "size_bytes": size})
                if file.suffix.lower() not in SAFE_TEXT_SUFFIXES and file.suffix.lower() not in COMMON_BINARY_SUFFIXES:
                    unsupported.append(str(file))

            duplicate_groups = [
                [str(p) for p in group]
                for group in by_name_size.values()
                if len(group) > 1
            ]

            report = {
                "report_type": "serena_files_cleanup_candidates",
                "created_at": _timestamp(),
                "folder": str(folder),
                "files_scanned": len(files),
                "duplicate_groups": duplicate_groups,
                "empty_files": empty,
                "large_files": large,
                "unsupported_files": unsupported,
            }

            report_path = _save_json_artifact("reports", folder, report)

            lines = [
                "Serena file cleanup candidates",
                "",
                f"- Folder: {folder}",
                f"- Recursive: {'yes' if recursive else 'no'}",
                f"- Files scanned: {len(files)}",
                f"- Duplicate groups: {len(duplicate_groups)}",
                f"- Empty files: {len(empty)}",
                f"- Large files >= 50MB: {len(large)}",
                f"- Unsupported extensions: {len(unsupported)}",
                f"- Report: {report_path}",
                "",
                "Operator note:",
                "- No files were deleted.",
                "- Delete/permanent cleanup is not part of Files v1.",
                "- Use copy first; use move only with explicit approval.",
            ]

            return self._result(
                "\n".join(lines),
                metadata={**report, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to find cleanup candidates: {exc}", success=False)


@ToolRegistry.register("serena_files_backup_plan")
class SerenaFilesBackupPlanTool(_FilesBaseTool):
    tool_id = "serena_files_backup_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Plan a local folder backup without creating it.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["folder"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            folder = _resolve_path(str(params.get("folder") or ""))
            recursive = bool(params.get("recursive", True))
            limit = int(params.get("limit") or 5000)

            if not folder.is_dir():
                return self._result(f"Not a folder: {folder}", success=False)

            files = _collect_files(folder, recursive, limit)
            total_size = sum(p.stat().st_size for p in files)
            backup_name = f"{_timestamp()}-{_safe_slug(folder.name)}.zip"
            backup_path = _files_root() / "backups" / backup_name

            lines = [
                "Serena file backup plan",
                "",
                f"- Source folder: {folder}",
                f"- Recursive: {'yes' if recursive else 'no'}",
                f"- Files to include: {len(files)}",
                f"- Estimated size before compression: {total_size} bytes",
                f"- Planned backup path: {backup_path}",
                "",
                "Operator note:",
                "- This is a plan only. No backup was created.",
                "- Use files backup to create the zip backup.",
            ]

            return self._result(
                "\n".join(lines),
                metadata={
                    "source_folder": str(folder),
                    "recursive": recursive,
                    "files": len(files),
                    "total_size_bytes": total_size,
                    "planned_backup": str(backup_path),
                },
            )
        except Exception as exc:
            return self._result(f"Failed to create backup plan: {exc}", success=False)


@ToolRegistry.register("serena_files_backup")
class SerenaFilesBackupTool(_FilesBaseTool):
    tool_id = "serena_files_backup"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local zip backup of a folder.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["folder"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            folder = _resolve_path(str(params.get("folder") or ""))
            recursive = bool(params.get("recursive", True))
            limit = int(params.get("limit") or 5000)

            if not folder.is_dir():
                return self._result(f"Not a folder: {folder}", success=False)

            files = _collect_files(folder, recursive, limit)
            backup_path = _files_root() / "backups" / f"{_timestamp()}-{_safe_slug(folder.name)}.zip"

            with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for file in files:
                    arcname = file.relative_to(folder)
                    z.write(file, arcname)

            manifest = {
                "report_type": "serena_files_backup_manifest",
                "created_at": _timestamp(),
                "source_folder": str(folder),
                "backup_path": str(backup_path),
                "recursive": recursive,
                "files_count": len(files),
                "files": [str(p) for p in files],
            }

            manifest_path = backup_path.with_suffix(".json")
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            return self._result(
                "Serena file backup created\n\n"
                f"- Source folder: {folder}\n"
                f"- Backup: {backup_path}\n"
                f"- Manifest: {manifest_path}\n"
                f"- Files included: {len(files)}",
                metadata={"source_folder": str(folder), "backup": str(backup_path), "manifest": str(manifest_path), "files": len(files)},
            )
        except Exception as exc:
            return self._result(f"Failed to create backup: {exc}", success=False)


def _file_roots_config_path() -> Path:
    return Path("config/serena_file_roots.json")


def _load_file_roots() -> dict[str, Any]:
    path = _file_roots_config_path()
    if not path.exists():
        return {"roots": {}}

    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_file_root(root_key: str, required_permission: str | None = None) -> tuple[str, dict[str, Any], Path]:
    root_key = str(root_key or "").strip()

    if not root_key:
        raise RuntimeError("Root key is required.")

    config = _load_file_roots()
    roots = config.get("roots", {})

    if root_key not in roots:
        available = ", ".join(sorted(roots.keys())) or "none"
        raise RuntimeError(f"Unknown file root: {root_key}. Available roots: {available}")

    root = roots[root_key]
    path = Path(str(root.get("path") or "")).expanduser()

    if required_permission:
        permission_key = f"allow_{required_permission}"
        if root.get(permission_key) is not True:
            raise RuntimeError(f"Root '{root_key}' does not allow {required_permission} operations.")

    if not path.exists():
        raise RuntimeError(f"Configured root path does not exist for '{root_key}': {path}")

    if not path.is_dir():
        raise RuntimeError(f"Configured root path is not a folder for '{root_key}': {path}")

    return root_key, root, path


@ToolRegistry.register("serena_files_roots")
class SerenaFilesRootsTool(_FilesBaseTool):
    tool_id = "serena_files_roots"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List Serena's approved local file roots.",
            parameters={"type": "object", "properties": {}},
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            config = _load_file_roots()
            roots = config.get("roots", {})

            lines = [
                "Serena approved file roots",
                "",
                f"- Config: {_file_roots_config_path()}",
                f"- Roots configured: {len(roots)}",
                "",
                "Roots:",
            ]

            if not roots:
                lines.append("- none")
            else:
                for key, root in sorted(roots.items()):
                    path = Path(str(root.get("path") or ""))
                    exists = path.exists()
                    lines.append(
                        f"- {key} | {root.get('category', 'general')} | exists={'yes' if exists else 'no'} | {path}"
                    )
                    lines.append(f"  {root.get('description', '')}")
                    lines.append(
                        "  permissions: "
                        f"search={bool(root.get('allow_search'))}, "
                        f"audit={bool(root.get('allow_audit'))}, "
                        f"backup={bool(root.get('allow_backup'))}, "
                        f"organize={bool(root.get('allow_organize'))}"
                    )

            return self._result(
                "\n".join(lines),
                metadata={"config": str(_file_roots_config_path()), "roots": roots},
            )
        except Exception as exc:
            return self._result(f"Failed to list file roots: {exc}", success=False)


@ToolRegistry.register("serena_files_root_info")
class SerenaFilesRootInfoTool(_FilesBaseTool):
    tool_id = "serena_files_root_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show details for one approved local file root.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"}
                },
                "required": ["root"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root_key, root, path = _resolve_file_root(str(params.get("root") or ""))

            files = [p for p in path.glob("*") if p.is_file()]
            folders = [p for p in path.glob("*") if p.is_dir()]

            return self._result(
                "Serena file root info\n\n"
                f"- Root: {root_key}\n"
                f"- Path: {path}\n"
                f"- Description: {root.get('description', '')}\n"
                f"- Category: {root.get('category', 'general')}\n"
                f"- Exists: yes\n"
                f"- Immediate files: {len(files)}\n"
                f"- Immediate folders: {len(folders)}\n"
                f"- Allow search: {bool(root.get('allow_search'))}\n"
                f"- Allow audit: {bool(root.get('allow_audit'))}\n"
                f"- Allow backup: {bool(root.get('allow_backup'))}\n"
                f"- Allow organize: {bool(root.get('allow_organize'))}",
                metadata={"root": root_key, "path": str(path), **root},
            )
        except Exception as exc:
            return self._result(f"Failed to show file root info: {exc}", success=False)


@ToolRegistry.register("serena_files_root_index")
class SerenaFilesRootIndexTool(_FilesBaseTool):
    tool_id = "serena_files_root_index"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Index an approved file root by alias.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["root"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root_key, root, path = _resolve_file_root(str(params.get("root") or ""), required_permission="search")
            result = SerenaFilesIndexTool().execute(
                folder=str(path),
                recursive=bool(params.get("recursive", True)),
                limit=int(params.get("limit") or 500),
            )

            if result.success:
                result.content = f"Approved root: {root_key}\n\n" + result.content
                result.metadata["root"] = root_key

            return result
        except Exception as exc:
            return self._result(f"Failed to index file root: {exc}", success=False)


@ToolRegistry.register("serena_files_root_search")
class SerenaFilesRootSearchTool(_FilesBaseTool):
    tool_id = "serena_files_root_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Search an approved file root by alias.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "query": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "content": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["root", "query"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root_key, root, path = _resolve_file_root(str(params.get("root") or ""), required_permission="search")
            result = SerenaFilesSearchTool().execute(
                folder=str(path),
                query=str(params.get("query") or ""),
                recursive=bool(params.get("recursive", True)),
                content=bool(params.get("content", False)),
                limit=int(params.get("limit") or 100),
            )

            if result.success:
                result.content = f"Approved root: {root_key}\n\n" + result.content
                result.metadata["root"] = root_key

            return result
        except Exception as exc:
            return self._result(f"Failed to search file root: {exc}", success=False)


@ToolRegistry.register("serena_files_root_audit")
class SerenaFilesRootAuditTool(_FilesBaseTool):
    tool_id = "serena_files_root_audit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Audit an approved file root by alias.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["root"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root_key, root, path = _resolve_file_root(str(params.get("root") or ""), required_permission="audit")
            result = SerenaFilesAuditTool().execute(
                folder=str(path),
                recursive=bool(params.get("recursive", True)),
                limit=int(params.get("limit") or 1000),
            )

            if result.success:
                result.content = f"Approved root: {root_key}\n\n" + result.content
                result.metadata["root"] = root_key

            return result
        except Exception as exc:
            return self._result(f"Failed to audit file root: {exc}", success=False)


@ToolRegistry.register("serena_files_root_backup_plan")
class SerenaFilesRootBackupPlanTool(_FilesBaseTool):
    tool_id = "serena_files_root_backup_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Plan a backup for an approved file root by alias.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["root"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root_key, root, path = _resolve_file_root(str(params.get("root") or ""), required_permission="backup")
            result = SerenaFilesBackupPlanTool().execute(
                folder=str(path),
                recursive=bool(params.get("recursive", True)),
                limit=int(params.get("limit") or 5000),
            )

            if result.success:
                result.content = f"Approved root: {root_key}\n\n" + result.content
                result.metadata["root"] = root_key

            return result
        except Exception as exc:
            return self._result(f"Failed to plan root backup: {exc}", success=False)


@ToolRegistry.register("serena_files_root_backup")
class SerenaFilesRootBackupTool(_FilesBaseTool):
    tool_id = "serena_files_root_backup"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a backup for an approved file root by alias.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["root"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root_key, root, path = _resolve_file_root(str(params.get("root") or ""), required_permission="backup")
            result = SerenaFilesBackupTool().execute(
                folder=str(path),
                recursive=bool(params.get("recursive", True)),
                limit=int(params.get("limit") or 5000),
            )

            if result.success:
                result.content = f"Approved root: {root_key}\n\n" + result.content
                result.metadata["root"] = root_key

            return result
        except Exception as exc:
            return self._result(f"Failed to back up file root: {exc}", success=False)


def _suggest_file_category(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()

    if suffix in {".txt", ".md", ".rtf", ".docx", ".pdf"}:
        if any(k in name for k in ["invoice", "billing", "claim", "payment", "medical-aid", "medical_aid"]):
            return "billing-finance"
        if any(k in name for k in ["patient", "medical", "clinical", "health"]):
            return "healthcare"
        if any(k in name for k in ["contract", "terms", "policy", "privacy", "legal", "compliance"]):
            return "legal-compliance"
        return "documents"

    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico"}:
        return "images"

    if suffix in {".mp3", ".wav", ".m4a", ".ogg"}:
        return "audio"

    if suffix in {".mp4", ".mov", ".avi", ".mkv"}:
        return "video"

    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".sql"}:
        return "code-config"

    if suffix in {".zip", ".7z", ".rar"}:
        return "archives"

    return "general"


@ToolRegistry.register("serena_files_root_organize")
class SerenaFilesRootOrganizeTool(_FilesBaseTool):
    tool_id = "serena_files_root_organize"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Organize files from an approved root by copying them into categorized folders under outputs/files/organized. Originals are preserved.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["root"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root_key, root, path = _resolve_file_root(str(params.get("root") or ""), required_permission="organize")
            recursive = bool(params.get("recursive", True))
            limit = int(params.get("limit") or 500)

            files = _collect_files(path, recursive, limit)
            organized_root = _files_root() / "organized" / _safe_slug(root_key)
            organized_root.mkdir(parents=True, exist_ok=True)

            copied: list[dict[str, Any]] = []
            skipped: list[dict[str, str]] = []

            for file in files:
                try:
                    category = _suggest_file_category(file)
                    target_folder = organized_root / category
                    target = _safe_unique_target(target_folder, file.name)

                    shutil.copy2(file, target)

                    copied.append(
                        {
                            "source": str(file),
                            "target": str(target),
                            "category": category,
                            "size_bytes": file.stat().st_size,
                            "suffix": file.suffix.lower(),
                        }
                    )
                except Exception as exc:
                    skipped.append({"source": str(file), "error": str(exc)})

            report = {
                "report_type": "serena_files_root_organize",
                "created_at": _timestamp(),
                "root": root_key,
                "source_folder": str(path),
                "organized_root": str(organized_root),
                "recursive": recursive,
                "copied": copied,
                "skipped": skipped,
                "originals_preserved": True,
            }

            report_path = _save_json_artifact("reports", path, report)

            lines = [
                "Serena root files organized by copy",
                "",
                f"- Approved root: {root_key}",
                f"- Source folder: {path}",
                f"- Organized folder: {organized_root}",
                f"- Recursive: {'yes' if recursive else 'no'}",
                f"- Copied: {len(copied)}",
                f"- Skipped: {len(skipped)}",
                f"- Originals preserved: yes",
                f"- Report: {report_path}",
                "",
                "Copied files:",
            ]

            if copied:
                for item in copied[:30]:
                    lines.append(f"- {Path(item['source']).name} -> {item['category']} | {item['target']}")
                if len(copied) > 30:
                    lines.append(f"- ... plus {len(copied) - 30} more")
            else:
                lines.append("- none")

            lines.extend(["", "Skipped files:"])
            if skipped:
                for item in skipped[:20]:
                    lines.append(f"- {item['source']}: {item['error']}")
            else:
                lines.append("- none")

            lines.extend([
                "",
                "Operator note:",
                "- This command copies into Serena's organized file area.",
                "- Original files were not moved or deleted.",
                "- Moving originals still requires explicit approval.",
                "- Permanent delete is excluded from Files v1.",
            ])

            return self._result(
                "\n".join(lines),
                metadata={
                    "root": root_key,
                    "source_folder": str(path),
                    "organized_root": str(organized_root),
                    "copied_count": len(copied),
                    "skipped_count": len(skipped),
                    "report": str(report_path),
                },
            )
        except Exception as exc:
            return self._result(f"Failed to organize file root: {exc}", success=False)


@ToolRegistry.register("serena_files_root_cleanup_candidates")
class SerenaFilesRootCleanupCandidatesTool(_FilesBaseTool):
    tool_id = "serena_files_root_cleanup_candidates"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Find cleanup candidates in an approved file root without deleting anything.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["root"],
            },
            category="serena_files",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root_key, root, path = _resolve_file_root(str(params.get("root") or ""), required_permission="audit")

            result = SerenaFilesCleanupCandidatesTool().execute(
                folder=str(path),
                recursive=bool(params.get("recursive", True)),
                limit=int(params.get("limit") or 1000),
            )

            if result.success:
                result.content = f"Approved root: {root_key}\n\n" + result.content
                result.metadata["root"] = root_key

            return result
        except Exception as exc:
            return self._result(f"Failed to find cleanup candidates for file root: {exc}", success=False)


__all__ = [
    "SerenaFilesStatusTool",
    "SerenaFilesIndexTool",
    "SerenaFilesSearchTool",
    "SerenaFilesReadTool",
    "SerenaFilesAuditTool",
    "SerenaFilesSnapshotTool",
    "SerenaFilesSnapshotsTool",
    "SerenaFilesCopyTool",
    "SerenaFilesMoveTool",
    "SerenaFilesCleanupCandidatesTool",
    "SerenaFilesBackupPlanTool",
    "SerenaFilesBackupTool",
    "SerenaFilesRootBackupTool",
    "SerenaFilesRootCleanupCandidatesTool",
    "SerenaFilesRootOrganizeTool",
    "SerenaFilesRootBackupPlanTool",
    "SerenaFilesRootAuditTool",
    "SerenaFilesRootSearchTool",
    "SerenaFilesRootIndexTool",
    "SerenaFilesRootInfoTool",
    "SerenaFilesRootsTool",
]
