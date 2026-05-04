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
            query = (
                f"'{root_id}' in parents and trashed = false and "
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


__all__ = [
    "SerenaGDriveStatusTool",
    "SerenaGDriveEnvCheckTool",
    "SerenaGDriveRootInfoTool",
    "SerenaGDrivePlanTool",
    "SerenaGDriveMkdirTool",
    "SerenaGDriveSearchTool",
    "SerenaGDriveListTool",
    "SerenaGDriveConnectCheckTool",
]
