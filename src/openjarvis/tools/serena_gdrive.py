"""Native Serena Google Drive operator tools.

Serena Google Drive Full Operator v1 foundation:
- status
- env-check without exposing secrets
- root folder config check
- operation planning
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


GDRIVE_OUTPUT_ROOT = Path("outputs/gdrive")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "gdrive"


def _gdrive_root() -> Path:
    GDRIVE_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "plans", "downloads", "uploads", "audits"]:
        (GDRIVE_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return GDRIVE_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _gdrive_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _env_present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _masked_env_status(name: str) -> dict[str, Any]:
    value = os.getenv(name, "")
    return {
        "name": name,
        "present": bool(value.strip()),
        "length": len(value) if value else 0,
        "preview": f"{value[:4]}..." if value else "",
    }


def _gdrive_env_status() -> dict[str, Any]:
    required = [
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
        "GDRIVE_ROOT_FOLDER_ID",
    ]

    optional = [
        "GDRIVE_LOCAL_PATH",
    ]

    required_status = [_masked_env_status(name) for name in required]
    optional_status = [_masked_env_status(name) for name in optional]

    missing_required = [item["name"] for item in required_status if not item["present"]]

    return {
        "required": required_status,
        "optional": optional_status,
        "missing_required": missing_required,
        "configured": len(missing_required) == 0,
    }


class _GDriveBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_gdrive_status")
class SerenaGDriveStatusTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Google Drive operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _gdrive_root()
        env = _gdrive_env_status()

        return self._result(
            "Serena Google Drive status\n\n"
            "- Status: active\n"
            "- Role: safe Google Drive storage and organization operator\n"
            f"- Configured: {'yes' if env['configured'] else 'no'}\n"
            "- Secret values exposed: no\n"
            "- Delete/permanent removal: blocked in v1\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Plans: {root / 'plans'}\n"
            f"- Downloads: {root / 'downloads'}\n"
            f"- Upload staging: {root / 'uploads'}",
            metadata={
                "output_root": str(root),
                "configured": env["configured"],
                "missing_required": env["missing_required"],
            },
        )


@ToolRegistry.register("serena_gdrive_env_check")
class SerenaGDriveEnvCheckTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Google Drive environment variable presence without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _gdrive_env_status()

        payload = {
            "report_type": "serena_gdrive_env_check",
            "created_at": _timestamp(),
            "env": env,
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", "env-check", payload)

        lines = [
            "Serena Google Drive env check",
            "",
            f"- Configured: {'yes' if env['configured'] else 'no'}",
            f"- Missing required: {len(env['missing_required'])}",
            "- Secret values exposed: no",
            f"- Report: {report_path}",
            "",
            "Required variables:",
        ]

        for item in env["required"]:
            lines.append(
                f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}"
            )

        lines.extend(["", "Optional variables:"])
        for item in env["optional"]:
            lines.append(
                f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}"
            )

        lines.extend(["", "Missing required:"])
        lines.extend(f"- {name}" for name in env["missing_required"]) if env["missing_required"] else lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_gdrive_root_info")
class SerenaGDriveRootInfoTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_root_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show configured Google Drive root folder information without API calls.",
            parameters={"type": "object", "properties": {}},
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        root_id = os.getenv("GDRIVE_ROOT_FOLDER_ID", "").strip()
        configured = bool(root_id)

        payload = {
            "report_type": "serena_gdrive_root_info",
            "created_at": _timestamp(),
            "root_folder_configured": configured,
            "root_folder_id_present": configured,
            "root_folder_id_length": len(root_id),
            "root_folder_id_preview": f"{root_id[:6]}..." if root_id else "",
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", "root-info", payload)

        return self._result(
            "Serena Google Drive root info\n\n"
            f"- Root folder configured: {'yes' if configured else 'no'}\n"
            f"- Root folder ID length: {len(root_id)}\n"
            "- Root folder ID full value exposed: no\n"
            f"- Report: {report_path}\n\n"
            "Note:\n"
            "- This command only checks local configuration.\n"
            "- It does not call Google Drive yet.",
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_gdrive_plan")
class SerenaGDrivePlanTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Drive operation plan without calling Drive.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "operation": {"type": "string"},
                    "local_path": {"type": "string"},
                    "drive_folder": {"type": "string"},
                },
                "required": ["goal"],
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "").strip()
        operation = str(params.get("operation") or "general").strip()
        local_path = str(params.get("local_path") or "").strip()
        drive_folder = str(params.get("drive_folder") or "").strip()
        env = _gdrive_env_status()

        plan = {
            "report_type": "serena_gdrive_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "operation": operation,
            "local_path": local_path,
            "drive_folder": drive_folder,
            "configured": env["configured"],
            "missing_required": env["missing_required"],
            "steps": [
                "Check Google Drive env configuration.",
                "Verify the configured Drive root folder.",
                "Inspect local source path if applicable.",
                "Prepare Drive folder path.",
                "Perform requested Drive operation only after command-specific validation.",
                "Write a local report of exactly what changed.",
            ],
            "drive_api_called": False,
            "changes_made": False,
            "delete_performed": False,
        }

        plan_path = _save_json("plans", goal or operation or "gdrive-plan", plan)

        return self._result(
            "Serena Google Drive operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Operation: {operation}\n"
            f"- Local path: {local_path or 'not specified'}\n"
            f"- Drive folder: {drive_folder or 'not specified'}\n"
            f"- Configured: {'yes' if env['configured'] else 'no'}\n"
            f"- Plan: {plan_path}\n"
            "- Drive API called: no\n"
            "- Changes made: no\n"
            "- Delete performed: no\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in plan["steps"]),
            metadata={**plan, "plan_path": str(plan_path)},
        )


def _google_imports() -> tuple[Any, Any]:
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        return Credentials, build
    except Exception as exc:
        raise RuntimeError(
            "Google API Python dependencies are not available. "
            "Install google-api-python-client and google-auth if missing."
        ) from exc


def _get_drive_service() -> Any:
    env = _gdrive_env_status()
    if not env["configured"]:
        missing = ", ".join(env["missing_required"])
        raise RuntimeError(f"Google Drive is not configured. Missing required env vars: {missing}")

    Credentials, build = _google_imports()

    creds = Credentials(
        token=None,
        refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN", "").strip(),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        scopes=["https://www.googleapis.com/auth/drive"],
    )

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _drive_root_folder_id() -> str:
    root_id = os.getenv("GDRIVE_ROOT_FOLDER_ID", "").strip()
    if not root_id:
        raise RuntimeError("GDRIVE_ROOT_FOLDER_ID is not configured.")
    return root_id


def _drive_file_fields() -> str:
    return "files(id,name,mimeType,parents,webViewLink,webContentLink,createdTime,modifiedTime,size),nextPageToken"


def _escape_drive_query(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("'", "\\'")


def _safe_drive_name(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise RuntimeError("Drive name/path is required.")
    blocked = ["/", "\\", ".."]
    if any(item in value for item in blocked):
        raise RuntimeError(f"Unsafe Drive name: {value}")
    return value


def _find_child_folder(service: Any, parent_id: str, name: str) -> dict[str, Any] | None:
    safe_name = _escape_drive_query(name)
    query = (
        f"'{parent_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "trashed = false and "
        f"name = '{safe_name}'"
    )
    result = service.files().list(
        q=query,
        fields="files(id,name,mimeType,parents,webViewLink,createdTime,modifiedTime)",
        pageSize=10,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = result.get("files", [])
    return files[0] if files else None


def _ensure_drive_folder_path(service: Any, folder_path: str) -> dict[str, Any]:
    root_id = _drive_root_folder_id()
    parts = [
        _safe_drive_name(part)
        for part in str(folder_path or "").replace("\\", "/").split("/")
        if part.strip()
    ]

    current_id = root_id
    created: list[dict[str, Any]] = []
    existing: list[dict[str, Any]] = []

    for part in parts:
        found = _find_child_folder(service, current_id, part)
        if found:
            existing.append(found)
            current_id = found["id"]
            continue

        metadata = {
            "name": part,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [current_id],
        }
        folder = service.files().create(
            body=metadata,
            fields="id,name,mimeType,parents,webViewLink,createdTime,modifiedTime",
            supportsAllDrives=True,
        ).execute()
        created.append(folder)
        current_id = folder["id"]

    return {
        "folder_id": current_id,
        "path": folder_path,
        "created": created,
        "existing": existing,
        "changed": bool(created),
    }


@ToolRegistry.register("serena_gdrive_connect_check")
class SerenaGDriveConnectCheckTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_connect_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Connect to Google Drive and verify the configured root folder.",
            parameters={"type": "object", "properties": {}},
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            service = _get_drive_service()
            root_id = _drive_root_folder_id()

            root = service.files().get(
                fileId=root_id,
                fields="id,name,mimeType,webViewLink,createdTime,modifiedTime",
                supportsAllDrives=True,
            ).execute()

            payload = {
                "report_type": "serena_gdrive_connect_check",
                "created_at": _timestamp(),
                "configured": True,
                "root_folder": root,
                "secret_values_exposed": False,
                "changes_made": False,
                "search_scope": "broad_visible_drive",
                "note": "Broad visible-Drive search is used so nested Drive files can be found.",
            }
            report_path = _save_json("reports", "connect-check", payload)

            return self._result(
                "Serena Google Drive connection check\n\n"
                "- Connected: yes\n"
                f"- Root folder name: {root.get('name', 'unknown')}\n"
                f"- Root folder ID length: {len(root_id)}\n"
                f"- Root folder link available: {'yes' if root.get('webViewLink') else 'no'}\n"
                "- Secret values exposed: no\n"
                "- Changes made: no\n"
                f"- Report: {report_path}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Google Drive connection check failed\n\n"
                f"- Connected: no\n"
                f"- Error: {exc}\n"
                "- Secret values exposed: no\n"
                "- Changes made: no",
                success=False,
            )


@ToolRegistry.register("serena_gdrive_list")
class SerenaGDriveListTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List files/folders under the configured Google Drive root or a provided folder ID.",
            parameters={
                "type": "object",
                "properties": {
                    "folder_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            service = _get_drive_service()
            folder_id = str(params.get("folder_id") or "").strip() or _drive_root_folder_id()
            limit = int(params.get("limit") or 25)

            query = f"'{folder_id}' in parents and trashed = false"
            result = service.files().list(
                q=query,
                fields=_drive_file_fields(),
                pageSize=limit,
                orderBy="folder,name",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()

            files = result.get("files", [])
            payload = {
                "report_type": "serena_gdrive_list",
                "created_at": _timestamp(),
                "folder_id_length": len(folder_id),
                "file_count": len(files),
                "files": files,
                "changes_made": False,
            }
            report_path = _save_json("reports", "list", payload)

            lines = [
                "Serena Google Drive list",
                "",
                f"- Files/folders found: {len(files)}",
                f"- Report: {report_path}",
                "- Changes made: no",
                "",
                "Items:",
            ]

            if files:
                for item in files:
                    kind = "folder" if item.get("mimeType") == "application/vnd.google-apps.folder" else "file"
                    link = item.get("webViewLink") or ""
                    lines.append(f"- {item.get('name')} | {kind} | id={item.get('id')} | link={link}")
            else:
                lines.append("- none")

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to list Google Drive folder: {exc}", success=False)


@ToolRegistry.register("serena_gdrive_search")
class SerenaGDriveSearchTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Search Google Drive inside the configured root.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            service = _get_drive_service()
            root_id = _drive_root_folder_id()
            query_text = str(params.get("query") or "").strip()
            limit = int(params.get("limit") or 25)

            if not query_text:
                return self._result("Search query is required.", success=False)

            safe_query = _escape_drive_query(query_text)

            # Google Drive does not support simple recursive folder search with one parent query.
            # Use a broad visible-Drive search for v1 so nested files are discoverable.
            query = (
                "trashed = false and "
                f"(name contains '{safe_query}' or fullText contains '{safe_query}')"
            )

            result = service.files().list(
                q=query,
                fields=_drive_file_fields(),
                pageSize=limit,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()

            files = result.get("files", [])
            payload = {
                "report_type": "serena_gdrive_search",
                "created_at": _timestamp(),
                "query": query_text,
                "file_count": len(files),
                "files": files,
                "changes_made": False,
            }
            report_path = _save_json("reports", f"search-{query_text}", payload)

            lines = [
                "Serena Google Drive search",
                "",
                f"- Query: {query_text}",
                f"- Matches: {len(files)}",
                f"- Report: {report_path}",
                "- Changes made: no",
                "",
                "Matches:",
            ]

            if files:
                for item in files:
                    kind = "folder" if item.get("mimeType") == "application/vnd.google-apps.folder" else "file"
                    link = item.get("webViewLink") or ""
                    lines.append(f"- {item.get('name')} | {kind} | id={item.get('id')} | link={link}")
            else:
                lines.append("- none")

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to search Google Drive: {exc}", success=False)


@ToolRegistry.register("serena_gdrive_mkdir")
class SerenaGDriveMkdirTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_mkdir"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create or find a folder path inside the configured Google Drive root.",
            parameters={
                "type": "object",
                "properties": {
                    "folder_path": {"type": "string"},
                },
                "required": ["folder_path"],
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            service = _get_drive_service()
            folder_path = str(params.get("folder_path") or "").strip()

            if not folder_path:
                return self._result("Folder path is required.", success=False)

            result = _ensure_drive_folder_path(service, folder_path)

            payload = {
                "report_type": "serena_gdrive_mkdir",
                "created_at": _timestamp(),
                "folder_path": folder_path,
                "folder_id": result["folder_id"],
                "created": result["created"],
                "existing": result["existing"],
                "changes_made": result["changed"],
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"mkdir-{folder_path}", payload)

            return self._result(
                "Serena Google Drive folder ready\n\n"
                f"- Folder path: {folder_path}\n"
                f"- Folder ID: {result['folder_id']}\n"
                f"- New folders created: {len(result['created'])}\n"
                f"- Existing folders reused: {len(result['existing'])}\n"
                f"- Changes made: {'yes' if result['changed'] else 'no'}\n"
                "- Delete performed: no\n"
                f"- Report: {report_path}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to create/find Google Drive folder: {exc}", success=False)


def _media_imports() -> tuple[Any, Any]:
    try:
        from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
        return MediaFileUpload, MediaIoBaseDownload
    except Exception as exc:
        raise RuntimeError(
            "Google API media helpers are not available. "
            "Install google-api-python-client if missing."
        ) from exc


def _safe_local_file(path_value: str) -> Path:
    path = Path(str(path_value or "")).expanduser()

    if not path.exists():
        raise RuntimeError(f"Local file does not exist: {path}")
    if not path.is_file():
        raise RuntimeError(f"Local path is not a file: {path}")

    lowered = str(path).lower()
    blocked = [".env", "secret", "secrets", "credential", "credentials", "password", "token"]

    if any(item in lowered for item in blocked):
        raise RuntimeError(f"Refusing to upload sensitive-looking local file path: {path}")

    return path


def _safe_output_download_path(filename: str) -> Path:
    name = Path(str(filename or "")).name.strip()

    if not name:
        raise RuntimeError("Download filename is required.")

    lowered = name.lower()
    blocked_names = [".env", "secrets", "credentials", "token", "password"]
    if any(item in lowered for item in blocked_names):
        raise RuntimeError(f"Refusing unsafe download filename: {name}")

    folder = _gdrive_root() / "downloads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def _guess_mime_type(path: Path) -> str:
    import mimetypes

    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _get_drive_file(service: Any, file_id: str) -> dict[str, Any]:
    file_id = str(file_id or "").strip()
    if not file_id:
        raise RuntimeError("Drive file ID is required.")

    return service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,parents,webViewLink,webContentLink,createdTime,modifiedTime,size,owners(emailAddress,displayName),shared",
        supportsAllDrives=True,
    ).execute()


@ToolRegistry.register("serena_gdrive_file_info")
class SerenaGDriveFileInfoTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_file_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect Google Drive file/folder metadata.",
            parameters={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                },
                "required": ["file_id"],
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            service = _get_drive_service()
            file_id = str(params.get("file_id") or "").strip()
            info = _get_drive_file(service, file_id)

            payload = {
                "report_type": "serena_gdrive_file_info",
                "created_at": _timestamp(),
                "file": info,
                "changes_made": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"file-info-{info.get('name', file_id)}", payload)

            return self._result(
                "Serena Google Drive file info\n\n"
                f"- Name: {info.get('name', 'unknown')}\n"
                f"- ID: {info.get('id', file_id)}\n"
                f"- MIME type: {info.get('mimeType', 'unknown')}\n"
                f"- Size: {info.get('size', 'unknown')}\n"
                f"- Modified: {info.get('modifiedTime', 'unknown')}\n"
                f"- Link: {info.get('webViewLink', '')}\n"
                f"- Report: {report_path}\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to inspect Google Drive file: {exc}", success=False)


@ToolRegistry.register("serena_gdrive_share_link")
class SerenaGDriveShareLinkTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_share_link"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Return the Google Drive web link for a file/folder without changing permissions.",
            parameters={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                },
                "required": ["file_id"],
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            service = _get_drive_service()
            file_id = str(params.get("file_id") or "").strip()
            info = _get_drive_file(service, file_id)

            payload = {
                "report_type": "serena_gdrive_share_link",
                "created_at": _timestamp(),
                "file_id": file_id,
                "name": info.get("name"),
                "webViewLink": info.get("webViewLink"),
                "permissions_changed": False,
                "changes_made": False,
            }
            report_path = _save_json("reports", f"share-link-{info.get('name', file_id)}", payload)

            return self._result(
                "Serena Google Drive link\n\n"
                f"- Name: {info.get('name', 'unknown')}\n"
                f"- Link: {info.get('webViewLink', '')}\n"
                f"- Report: {report_path}\n"
                "- Permissions changed: no\n"
                "- Changes made: no\n\n"
                "Note:\n"
                "- This returns the existing Drive link. It does not make the file public.",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to get Google Drive link: {exc}", success=False)


@ToolRegistry.register("serena_gdrive_upload")
class SerenaGDriveUploadTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_upload"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Upload a safe local file into a folder under the configured Google Drive root.",
            parameters={
                "type": "object",
                "properties": {
                    "local_path": {"type": "string"},
                    "drive_folder": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["local_path"],
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            service = _get_drive_service()
            MediaFileUpload, _ = _media_imports()

            local_path = _safe_local_file(str(params.get("local_path") or ""))
            drive_folder = str(params.get("drive_folder") or "").strip()
            name = str(params.get("name") or "").strip() or local_path.name

            if drive_folder:
                folder = _ensure_drive_folder_path(service, drive_folder)
                parent_id = folder["folder_id"]
                folder_created = folder["created"]
                folder_existing = folder["existing"]
            else:
                parent_id = _drive_root_folder_id()
                folder_created = []
                folder_existing = []

            media = MediaFileUpload(str(local_path), mimetype=_guess_mime_type(local_path), resumable=True)
            metadata = {
                "name": name,
                "parents": [parent_id],
            }

            uploaded = service.files().create(
                body=metadata,
                media_body=media,
                fields="id,name,mimeType,parents,webViewLink,webContentLink,createdTime,modifiedTime,size",
                supportsAllDrives=True,
            ).execute()

            payload = {
                "report_type": "serena_gdrive_upload",
                "created_at": _timestamp(),
                "local_path": str(local_path),
                "drive_folder": drive_folder,
                "uploaded": uploaded,
                "folder_created": folder_created,
                "folder_existing": folder_existing,
                "changes_made": True,
                "upload_performed": True,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"upload-{name}", payload)

            return self._result(
                "Serena Google Drive upload complete\n\n"
                f"- Local file: {local_path}\n"
                f"- Drive name: {uploaded.get('name', name)}\n"
                f"- Drive file ID: {uploaded.get('id')}\n"
                f"- Drive folder: {drive_folder or 'configured root'}\n"
                f"- Link: {uploaded.get('webViewLink', '')}\n"
                f"- New folders created: {len(folder_created)}\n"
                f"- Report: {report_path}\n"
                "- Upload performed: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no\n"
                "- Secret values exposed: no",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to upload file to Google Drive: {exc}", success=False)


@ToolRegistry.register("serena_gdrive_download")
class SerenaGDriveDownloadTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_download"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Download a Google Drive file to Serena's local Drive downloads folder.",
            parameters={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["file_id"],
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            import io

            service = _get_drive_service()
            _, MediaIoBaseDownload = _media_imports()

            file_id = str(params.get("file_id") or "").strip()
            info = _get_drive_file(service, file_id)

            if info.get("mimeType", "").startswith("application/vnd.google-apps."):
                return self._result(
                    "Download blocked for native Google Workspace file.\n\n"
                    f"- Name: {info.get('name', 'unknown')}\n"
                    f"- MIME type: {info.get('mimeType')}\n"
                    "- Use a future export command for Google Docs/Sheets/Slides.",
                    success=False,
                )

            filename = str(params.get("name") or "").strip() or info.get("name") or f"{file_id}.bin"
            output_path = _safe_output_download_path(filename)

            request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
            fh = io.FileIO(output_path, "wb")
            downloader = MediaIoBaseDownload(fh, request)

            done = False
            progress = 0
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    progress = int(status.progress() * 100)

            fh.close()

            payload = {
                "report_type": "serena_gdrive_download",
                "created_at": _timestamp(),
                "file": info,
                "output_path": str(output_path),
                "download_performed": True,
                "changes_made": True,
                "local_file_created": True,
                "delete_performed": False,
                "progress": progress,
            }
            report_path = _save_json("reports", f"download-{filename}", payload)

            return self._result(
                "Serena Google Drive download complete\n\n"
                f"- Drive file: {info.get('name', file_id)}\n"
                f"- Local output: {output_path}\n"
                f"- Progress: {progress}%\n"
                f"- Report: {report_path}\n"
                "- Download performed: yes\n"
                "- Local file created: yes\n"
                "- Delete performed: no",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to download Google Drive file: {exc}", success=False)


@ToolRegistry.register("serena_gdrive_save_text")
class SerenaGDriveSaveTextTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_save_text"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Save text content as a file in Google Drive under the configured root.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                    "drive_folder": {"type": "string"},
                },
                "required": ["name", "content"],
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            service = _get_drive_service()
            MediaFileUpload, _ = _media_imports()

            name = str(params.get("name") or "").strip()
            content = str(params.get("content") or "")
            drive_folder = str(params.get("drive_folder") or "").strip()

            if not name:
                return self._result("File name is required.", success=False)

            safe_name = Path(name).name
            if not safe_name.lower().endswith((".txt", ".md", ".json", ".csv")):
                safe_name = safe_name + ".txt"

            staging_folder = _gdrive_root() / "uploads"
            staging_folder.mkdir(parents=True, exist_ok=True)
            local_stage = staging_folder / f"{_timestamp()}-{_safe_slug(safe_name)}"
            local_stage.write_text(content, encoding="utf-8")

            if drive_folder:
                folder = _ensure_drive_folder_path(service, drive_folder)
                parent_id = folder["folder_id"]
                folder_created = folder["created"]
                folder_existing = folder["existing"]
            else:
                parent_id = _drive_root_folder_id()
                folder_created = []
                folder_existing = []

            media = MediaFileUpload(str(local_stage), mimetype="text/plain", resumable=True)
            metadata = {
                "name": safe_name,
                "parents": [parent_id],
            }

            uploaded = service.files().create(
                body=metadata,
                media_body=media,
                fields="id,name,mimeType,parents,webViewLink,webContentLink,createdTime,modifiedTime,size",
                supportsAllDrives=True,
            ).execute()

            payload = {
                "report_type": "serena_gdrive_save_text",
                "created_at": _timestamp(),
                "name": safe_name,
                "drive_folder": drive_folder,
                "local_stage": str(local_stage),
                "uploaded": uploaded,
                "folder_created": folder_created,
                "folder_existing": folder_existing,
                "upload_performed": True,
                "changes_made": True,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"save-text-{safe_name}", payload)

            return self._result(
                "Serena Google Drive text saved\n\n"
                f"- Name: {uploaded.get('name', safe_name)}\n"
                f"- Drive folder: {drive_folder or 'configured root'}\n"
                f"- Drive file ID: {uploaded.get('id')}\n"
                f"- Link: {uploaded.get('webViewLink', '')}\n"
                f"- Report: {report_path}\n"
                "- Upload performed: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no\n"
                "- Secret values exposed: no",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to save text to Google Drive: {exc}", success=False)


def _safe_serena_output_file(path_value: str) -> Path:
    path = Path(str(path_value or "")).expanduser()

    if not path.exists():
        raise RuntimeError(f"Output file does not exist: {path}")
    if not path.is_file():
        raise RuntimeError(f"Output path is not a file: {path}")

    resolved = path.resolve()
    allowed_roots = [
        Path("outputs").resolve(),
        Path("reports").resolve(),
        Path("conversion-workspace").resolve(),
    ]

    if not any(str(resolved).lower().startswith(str(root).lower()) for root in allowed_roots if root.exists()):
        raise RuntimeError(
            "save-output only allows files from outputs, reports, or conversion-workspace."
        )

    lowered = str(path).lower()
    blocked = [".env", "secret", "secrets", "credential", "credentials", "password", "token"]
    if any(item in lowered for item in blocked):
        raise RuntimeError(f"Refusing to save sensitive-looking output path: {path}")

    return path


@ToolRegistry.register("serena_gdrive_save_output")
class SerenaGDriveSaveOutputTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_save_output"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Save an existing Serena-generated output file into Google Drive.",
            parameters={
                "type": "object",
                "properties": {
                    "local_path": {"type": "string"},
                    "drive_folder": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["local_path"],
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            local_path = _safe_serena_output_file(str(params.get("local_path") or ""))
            drive_folder = str(params.get("drive_folder") or "Serena/Outputs").strip()
            name = str(params.get("name") or "").strip() or local_path.name

            result = SerenaGDriveUploadTool().execute(
                local_path=str(local_path),
                drive_folder=drive_folder,
                name=name,
            )

            payload = {
                "report_type": "serena_gdrive_save_output",
                "created_at": _timestamp(),
                "local_path": str(local_path),
                "drive_folder": drive_folder,
                "name": name,
                "upload_success": result.success,
                "upload_result": result.metadata,
                "changes_made": result.success,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"save-output-{name}", payload)

            if result.success:
                return self._result(
                    "Serena Google Drive output saved\n\n"
                    f"- Local output: {local_path}\n"
                    f"- Drive folder: {drive_folder}\n"
                    f"- Drive name: {name}\n"
                    f"- Report: {report_path}\n"
                    "- Upload performed: yes\n"
                    "- Changes made: yes\n"
                    "- Delete performed: no\n"
                    "- Secret values exposed: no\n\n"
                    "Upload result:\n"
                    f"{result.content}",
                    metadata={**payload, "report_path": str(report_path)},
                )

            return self._result(
                "Serena Google Drive output save failed\n\n"
                f"- Local output: {local_path}\n"
                f"- Drive folder: {drive_folder}\n"
                f"- Report: {report_path}\n"
                "- Upload performed: no\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                f"{result.content}",
                success=False,
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to save Serena output to Google Drive: {exc}", success=False)


@ToolRegistry.register("serena_gdrive_audit")
class SerenaGDriveAuditTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_audit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Audit a Google Drive folder and write a local report.",
            parameters={
                "type": "object",
                "properties": {
                    "folder_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            service = _get_drive_service()
            folder_id = str(params.get("folder_id") or "").strip() or _drive_root_folder_id()
            limit = int(params.get("limit") or 100)

            query = f"'{folder_id}' in parents and trashed = false"

            result = service.files().list(
                q=query,
                fields=_drive_file_fields(),
                pageSize=limit,
                orderBy="folder,name",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()

            files = result.get("files", [])
            folders = [item for item in files if item.get("mimeType") == "application/vnd.google-apps.folder"]
            normal_files = [item for item in files if item.get("mimeType") != "application/vnd.google-apps.folder"]

            total_size = 0
            missing_size = 0
            for item in normal_files:
                try:
                    total_size += int(item.get("size") or 0)
                except Exception:
                    missing_size += 1

            duplicate_names: dict[str, list[dict[str, Any]]] = {}
            for item in files:
                duplicate_names.setdefault(item.get("name", ""), []).append(item)
            duplicates = {
                name: items for name, items in duplicate_names.items()
                if name and len(items) > 1
            }

            payload = {
                "report_type": "serena_gdrive_audit",
                "created_at": _timestamp(),
                "folder_id_length": len(folder_id),
                "item_count": len(files),
                "folder_count": len(folders),
                "file_count": len(normal_files),
                "total_file_size_bytes": total_size,
                "files_with_missing_size": missing_size,
                "duplicate_name_groups": duplicates,
                "items": files,
                "changes_made": False,
                "delete_performed": False,
            }
            report_path = _save_json("audits", "drive-folder-audit", payload)

            lines = [
                "Serena Google Drive folder audit",
                "",
                f"- Items scanned: {len(files)}",
                f"- Folders: {len(folders)}",
                f"- Files: {len(normal_files)}",
                f"- Total file size bytes: {total_size}",
                f"- Duplicate name groups: {len(duplicates)}",
                f"- Report: {report_path}",
                "- Changes made: no",
                "- Delete performed: no",
                "",
                "Items:",
            ]

            if files:
                for item in files[:50]:
                    kind = "folder" if item.get("mimeType") == "application/vnd.google-apps.folder" else "file"
                    link = item.get("webViewLink") or ""
                    lines.append(f"- {item.get('name')} | {kind} | id={item.get('id')} | link={link}")
                if len(files) > 50:
                    lines.append(f"... plus {len(files) - 50} more")
            else:
                lines.append("- none")

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to audit Google Drive folder: {exc}", success=False)


@ToolRegistry.register("serena_gdrive_blocked_delete")
class SerenaGDriveBlockedDeleteTool(_GDriveBaseTool):
    tool_id = "serena_gdrive_blocked_delete"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked Google Drive delete command for v1 safety.",
            parameters={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["file_id"],
            },
            category="serena_gdrive",
        )

    def execute(self, **params: Any) -> ToolResult:
        file_id = str(params.get("file_id") or "").strip()
        reason = str(params.get("reason") or "Delete requested.").strip()

        payload = {
            "report_type": "serena_gdrive_blocked_delete",
            "created_at": _timestamp(),
            "file_id_present": bool(file_id),
            "file_id_length": len(file_id),
            "reason": reason,
            "delete_performed": False,
            "trash_performed": False,
            "permanent_delete_performed": False,
            "changes_made": False,
            "blocked_reason": "Google Drive delete/permanent removal is blocked in v1.",
        }
        report_path = _save_json("reports", "blocked-delete", payload)

        return self._result(
            "Google Drive delete blocked by Serena Google Drive v1 policy\n\n"
            f"- File ID provided: {'yes' if file_id else 'no'}\n"
            f"- Reason: {reason}\n"
            f"- Report: {report_path}\n"
            "- Delete performed: no\n"
            "- Trash performed: no\n"
            "- Permanent delete performed: no\n"
            "- Changes made: no\n\n"
            "Policy:\n"
            "- Serena Google Drive v1 may inspect, create folders, upload, download, save text, save outputs, return links, and audit.\n"
            "- Delete/permanent removal is intentionally blocked in v1.",
            success=False,
            metadata={**payload, "report_path": str(report_path)},
        )


__all__ = [
    "SerenaGDriveStatusTool",
    "SerenaGDriveEnvCheckTool",
    "SerenaGDriveRootInfoTool",
    "SerenaGDrivePlanTool",
    "SerenaGDriveMkdirTool",
    "SerenaGDriveSaveTextTool",
    "SerenaGDriveBlockedDeleteTool",
    "SerenaGDriveAuditTool",
    "SerenaGDriveSaveOutputTool",
    "SerenaGDriveDownloadTool",
    "SerenaGDriveUploadTool",
    "SerenaGDriveShareLinkTool",
    "SerenaGDriveFileInfoTool",
    "SerenaGDriveSearchTool",
    "SerenaGDriveListTool",
    "SerenaGDriveConnectCheckTool",
]
