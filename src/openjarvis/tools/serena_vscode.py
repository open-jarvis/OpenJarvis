
"""Native Serena VS Code developer/operator tools.

Serena VS Code Full Operator v1 foundation:
- detect VS Code availability
- operate approved project roots
- open VS Code on approved roots
- inspect project structure
- search/read files
- snapshot before edits
- create folders/files
- edit files safely
- run safe local checks
- no publish/deploy/push in v1 without approval-gated future layer
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


SAFE_READ_SUFFIXES = {
    ".txt", ".md", ".rtf", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".xml", ".sql",
    ".ps1", ".bat", ".sh", ".env.example", ".gitignore",
}

PROTECTED_NAME_PARTS = {
    ".env",
    "secret",
    "secrets",
    "credential",
    "credentials",
    "password",
    "token",
    "key",
    "prod",
    "production",
}

MAX_READ_BYTES = 2_000_000


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "vscode"


def _vscode_root() -> Path:
    root = Path("outputs/vscode")
    root.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "snapshots"]:
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def _file_roots_config_path() -> Path:
    return Path("config/serena_file_roots.json")


def _load_file_roots() -> dict[str, Any]:
    path = _file_roots_config_path()
    if not path.exists():
        return {"roots": {}}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_root(root_key: str) -> tuple[str, dict[str, Any], Path]:
    root_key = str(root_key or "").strip()
    if not root_key:
        raise RuntimeError("Root key is required.")

    roots = _load_file_roots().get("roots", {})
    if root_key not in roots:
        available = ", ".join(sorted(roots.keys())) or "none"
        raise RuntimeError(f"Unknown approved root: {root_key}. Available roots: {available}")

    root = roots[root_key]
    path = Path(str(root.get("path") or "")).expanduser()

    if not path.exists():
        raise RuntimeError(f"Approved root path does not exist: {path}")
    if not path.is_dir():
        raise RuntimeError(f"Approved root path is not a folder: {path}")

    return root_key, root, path


def _resolve_project_file(root_key: str, relative_path: str) -> tuple[str, dict[str, Any], Path, Path]:
    key, root, root_path = _resolve_root(root_key)
    rel = Path(str(relative_path or "").replace("\\", "/"))

    if rel.is_absolute() or ".." in rel.parts:
        raise RuntimeError("Relative path must stay inside the approved root.")

    target = (root_path / rel).resolve()
    root_resolved = root_path.resolve()

    if root_resolved not in target.parents and target != root_resolved:
        raise RuntimeError("Resolved path escapes the approved root.")

    return key, root, root_path, target


def _is_sensitive_path(path: Path) -> bool:
    lower = path.name.lower()
    full = str(path).lower()
    return any(part in lower or part in full for part in PROTECTED_NAME_PARTS)


def _is_safe_read(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    return suffix in SAFE_READ_SUFFIXES or name in {".gitignore", ".dockerignore"}


def _read_text(path: Path, max_chars: int = 8000) -> str:
    if not path.is_file():
        raise RuntimeError(f"Not a file: {path}")

    if path.stat().st_size > MAX_READ_BYTES:
        raise RuntimeError(f"File too large to read safely: {path.stat().st_size} bytes")

    if not _is_safe_read(path):
        raise RuntimeError(f"Unsupported safe read type: {path.suffix.lower()}")

    data = path.read_bytes()

    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)[:max_chars]
        except UnicodeDecodeError:
            continue

    return data.decode("utf-8", errors="replace")[:max_chars]


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


def _snapshot_file(path: Path, reason: str) -> Path:
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Cannot snapshot missing/non-file path: {path}")

    folder = _vscode_root() / "snapshots"
    target = _safe_unique_target(
        folder,
        f"{_timestamp()}-{_safe_slug(path.stem)}-{_safe_slug(reason)}{path.suffix}",
    )

    shutil.copy2(path, target)

    meta = {
        "source": str(path),
        "snapshot": str(target),
        "reason": reason,
        "timestamp": _timestamp(),
        "size_bytes": path.stat().st_size,
    }

    meta_path = target.with_suffix(target.suffix + ".json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return target


def _save_report(source: Path, payload: dict[str, Any]) -> Path:
    folder = _vscode_root() / "reports"
    out = folder / f"{_timestamp()}-{_safe_slug(source.name)}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def _detect_vscode_cli() -> dict[str, Any]:
    candidates = ["code", "code.cmd"]
    for cmd in candidates:
        try:
            result = subprocess.run(
                [cmd, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
            if result.returncode == 0:
                version = (result.stdout or "").strip().splitlines()
                return {"available": True, "command": cmd, "version": version}
        except Exception:
            continue

    return {"available": False, "command": "", "version": []}


def _detect_project_type(root_path: Path) -> dict[str, Any]:
    markers = {
        "python": ["pyproject.toml", "requirements.txt", "setup.py"],
        "node": ["package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"],
        "typescript": ["tsconfig.json"],
        "docker": ["Dockerfile", "docker-compose.yml", "compose.yml"],
        "git": [".git"],
        "uv": ["uv.lock"],
        "python_package": ["src"],
    }

    found: dict[str, list[str]] = {}

    for kind, names in markers.items():
        hits = []
        for name in names:
            if (root_path / name).exists():
                hits.append(name)
        if hits:
            found[kind] = hits

    languages: list[str] = []
    if "python" in found or "uv" in found:
        languages.append("python")
    if "node" in found or "typescript" in found:
        languages.append("javascript/typescript")
    if "docker" in found:
        languages.append("docker")

    return {
        "markers": found,
        "languages": languages or ["unknown"],
    }


def _collect_project_files(root_path: Path, limit: int = 500) -> list[Path]:
    ignored_dirs = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build"}
    files: list[Path] = []

    for p in root_path.rglob("*"):
        if len(files) >= limit:
            break
        if any(part in ignored_dirs for part in p.parts):
            continue
        if p.is_file():
            files.append(p)

    return files


class _VSCodeBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_vscode_status")
class SerenaVSCodeStatusTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena VS Code developer/operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        cli = _detect_vscode_cli()
        roots = _load_file_roots().get("roots", {})

        return self._result(
            "Serena VS Code status\n\n"
            f"- Status: active\n"
            f"- VS Code CLI available: {'yes' if cli['available'] else 'no'}\n"
            f"- VS Code command: {cli['command'] or 'not found'}\n"
            f"- Approved roots available: {len(roots)}\n"
            "- Local developer work: trusted with snapshots\n"
            "- Publish/deploy/push: requires explicit approval\n"
            "- Delete/destructive cleanup: excluded from v1\n"
            f"- Output root: {_vscode_root()}",
            metadata={"vscode_cli": cli, "approved_roots": sorted(roots.keys())},
        )


@ToolRegistry.register("serena_vscode_roots")
class SerenaVSCodeRootsTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_roots"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List approved roots Serena can use for VS Code operations.",
            parameters={"type": "object", "properties": {}},
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        roots = _load_file_roots().get("roots", {})
        lines = [
            "Serena VS Code approved roots",
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
                lines.append(f"- {key} | exists={'yes' if path.exists() else 'no'} | {path}")
                lines.append(f"  {root.get('description', '')}")

        return self._result("\n".join(lines), metadata={"roots": roots})


@ToolRegistry.register("serena_vscode_root_info")
class SerenaVSCodeRootInfoTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_root_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show VS Code/project info for one approved root.",
            parameters={
                "type": "object",
                "properties": {"root": {"type": "string"}},
                "required": ["root"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            project = _detect_project_type(path)

            immediate_files = len([p for p in path.glob("*") if p.is_file()])
            immediate_folders = len([p for p in path.glob("*") if p.is_dir()])

            return self._result(
                "Serena VS Code root info\n\n"
                f"- Root: {key}\n"
                f"- Path: {path}\n"
                f"- Description: {root.get('description', '')}\n"
                f"- Immediate files: {immediate_files}\n"
                f"- Immediate folders: {immediate_folders}\n"
                f"- Detected languages: {', '.join(project['languages'])}\n"
                f"- Markers: {json.dumps(project['markers'])}",
                metadata={"root": key, "path": str(path), "project": project},
            )
        except Exception as exc:
            return self._result(f"Failed to show VS Code root info: {exc}", success=False)


@ToolRegistry.register("serena_vscode_open_root")
class SerenaVSCodeOpenRootTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_open_root"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Open VS Code on an approved root.",
            parameters={
                "type": "object",
                "properties": {"root": {"type": "string"}},
                "required": ["root"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            cli = _detect_vscode_cli()

            if not cli["available"]:
                return self._result(
                    "VS Code CLI was not found. Open VS Code manually or add 'code' to PATH.",
                    success=False,
                    metadata={"root": key, "path": str(path), "vscode_cli": cli},
                )

            subprocess.Popen([cli["command"], str(path)], shell=False)

            return self._result(
                "VS Code opened on approved root\n\n"
                f"- Root: {key}\n"
                f"- Path: {path}\n"
                f"- Command: {cli['command']}",
                metadata={"root": key, "path": str(path), "command": cli["command"]},
            )
        except Exception as exc:
            return self._result(f"Failed to open VS Code root: {exc}", success=False)


@ToolRegistry.register("serena_vscode_inspect_root")
class SerenaVSCodeInspectRootTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_inspect_root"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect an approved project root like a developer.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["root"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            limit = int(params.get("limit") or 300)

            files = _collect_project_files(path, limit=limit)
            project = _detect_project_type(path)

            suffix_counts: dict[str, int] = {}
            important = []
            for file in files:
                suffix = file.suffix.lower() or "(none)"
                suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
                if file.name in {"pyproject.toml", "package.json", "README.md", "uv.lock", "tsconfig.json"}:
                    important.append(str(file.relative_to(path)))

            findings = []
            recommendations = []

            if "git" not in project["markers"]:
                findings.append("No .git folder marker detected at root.")
            if "python" in project["languages"] and "pyproject.toml" not in project["markers"].get("python", []):
                recommendations.append("Python project detected but pyproject.toml was not found.")
            if not important:
                recommendations.append("No common project metadata files found in scan limit.")

            report = {
                "report_type": "serena_vscode_root_inspection",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "project": project,
                "files_scanned": len(files),
                "suffix_counts": suffix_counts,
                "important_files": important,
                "findings": findings,
                "recommendations": recommendations,
            }

            report_path = _save_report(path, report)

            lines = [
                "Serena VS Code developer inspection",
                "",
                f"- Root: {key}",
                f"- Path: {path}",
                f"- Files scanned: {len(files)}",
                f"- Detected languages: {', '.join(project['languages'])}",
                f"- Report: {report_path}",
                "",
                "Project markers:",
            ]

            if project["markers"]:
                for marker, hits in sorted(project["markers"].items()):
                    lines.append(f"- {marker}: {', '.join(hits)}")
            else:
                lines.append("- none")

            lines.extend(["", "File types:"])
            for suffix, count in sorted(suffix_counts.items()):
                lines.append(f"- {suffix}: {count}")

            lines.extend(["", "Important files:"])
            lines.extend(f"- {item}" for item in important) if important else lines.append("- none")

            lines.extend(["", "Findings:"])
            lines.extend(f"- {item}" for item in findings) if findings else lines.append("- none")

            lines.extend(["", "Recommendations:"])
            lines.extend(f"- {item}" for item in recommendations) if recommendations else lines.append("- No immediate recommendations.")

            return self._result("\n".join(lines), metadata={**report, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to inspect VS Code root: {exc}", success=False)


@ToolRegistry.register("serena_vscode_project_report")
class SerenaVSCodeProjectReportTool(SerenaVSCodeInspectRootTool):
    tool_id = "serena_vscode_project_report"


@ToolRegistry.register("serena_vscode_search")
class SerenaVSCodeSearchTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Search approved root project files by name and optional safe text content.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "query": {"type": "string"},
                    "content": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["root", "query"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            query = str(params.get("query") or "").strip()
            content = bool(params.get("content", False))
            limit = int(params.get("limit") or 100)

            if not query:
                return self._result("Query is required.", success=False)

            # Search needs a deeper scan than the return limit so nested/new files are not missed.
            scan_limit = max(limit * 100, 1000)
            files = _collect_project_files(path, limit=scan_limit)
            q = query.lower()
            matches = []

            for file in files:
                rel = str(file.relative_to(path))
                name_match = q in file.name.lower() or q in rel.lower()
                content_match = False
                preview = ""

                if content and _is_safe_read(file) and file.stat().st_size <= MAX_READ_BYTES:
                    try:
                        text = _read_text(file, max_chars=20000)
                        idx = text.lower().find(q)
                        if idx >= 0:
                            content_match = True
                            start = max(0, idx - 120)
                            end = min(len(text), idx + len(query) + 120)
                            preview = text[start:end].replace("\n", " ")
                    except Exception:
                        pass

                if name_match or content_match:
                    matches.append(
                        {
                            "relative_path": rel,
                            "path": str(file),
                            "name_match": name_match,
                            "content_match": content_match,
                            "preview": preview,
                        }
                    )

                if len(matches) >= limit:
                    break

            lines = [
                "Serena VS Code search",
                "",
                f"- Root: {key}",
                f"- Query: {query}",
                f"- Content search: {'yes' if content else 'no'}",
                f"- Matches: {len(matches)}",
                "",
                "Matches:",
            ]

            if matches:
                for item in matches:
                    lines.append(f"- {item['relative_path']} | name={item['name_match']} | content={item['content_match']}")
                    if item["preview"]:
                        lines.append(f"  preview: {item['preview']}")
            else:
                lines.append("- none")

            return self._result("\n".join(lines), metadata={"root": key, "matches": matches})
        except Exception as exc:
            return self._result(f"Failed to search VS Code root: {exc}", success=False)


@ToolRegistry.register("serena_vscode_read")
class SerenaVSCodeReadTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read a safe text file from an approved root.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "path": {"type": "string"},
                    "preview_chars": {"type": "integer"},
                },
                "required": ["root", "path"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_file(
                str(params.get("root") or ""),
                str(params.get("path") or ""),
            )
            preview_chars = int(params.get("preview_chars") or 6000)
            text = _read_text(target, max_chars=preview_chars)

            return self._result(
                "Serena VS Code file read\n\n"
                f"- Root: {key}\n"
                f"- File: {target.relative_to(root_path)}\n"
                f"- Size: {target.stat().st_size} bytes\n"
                f"- Preview chars: {preview_chars}\n\n"
                "Preview:\n"
                f"{text}",
                metadata={"root": key, "path": str(target), "relative_path": str(target.relative_to(root_path))},
            )
        except Exception as exc:
            return self._result(f"Failed to read VS Code file: {exc}", success=False)


@ToolRegistry.register("serena_vscode_snapshot")
class SerenaVSCodeSnapshotTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_snapshot"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Snapshot a file in an approved root.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "path": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["root", "path"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_file(
                str(params.get("root") or ""),
                str(params.get("path") or ""),
            )
            reason = str(params.get("reason") or "manual-snapshot").strip() or "manual-snapshot"

            snapshot = _snapshot_file(target, reason)

            return self._result(
                "Serena VS Code file snapshot created\n\n"
                f"- Root: {key}\n"
                f"- File: {target.relative_to(root_path)}\n"
                f"- Snapshot: {snapshot}\n"
                f"- Reason: {reason}",
                metadata={"root": key, "path": str(target), "snapshot": str(snapshot)},
            )
        except Exception as exc:
            return self._result(f"Failed to snapshot VS Code file: {exc}", success=False)


@ToolRegistry.register("serena_vscode_mkdir")
class SerenaVSCodeMkdirTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_mkdir"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a folder inside an approved root.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["root", "path"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_file(
                str(params.get("root") or ""),
                str(params.get("path") or ""),
            )

            target.mkdir(parents=True, exist_ok=True)

            return self._result(
                "Serena VS Code folder ready\n\n"
                f"- Root: {key}\n"
                f"- Folder: {target.relative_to(root_path)}",
                metadata={"root": key, "folder": str(target)},
            )
        except Exception as exc:
            return self._result(f"Failed to create VS Code folder: {exc}", success=False)


@ToolRegistry.register("serena_vscode_write_file")
class SerenaVSCodeWriteFileTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_write_file"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create or overwrite a file inside an approved root. Existing files are snapshotted before overwrite.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["root", "path", "content"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_file(
                str(params.get("root") or ""),
                str(params.get("path") or ""),
            )
            content = str(params.get("content") or "")
            overwrite = bool(params.get("overwrite", False))

            if _is_sensitive_path(target):
                return self._result(
                    "Write blocked. The target path looks sensitive or production-related.",
                    success=False,
                    metadata={"root": key, "path": str(target)},
                )

            snapshot = ""
            existed = target.exists()

            if existed:
                if not overwrite:
                    return self._result(
                        "Write blocked. File already exists. Use overwrite=True to replace it with a snapshot.",
                        success=False,
                        metadata={"root": key, "path": str(target)},
                    )
                snapshot = str(_snapshot_file(target, "before-overwrite"))

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

            return self._result(
                "Serena VS Code file written\n\n"
                f"- Root: {key}\n"
                f"- File: {target.relative_to(root_path)}\n"
                f"- Existing file: {'yes' if existed else 'no'}\n"
                f"- Snapshot before overwrite: {snapshot or 'not needed'}",
                metadata={"root": key, "path": str(target), "existed": existed, "snapshot": snapshot},
            )
        except Exception as exc:
            return self._result(f"Failed to write VS Code file: {exc}", success=False)


@ToolRegistry.register("serena_vscode_edit_file")
class SerenaVSCodeEditFileTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_edit_file"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Edit a safe text file by replacing text. Snapshot is created before edit.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["root", "path", "old", "new"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_file(
                str(params.get("root") or ""),
                str(params.get("path") or ""),
            )
            old = str(params.get("old") or "")
            new = str(params.get("new") or "")
            replace_all = bool(params.get("replace_all", False))

            if not old:
                return self._result("Edit blocked. Old text is required.", success=False)

            if _is_sensitive_path(target):
                return self._result(
                    "Edit blocked. The target path looks sensitive or production-related.",
                    success=False,
                    metadata={"root": key, "path": str(target)},
                )

            text = _read_text(target, max_chars=MAX_READ_BYTES)

            count = text.count(old)
            if count == 0:
                return self._result(
                    "Edit blocked. Old text was not found.",
                    success=False,
                    metadata={"root": key, "path": str(target)},
                )

            snapshot = _snapshot_file(target, "before-edit")
            updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
            target.write_text(updated, encoding="utf-8")

            replacements = count if replace_all else 1

            return self._result(
                "Serena VS Code file edited\n\n"
                f"- Root: {key}\n"
                f"- File: {target.relative_to(root_path)}\n"
                f"- Replacements made: {replacements}\n"
                f"- Snapshot before edit: {snapshot}",
                metadata={"root": key, "path": str(target), "replacements": replacements, "snapshot": str(snapshot)},
            )
        except Exception as exc:
            return self._result(f"Failed to edit VS Code file: {exc}", success=False)


@ToolRegistry.register("serena_vscode_run_check")
class SerenaVSCodeRunCheckTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_run_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Run approved safe project checks in an approved root.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "check": {"type": "string"},
                    "module": {"type": "string"},
                },
                "required": ["root", "check"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            check = str(params.get("check") or "").strip()
            module = str(params.get("module") or "").strip()

            allowed: dict[str, list[str]] = {
                "git-status": ["git", "status", "--short"],
                "git-diff-stat": ["git", "diff", "--stat"],
                "uv-lock-check": ["uv", "lock", "--check"],
                "uv-sync-check": ["uv", "sync", "--python", "3.11", "--extra", "server"],
                "python-import": ["uv", "run", "python", "-c", f"import {module}; print('import ok: {module}')"],
            }

            if check not in allowed:
                return self._result(
                    "Check blocked. Use an approved safe check.",
                    success=False,
                    metadata={"allowed_checks": sorted(allowed.keys())},
                )

            if check == "python-import" and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", module):
                return self._result("python-import requires a safe module name.", success=False)

            cmd = allowed[check]

            result = subprocess.run(
                cmd,
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=120,
                shell=False,
            )

            output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")

            report = {
                "report_type": "serena_vscode_safe_check",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "check": check,
                "command": cmd,
                "returncode": result.returncode,
                "output": output[-12000:],
            }

            report_path = _save_report(path, report)

            return self._result(
                "Serena VS Code safe check completed\n\n"
                f"- Root: {key}\n"
                f"- Check: {check}\n"
                f"- Return code: {result.returncode}\n"
                f"- Report: {report_path}\n\n"
                "Output:\n"
                f"{output[-4000:]}",
                metadata={**report, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to run VS Code check: {exc}", success=False)


def _snapshot_metadata_files() -> list[Path]:
    folder = _vscode_root() / "snapshots"
    return sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def _load_snapshot_meta(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _simple_line_diff(before: str, after: str, max_lines: int = 200) -> list[str]:
    import difflib

    before_lines = before.splitlines()
    after_lines = after.splitlines()
    diff = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile="snapshot",
            tofile="current",
            lineterm="",
        )
    )
    return diff[:max_lines]


def _latest_snapshot_for_target(target: Path) -> tuple[Path, dict[str, Any]] | None:
    target_str = str(target)
    for meta_path in _snapshot_metadata_files():
        try:
            meta = _load_snapshot_meta(meta_path)
            if meta.get("source") == target_str:
                snapshot_path = Path(str(meta.get("snapshot") or ""))
                if snapshot_path.exists():
                    return snapshot_path, meta
        except Exception:
            continue
    return None


@ToolRegistry.register("serena_vscode_diff_file")
class SerenaVSCodeDiffFileTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_diff_file"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show a safe text diff between the current file and its latest Serena VS Code snapshot.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "path": {"type": "string"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["root", "path"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_file(
                str(params.get("root") or ""),
                str(params.get("path") or ""),
            )
            max_lines = int(params.get("max_lines") or 200)

            latest = _latest_snapshot_for_target(target)
            if not latest:
                return self._result(
                    "No Serena VS Code snapshot found for this file.",
                    success=False,
                    metadata={"root": key, "path": str(target)},
                )

            snapshot_path, meta = latest

            before = _read_text(snapshot_path, max_chars=MAX_READ_BYTES)
            after = _read_text(target, max_chars=MAX_READ_BYTES)
            diff_lines = _simple_line_diff(before, after, max_lines=max_lines)

            report = {
                "report_type": "serena_vscode_file_diff",
                "created_at": _timestamp(),
                "root": key,
                "file": str(target),
                "relative_path": str(target.relative_to(root_path)),
                "snapshot": str(snapshot_path),
                "snapshot_meta": meta,
                "diff_lines": diff_lines,
                "truncated": len(diff_lines) >= max_lines,
            }

            report_path = _save_report(target, report)

            return self._result(
                "Serena VS Code file diff\n\n"
                f"- Root: {key}\n"
                f"- File: {target.relative_to(root_path)}\n"
                f"- Snapshot: {snapshot_path}\n"
                f"- Diff lines shown: {len(diff_lines)}\n"
                f"- Report: {report_path}\n\n"
                "Diff:\n"
                + ("\n".join(diff_lines) if diff_lines else "No text differences detected."),
                metadata={**report, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to diff VS Code file: {exc}", success=False)


@ToolRegistry.register("serena_vscode_list_snapshots")
class SerenaVSCodeListSnapshotsTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_list_snapshots"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List Serena VS Code file snapshots.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "path": {"type": "string"},
                },
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            limit = int(params.get("limit") or 50)
            path_filter = str(params.get("path") or "").strip()

            rows: list[dict[str, Any]] = []
            for meta_path in _snapshot_metadata_files():
                try:
                    meta = _load_snapshot_meta(meta_path)
                    source = str(meta.get("source") or "")
                    snapshot = str(meta.get("snapshot") or "")
                    if path_filter and path_filter.lower() not in source.lower() and path_filter.lower() not in snapshot.lower():
                        continue
                    rows.append(
                        {
                            "meta": str(meta_path),
                            "source": source,
                            "snapshot": snapshot,
                            "reason": meta.get("reason", ""),
                            "timestamp": meta.get("timestamp", ""),
                            "size_bytes": meta.get("size_bytes", 0),
                        }
                    )
                    if len(rows) >= limit:
                        break
                except Exception:
                    continue

            lines = [
                "Serena VS Code snapshots",
                "",
                f"- Folder: {_vscode_root() / 'snapshots'}",
                f"- Snapshots shown: {len(rows)}",
                "",
                "Snapshots:",
            ]

            if rows:
                for row in rows:
                    lines.append(
                        f"- {Path(row['snapshot']).name} | reason={row['reason']} | source={row['source']}"
                    )
            else:
                lines.append("- none")

            return self._result("\n".join(lines), metadata={"snapshots": rows})
        except Exception as exc:
            return self._result(f"Failed to list VS Code snapshots: {exc}", success=False)


@ToolRegistry.register("serena_vscode_restore_snapshot")
class SerenaVSCodeRestoreSnapshotTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_restore_snapshot"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Restore a file from the latest Serena VS Code snapshot or a provided snapshot path. Creates safety snapshot first.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "path": {"type": "string"},
                    "snapshot": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["root", "path", "approved"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            approved = bool(params.get("approved", False))
            if not approved:
                return self._result(
                    "Restore blocked. Restoring a snapshot changes a file and requires explicit approval.",
                    success=False,
                )

            key, root, root_path, target = _resolve_project_file(
                str(params.get("root") or ""),
                str(params.get("path") or ""),
            )

            if _is_sensitive_path(target):
                return self._result(
                    "Restore blocked. Target path looks sensitive or production-related.",
                    success=False,
                    metadata={"root": key, "path": str(target)},
                )

            requested_snapshot = str(params.get("snapshot") or "").strip()

            if requested_snapshot:
                snapshot_path = Path(requested_snapshot)
                if not snapshot_path.exists() or not snapshot_path.is_file():
                    return self._result(f"Snapshot file not found: {snapshot_path}", success=False)
            else:
                latest = _latest_snapshot_for_target(target)
                if not latest:
                    return self._result(
                        "Restore blocked. No snapshot found for this file.",
                        success=False,
                        metadata={"root": key, "path": str(target)},
                    )
                snapshot_path, _meta = latest

            safety_snapshot = _snapshot_file(target, "before-restore")
            shutil.copy2(snapshot_path, target)

            return self._result(
                "Serena VS Code snapshot restored\n\n"
                f"- Root: {key}\n"
                f"- File: {target.relative_to(root_path)}\n"
                f"- Restored from: {snapshot_path}\n"
                f"- Safety snapshot before restore: {safety_snapshot}",
                metadata={
                    "root": key,
                    "path": str(target),
                    "restored_from": str(snapshot_path),
                    "safety_snapshot": str(safety_snapshot),
                    "approved": True,
                },
            )
        except Exception as exc:
            return self._result(f"Failed to restore VS Code snapshot: {exc}", success=False)


@ToolRegistry.register("serena_vscode_task_plan")
class SerenaVSCodeTaskPlanTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_task_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a developer task plan for an approved root without changing code.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "task": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["root", "task"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            task = str(params.get("task") or "").strip()
            limit = int(params.get("limit") or 300)

            if not task:
                return self._result("Task description is required.", success=False)

            project = _detect_project_type(path)
            files = _collect_project_files(path, limit=limit)

            likely_files = []
            task_terms = [t for t in re.findall(r"[A-Za-z0-9_/-]+", task.lower()) if len(t) >= 4]

            for file in files:
                rel = str(file.relative_to(path))
                lower_rel = rel.lower()
                if any(term in lower_rel for term in task_terms):
                    likely_files.append(rel)
                elif _is_safe_read(file) and file.stat().st_size <= MAX_READ_BYTES:
                    try:
                        text = _read_text(file, max_chars=12000).lower()
                        if any(term in text for term in task_terms):
                            likely_files.append(rel)
                    except Exception:
                        pass

                if len(likely_files) >= 30:
                    break

            plan = {
                "report_type": "serena_vscode_task_plan",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "task": task,
                "project": project,
                "likely_files": likely_files,
                "steps": [
                    "Inspect relevant files.",
                    "Snapshot files before edits.",
                    "Make the smallest safe change.",
                    "Run safe checks/tests.",
                    "Inspect diffs.",
                    "Prepare developer summary.",
                ],
                "approval_required_for": [
                    "publish",
                    "deploy",
                    "push",
                    "delete files",
                    "install/change dependencies",
                    "secrets/credentials",
                    "risky shell commands",
                ],
            }

            report_path = _save_report(path, plan)

            lines = [
                "Serena VS Code developer task plan",
                "",
                f"- Root: {key}",
                f"- Task: {task}",
                f"- Detected languages: {', '.join(project['languages'])}",
                f"- Likely relevant files: {len(likely_files)}",
                f"- Plan report: {report_path}",
                "",
                "Likely relevant files:",
            ]

            if likely_files:
                lines.extend(f"- {item}" for item in likely_files[:30])
            else:
                lines.append("- none found from deterministic search; inspect project structure manually.")

            lines.extend([
                "",
                "Planned steps:",
                "- Inspect relevant files.",
                "- Snapshot files before edits.",
                "- Make the smallest safe change.",
                "- Run safe checks/tests.",
                "- Inspect diffs.",
                "- Prepare developer summary.",
                "",
                "Approval required for publish/deploy/push/destructive/risky actions only.",
            ])

            return self._result("\n".join(lines), metadata={**plan, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to create VS Code task plan: {exc}", success=False)


@ToolRegistry.register("serena_vscode_implement_plan")
class SerenaVSCodeImplementPlanTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_implement_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Apply a small explicit set of file writes/edits from a structured plan. Snapshots before modifications.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "operations_json": {"type": "string"},
                    "operations_file": {"type": "string"},
                },
                "required": ["root"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path = _resolve_root(str(params.get("root") or ""))
            operations_file = str(params.get("operations_file") or "").strip()
            raw = str(params.get("operations_json") or "").strip()

            if operations_file:
                op_path = Path(operations_file)
                if not op_path.exists() or not op_path.is_file():
                    return self._result(f"operations_file not found: {op_path}", success=False)
                raw = op_path.read_text(encoding="utf-8-sig").strip()

            if not raw:
                return self._result("operations_json or operations_file is required.", success=False)

            try:
                operations = json.loads(raw)
            except Exception as exc:
                return self._result(f"Invalid operations_json: {exc}", success=False)

            if not isinstance(operations, list):
                return self._result("operations_json must be a JSON list.", success=False)

            applied: list[dict[str, Any]] = []
            blocked: list[dict[str, Any]] = []

            for op in operations:
                if not isinstance(op, dict):
                    blocked.append({"operation": op, "reason": "operation must be object"})
                    continue

                kind = str(op.get("op") or "").strip()
                rel_path = str(op.get("path") or "").strip()

                try:
                    _key, _root, _root_path, target = _resolve_project_file(key, rel_path)

                    if _is_sensitive_path(target):
                        blocked.append({"operation": op, "reason": "sensitive/protected path"})
                        continue

                    if kind == "write":
                        content = str(op.get("content") or "")
                        overwrite = bool(op.get("overwrite", False))
                        existed = target.exists()
                        snapshot = ""

                        if existed and not overwrite:
                            blocked.append({"operation": op, "reason": "target exists and overwrite was false"})
                            continue

                        if existed:
                            snapshot = str(_snapshot_file(target, "before-implement-write"))

                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(content, encoding="utf-8")
                        applied.append({"op": kind, "path": str(target), "existed": existed, "snapshot": snapshot})

                    elif kind == "replace":
                        old = str(op.get("old") or "")
                        new = str(op.get("new") or "")
                        replace_all = bool(op.get("replace_all", False))

                        if not old:
                            blocked.append({"operation": op, "reason": "old text required"})
                            continue

                        text = _read_text(target, max_chars=MAX_READ_BYTES)
                        count = text.count(old)
                        if count == 0:
                            blocked.append({"operation": op, "reason": "old text not found"})
                            continue

                        snapshot = str(_snapshot_file(target, "before-implement-replace"))
                        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
                        target.write_text(updated, encoding="utf-8")
                        applied.append(
                            {
                                "op": kind,
                                "path": str(target),
                                "replacements": count if replace_all else 1,
                                "snapshot": snapshot,
                            }
                        )

                    elif kind == "mkdir":
                        target.mkdir(parents=True, exist_ok=True)
                        applied.append({"op": kind, "path": str(target)})

                    else:
                        blocked.append({"operation": op, "reason": f"unsupported op: {kind}"})

                except Exception as exc:
                    blocked.append({"operation": op, "reason": str(exc)})

            report = {
                "report_type": "serena_vscode_implement_plan",
                "created_at": _timestamp(),
                "root": key,
                "operations_count": len(operations),
                "applied": applied,
                "blocked": blocked,
            }

            report_path = _save_report(root_path, report)

            lines = [
                "Serena VS Code implementation plan applied",
                "",
                f"- Root: {key}",
                f"- Operations requested: {len(operations)}",
                f"- Applied: {len(applied)}",
                f"- Blocked: {len(blocked)}",
                f"- Report: {report_path}",
                "",
                "Applied:",
            ]

            if applied:
                for item in applied:
                    lines.append(f"- {item['op']} | {item['path']} | snapshot={item.get('snapshot', '') or 'not needed'}")
            else:
                lines.append("- none")

            lines.extend(["", "Blocked:"])
            if blocked:
                for item in blocked:
                    lines.append(f"- {item.get('reason')}: {item.get('operation')}")
            else:
                lines.append("- none")

            return self._result("\n".join(lines), metadata={**report, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to implement VS Code plan: {exc}", success=False)


@ToolRegistry.register("serena_vscode_test_report")
class SerenaVSCodeTestReportTool(_VSCodeBaseTool):
    tool_id = "serena_vscode_test_report"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Run a set of safe checks and create a developer test report.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "checks": {"type": "string"},
                    "module": {"type": "string"},
                },
                "required": ["root"],
            },
            category="serena_vscode",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            checks_raw = str(params.get("checks") or "git-status").strip()
            module = str(params.get("module") or "").strip()

            checks = [c.strip() for c in checks_raw.split(",") if c.strip()]
            results = []

            for check in checks:
                result = SerenaVSCodeRunCheckTool().execute(root=key, check=check, module=module)
                results.append(
                    {
                        "check": check,
                        "success": result.success,
                        "content": result.content[-5000:],
                        "metadata": result.metadata,
                    }
                )

            failed = [r for r in results if not r["success"] or r["metadata"].get("returncode", 0) not in (0, None)]

            report = {
                "report_type": "serena_vscode_test_report",
                "created_at": _timestamp(),
                "root": key,
                "checks": checks,
                "results": results,
                "failed_count": len(failed),
                "passed_count": len(results) - len(failed),
            }

            report_path = _save_report(path, report)

            lines = [
                "Serena VS Code test report",
                "",
                f"- Root: {key}",
                f"- Checks run: {len(results)}",
                f"- Passed: {len(results) - len(failed)}",
                f"- Failed: {len(failed)}",
                f"- Report: {report_path}",
                "",
                "Results:",
            ]

            for item in results:
                returncode = item["metadata"].get("returncode", "n/a")
                lines.append(f"- {item['check']} | success={item['success']} | returncode={returncode}")

            if failed:
                lines.extend(["", "Attention needed:"])
                for item in failed:
                    lines.append(f"- {item['check']} needs review.")

            return self._result("\n".join(lines), metadata={**report, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to create VS Code test report: {exc}", success=False)


__all__ = [
    "SerenaVSCodeStatusTool",
    "SerenaVSCodeRootsTool",
    "SerenaVSCodeRootInfoTool",
    "SerenaVSCodeOpenRootTool",
    "SerenaVSCodeInspectRootTool",
    "SerenaVSCodeProjectReportTool",
    "SerenaVSCodeSearchTool",
    "SerenaVSCodeReadTool",
    "SerenaVSCodeSnapshotTool",
    "SerenaVSCodeMkdirTool",
    "SerenaVSCodeWriteFileTool",
    "SerenaVSCodeEditFileTool",
    "SerenaVSCodeRunCheckTool",
    "SerenaVSCodeTestReportTool",
    "SerenaVSCodeImplementPlanTool",
    "SerenaVSCodeTaskPlanTool",
    "SerenaVSCodeRestoreSnapshotTool",
    "SerenaVSCodeListSnapshotsTool",
    "SerenaVSCodeDiffFileTool",
]
