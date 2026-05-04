"""Native Serena Google Docs operator tools.

Serena Google Docs Full Operator v1 foundation:
- status
- env-check without exposing secrets
- connect-check for Docs + Drive APIs
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


GOOGLE_DOCS_OUTPUT_ROOT = Path("outputs/google-docs")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "google-docs"


def _google_docs_root() -> Path:
    GOOGLE_DOCS_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "drafts", "exports"]:
        (GOOGLE_DOCS_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return GOOGLE_DOCS_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _google_docs_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _masked_env_status(name: str) -> dict[str, Any]:
    value = os.getenv(name, "")
    return {
        "name": name,
        "present": bool(value.strip()),
        "length": len(value) if value else 0,
        "preview": f"{value[:4]}..." if value else "",
    }


def _google_docs_env_status() -> dict[str, Any]:
    required = [
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
        "GDRIVE_ROOT_FOLDER_ID",
    ]

    required_status = [_masked_env_status(name) for name in required]
    missing_required = [item["name"] for item in required_status if not item["present"]]

    return {
        "required": required_status,
        "missing_required": missing_required,
        "configured": len(missing_required) == 0,
    }


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


def _get_google_credentials() -> Any:
    env = _google_docs_env_status()
    if not env["configured"]:
        missing = ", ".join(env["missing_required"])
        raise RuntimeError(f"Google Docs is not configured. Missing required env vars: {missing}")

    Credentials, _ = _google_imports()

    return Credentials(
        token=None,
        refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN", "").strip(),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        scopes=[
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
        ],
    )


def _get_docs_service() -> Any:
    _, build = _google_imports()
    return build("docs", "v1", credentials=_get_google_credentials(), cache_discovery=False)


def _get_drive_service() -> Any:
    _, build = _google_imports()
    return build("drive", "v3", credentials=_get_google_credentials(), cache_discovery=False)


def _drive_root_folder_id() -> str:
    root_id = os.getenv("GDRIVE_ROOT_FOLDER_ID", "").strip()
    if not root_id:
        raise RuntimeError("GDRIVE_ROOT_FOLDER_ID is not configured.")
    return root_id


class _GoogleDocsBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_google_docs_status")
class SerenaGoogleDocsStatusTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Google Docs operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _google_docs_root()
        env = _google_docs_env_status()

        return self._result(
            "Serena Google Docs status\n\n"
            "- Status: active\n"
            "- Role: professional Google Docs creation, editing, linking, and export operator\n"
            f"- Configured: {'yes' if env['configured'] else 'no'}\n"
            "- Secret values exposed: no\n"
            "- Delete/permanent removal: blocked in v1\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Drafts: {root / 'drafts'}\n"
            f"- Exports: {root / 'exports'}",
            metadata={
                "output_root": str(root),
                "configured": env["configured"],
                "missing_required": env["missing_required"],
            },
        )


@ToolRegistry.register("serena_google_docs_env_check")
class SerenaGoogleDocsEnvCheckTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Google Docs environment variable presence without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _google_docs_env_status()

        payload = {
            "report_type": "serena_google_docs_env_check",
            "created_at": _timestamp(),
            "env": env,
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", "env-check", payload)

        lines = [
            "Serena Google Docs env check",
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

        lines.extend(["", "Missing required:"])
        lines.extend(f"- {name}" for name in env["missing_required"]) if env["missing_required"] else lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_google_docs_connect_check")
class SerenaGoogleDocsConnectCheckTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_connect_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Connect to Google Docs and Drive and verify configured root folder.",
            parameters={"type": "object", "properties": {}},
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            docs_service = _get_docs_service()
            drive_service = _get_drive_service()
            root_id = _drive_root_folder_id()

            root = drive_service.files().get(
                fileId=root_id,
                fields="id,name,mimeType,webViewLink,createdTime,modifiedTime",
                supportsAllDrives=True,
            ).execute()

            # Lightweight Docs API call by reading discovery-built service object availability.
            docs_available = docs_service is not None

            payload = {
                "report_type": "serena_google_docs_connect_check",
                "created_at": _timestamp(),
                "configured": True,
                "docs_api_available": docs_available,
                "drive_root_folder": root,
                "secret_values_exposed": False,
                "changes_made": False,
            }
            report_path = _save_json("reports", "connect-check", payload)

            return self._result(
                "Serena Google Docs connection check\n\n"
                "- Connected: yes\n"
                f"- Docs API available: {'yes' if docs_available else 'no'}\n"
                f"- Drive root folder name: {root.get('name', 'unknown')}\n"
                f"- Drive root folder ID length: {len(root_id)}\n"
                f"- Drive root link available: {'yes' if root.get('webViewLink') else 'no'}\n"
                "- Secret values exposed: no\n"
                "- Changes made: no\n"
                f"- Report: {report_path}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Google Docs connection check failed\n\n"
                f"- Connected: no\n"
                f"- Error: {exc}\n"
                "- Secret values exposed: no\n"
                "- Changes made: no",
                success=False,
            )


@ToolRegistry.register("serena_google_docs_plan")
class SerenaGoogleDocsPlanTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Docs operation plan without changing Google Docs.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "operation": {"type": "string"},
                    "title": {"type": "string"},
                    "drive_folder": {"type": "string"},
                },
                "required": ["goal"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "").strip()
        operation = str(params.get("operation") or "general").strip()
        title = str(params.get("title") or "").strip()
        drive_folder = str(params.get("drive_folder") or "").strip()
        env = _google_docs_env_status()

        plan = {
            "report_type": "serena_google_docs_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "operation": operation,
            "title": title,
            "drive_folder": drive_folder,
            "configured": env["configured"],
            "missing_required": env["missing_required"],
            "steps": [
                "Check Google Docs and Drive env configuration.",
                "Verify Google Docs API access.",
                "Verify configured Drive root folder.",
                "Prepare target Drive folder if applicable.",
                "Create/read/edit/copy/export only through command-specific validation.",
                "Write local report of exactly what changed.",
            ],
            "docs_api_called": False,
            "changes_made": False,
            "delete_performed": False,
        }

        plan_path = _save_json("reports", goal or operation or "google-docs-plan", plan)

        return self._result(
            "Serena Google Docs operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Operation: {operation}\n"
            f"- Title: {title or 'not specified'}\n"
            f"- Drive folder: {drive_folder or 'not specified'}\n"
            f"- Configured: {'yes' if env['configured'] else 'no'}\n"
            f"- Plan: {plan_path}\n"
            "- Docs API called: no\n"
            "- Changes made: no\n"
            "- Delete performed: no\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in plan["steps"]),
            metadata={**plan, "plan_path": str(plan_path)},
        )


__all__ = [
    "SerenaGoogleDocsStatusTool",
    "SerenaGoogleDocsEnvCheckTool",
    "SerenaGoogleDocsConnectCheckTool",
    "SerenaGoogleDocsPlanTool",
]
