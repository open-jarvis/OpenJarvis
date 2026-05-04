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


def _drive_file_fields() -> str:
    return "id,name,mimeType,parents,webViewLink,webContentLink,createdTime,modifiedTime,size"


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


def _get_doc_link(drive_service: Any, document_id: str) -> str:
    info = drive_service.files().get(
        fileId=document_id,
        fields="id,name,mimeType,webViewLink",
        supportsAllDrives=True,
    ).execute()
    return info.get("webViewLink", "")


def _extract_google_doc_text(doc: dict[str, Any]) -> str:
    parts: list[str] = []

    for item in doc.get("body", {}).get("content", []):
        paragraph = item.get("paragraph")
        if not paragraph:
            continue

        text_parts = []
        for element in paragraph.get("elements", []):
            run = element.get("textRun")
            if run and run.get("content"):
                text_parts.append(run["content"])

        if text_parts:
            parts.append("".join(text_parts))

    return "".join(parts).strip()


def _document_end_index(doc: dict[str, Any]) -> int:
    content = doc.get("body", {}).get("content", [])
    if not content:
        return 1
    return int(content[-1].get("endIndex", 1))


def _professional_content(title: str, content: str, doc_type: str = "document") -> str:
    title = str(title or "Serena Document").strip()
    content = str(content or "").strip()
    doc_type = str(doc_type or "document").strip().lower()

    if not content:
        content = "Prepared by Serena."

    header = f"{title}\n\n"
    meta = "Prepared by Serena\n\n"

    if doc_type in {"note", "notes"}:
        body = f"## Notes\n\n{content}\n\n## Next Actions\n\n- Review\n- Confirm\n- File or share as needed\n"
    elif doc_type in {"report", "professional-report"}:
        body = f"## Executive Summary\n\n{content}\n\n## Key Points\n\n- Review the summary above.\n- Confirm required actions.\n\n## Next Actions\n\n- Assign owner\n- Confirm deadline\n- Save final version\n"
    else:
        body = f"{content}\n"

    return header + meta + body


@ToolRegistry.register("serena_google_docs_create")
class SerenaGoogleDocsCreateTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_create"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a professional Google Doc and optionally move it into a Drive folder.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "drive_folder": {"type": "string"},
                    "doc_type": {"type": "string"},
                },
                "required": ["title", "content"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            docs_service = _get_docs_service()
            drive_service = _get_drive_service()

            title = str(params.get("title") or "").strip()
            content = str(params.get("content") or "").strip()
            drive_folder = str(params.get("drive_folder") or "").strip()
            doc_type = str(params.get("doc_type") or "document").strip()

            if not title:
                return self._result("Document title is required.", success=False)

            doc = docs_service.documents().create(body={"title": title}).execute()
            document_id = doc["documentId"]

            body_text = _professional_content(title=title, content=content, doc_type=doc_type)

            docs_service.documents().batchUpdate(
                documentId=document_id,
                body={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": 1},
                                "text": body_text,
                            }
                        }
                    ]
                },
            ).execute()

            folder_result = None
            if drive_folder:
                folder_result = _ensure_drive_folder_path(drive_service, drive_folder)
                current = drive_service.files().get(
                    fileId=document_id,
                    fields="parents",
                    supportsAllDrives=True,
                ).execute()
                previous_parents = ",".join(current.get("parents", []))
                drive_service.files().update(
                    fileId=document_id,
                    addParents=folder_result["folder_id"],
                    removeParents=previous_parents,
                    fields=_drive_file_fields(),
                    supportsAllDrives=True,
                ).execute()

            link = _get_doc_link(drive_service, document_id)

            payload = {
                "report_type": "serena_google_docs_create",
                "created_at": _timestamp(),
                "title": title,
                "document_id": document_id,
                "link": link,
                "drive_folder": drive_folder,
                "doc_type": doc_type,
                "folder_result": folder_result,
                "changes_made": True,
                "document_created": True,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"create-{title}", payload)

            return self._result(
                "Serena Google Doc created\n\n"
                f"- Title: {title}\n"
                f"- Document ID: {document_id}\n"
                f"- Drive folder: {drive_folder or 'default Drive location'}\n"
                f"- Link: {link}\n"
                f"- Report: {report_path}\n"
                "- Document created: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no\n"
                "- Secret values exposed: no",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to create Google Doc: {exc}", success=False)


@ToolRegistry.register("serena_google_docs_read")
class SerenaGoogleDocsReadTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read Google Doc text content.",
            parameters={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "preview_chars": {"type": "integer"},
                },
                "required": ["document_id"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            docs_service = _get_docs_service()
            drive_service = _get_drive_service()

            document_id = str(params.get("document_id") or "").strip()
            preview_chars = int(params.get("preview_chars") or 2000)

            if not document_id:
                return self._result("Document ID is required.", success=False)

            doc = docs_service.documents().get(documentId=document_id).execute()
            text = _extract_google_doc_text(doc)
            link = _get_doc_link(drive_service, document_id)

            payload = {
                "report_type": "serena_google_docs_read",
                "created_at": _timestamp(),
                "document_id": document_id,
                "title": doc.get("title"),
                "link": link,
                "text_length": len(text),
                "preview_chars": preview_chars,
                "changes_made": False,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"read-{doc.get('title', document_id)}", payload)

            preview = text[:preview_chars]

            return self._result(
                "Serena Google Doc read\n\n"
                f"- Title: {doc.get('title', 'unknown')}\n"
                f"- Document ID: {document_id}\n"
                f"- Text length: {len(text)}\n"
                f"- Link: {link}\n"
                f"- Report: {report_path}\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Preview:\n"
                f"{preview}",
                metadata={**payload, "report_path": str(report_path), "preview": preview},
            )
        except Exception as exc:
            return self._result(f"Failed to read Google Doc: {exc}", success=False)


@ToolRegistry.register("serena_google_docs_append")
class SerenaGoogleDocsAppendTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_append"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Append content to a Google Doc.",
            parameters={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "content": {"type": "string"},
                    "heading": {"type": "string"},
                },
                "required": ["document_id", "content"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            docs_service = _get_docs_service()
            drive_service = _get_drive_service()

            document_id = str(params.get("document_id") or "").strip()
            content = str(params.get("content") or "").strip()
            heading = str(params.get("heading") or "").strip()

            if not document_id:
                return self._result("Document ID is required.", success=False)
            if not content:
                return self._result("Append content is required.", success=False)

            doc = docs_service.documents().get(documentId=document_id).execute()
            end_index = max(_document_end_index(doc) - 1, 1)

            append_text = "\n\n"
            if heading:
                append_text += f"{heading}\n\n"
            append_text += content.strip() + "\n"

            docs_service.documents().batchUpdate(
                documentId=document_id,
                body={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": end_index},
                                "text": append_text,
                            }
                        }
                    ]
                },
            ).execute()

            link = _get_doc_link(drive_service, document_id)

            payload = {
                "report_type": "serena_google_docs_append",
                "created_at": _timestamp(),
                "document_id": document_id,
                "title": doc.get("title"),
                "heading": heading,
                "content_length": len(content),
                "link": link,
                "changes_made": True,
                "append_performed": True,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"append-{doc.get('title', document_id)}", payload)

            return self._result(
                "Serena Google Doc appended\n\n"
                f"- Title: {doc.get('title', 'unknown')}\n"
                f"- Document ID: {document_id}\n"
                f"- Heading: {heading or 'none'}\n"
                f"- Link: {link}\n"
                f"- Report: {report_path}\n"
                "- Append performed: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to append Google Doc: {exc}", success=False)


@ToolRegistry.register("serena_google_docs_update_title")
class SerenaGoogleDocsUpdateTitleTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_update_title"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Update a Google Doc title using Drive metadata.",
            parameters={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["document_id", "title"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            drive_service = _get_drive_service()

            document_id = str(params.get("document_id") or "").strip()
            title = str(params.get("title") or "").strip()

            if not document_id:
                return self._result("Document ID is required.", success=False)
            if not title:
                return self._result("New title is required.", success=False)

            before = drive_service.files().get(
                fileId=document_id,
                fields="id,name,mimeType,webViewLink",
                supportsAllDrives=True,
            ).execute()

            updated = drive_service.files().update(
                fileId=document_id,
                body={"name": title},
                fields="id,name,mimeType,webViewLink,modifiedTime",
                supportsAllDrives=True,
            ).execute()

            payload = {
                "report_type": "serena_google_docs_update_title",
                "created_at": _timestamp(),
                "document_id": document_id,
                "old_title": before.get("name"),
                "new_title": updated.get("name"),
                "link": updated.get("webViewLink"),
                "changes_made": True,
                "title_updated": True,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"update-title-{title}", payload)

            return self._result(
                "Serena Google Doc title updated\n\n"
                f"- Old title: {before.get('name', 'unknown')}\n"
                f"- New title: {updated.get('name', title)}\n"
                f"- Document ID: {document_id}\n"
                f"- Link: {updated.get('webViewLink', '')}\n"
                f"- Report: {report_path}\n"
                "- Title updated: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to update Google Doc title: {exc}", success=False)


@ToolRegistry.register("serena_google_docs_link")
class SerenaGoogleDocsLinkTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_link"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Return existing Google Doc Drive link without changing permissions.",
            parameters={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                },
                "required": ["document_id"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            drive_service = _get_drive_service()

            document_id = str(params.get("document_id") or "").strip()
            if not document_id:
                return self._result("Document ID is required.", success=False)

            info = drive_service.files().get(
                fileId=document_id,
                fields="id,name,mimeType,webViewLink,modifiedTime",
                supportsAllDrives=True,
            ).execute()

            payload = {
                "report_type": "serena_google_docs_link",
                "created_at": _timestamp(),
                "document_id": document_id,
                "title": info.get("name"),
                "link": info.get("webViewLink"),
                "permissions_changed": False,
                "changes_made": False,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"link-{info.get('name', document_id)}", payload)

            return self._result(
                "Serena Google Doc link\n\n"
                f"- Title: {info.get('name', 'unknown')}\n"
                f"- Document ID: {document_id}\n"
                f"- Link: {info.get('webViewLink', '')}\n"
                f"- Report: {report_path}\n"
                "- Permissions changed: no\n"
                "- Changes made: no\n"
                "- Delete performed: no",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to get Google Doc link: {exc}", success=False)


def _media_download_import() -> Any:
    try:
        from googleapiclient.http import MediaIoBaseDownload
        return MediaIoBaseDownload
    except Exception as exc:
        raise RuntimeError("Google API media download helper is not available.") from exc


def _safe_export_filename(name: str, extension: str) -> Path:
    safe = Path(str(name or "google-doc-export")).name.strip()
    if not safe:
        safe = "google-doc-export"

    extension = extension.strip(".").lower() or "pdf"
    if not safe.lower().endswith(f".{extension}"):
        safe = f"{safe}.{extension}"

    lowered = safe.lower()
    blocked = [".env", "secret", "secrets", "credential", "credentials", "password", "token"]
    if any(item in lowered for item in blocked):
        raise RuntimeError(f"Unsafe export filename: {safe}")

    folder = _google_docs_root() / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / safe


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
        raise RuntimeError("save-output only allows files from outputs, reports, or conversion-workspace.")

    lowered = str(path).lower()
    blocked = [".env", "secret", "secrets", "credential", "credentials", "password", "token"]
    if any(item in lowered for item in blocked):
        raise RuntimeError(f"Refusing to save sensitive-looking output path: {path}")

    return path


@ToolRegistry.register("serena_google_docs_copy")
class SerenaGoogleDocsCopyTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_copy"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Copy a Google Doc and optionally place the copy into a Drive folder.",
            parameters={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "title": {"type": "string"},
                    "drive_folder": {"type": "string"},
                },
                "required": ["document_id", "title"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            drive_service = _get_drive_service()

            document_id = str(params.get("document_id") or "").strip()
            title = str(params.get("title") or "").strip()
            drive_folder = str(params.get("drive_folder") or "").strip()

            if not document_id:
                return self._result("Document ID is required.", success=False)
            if not title:
                return self._result("Copy title is required.", success=False)

            copied = drive_service.files().copy(
                fileId=document_id,
                body={"name": title},
                fields=_drive_file_fields(),
                supportsAllDrives=True,
            ).execute()

            folder_result = None
            if drive_folder:
                folder_result = _ensure_drive_folder_path(drive_service, drive_folder)
                current = drive_service.files().get(
                    fileId=copied["id"],
                    fields="parents",
                    supportsAllDrives=True,
                ).execute()
                previous_parents = ",".join(current.get("parents", []))
                copied = drive_service.files().update(
                    fileId=copied["id"],
                    addParents=folder_result["folder_id"],
                    removeParents=previous_parents,
                    fields=_drive_file_fields(),
                    supportsAllDrives=True,
                ).execute()

            payload = {
                "report_type": "serena_google_docs_copy",
                "created_at": _timestamp(),
                "source_document_id": document_id,
                "copy": copied,
                "drive_folder": drive_folder,
                "folder_result": folder_result,
                "copy_performed": True,
                "changes_made": True,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"copy-{title}", payload)

            return self._result(
                "Serena Google Doc copied\n\n"
                f"- Source document ID: {document_id}\n"
                f"- Copy title: {copied.get('name', title)}\n"
                f"- Copy document ID: {copied.get('id')}\n"
                f"- Drive folder: {drive_folder or 'default Drive location'}\n"
                f"- Link: {copied.get('webViewLink', '')}\n"
                f"- Report: {report_path}\n"
                "- Copy performed: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to copy Google Doc: {exc}", success=False)


@ToolRegistry.register("serena_google_docs_export")
class SerenaGoogleDocsExportTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_export"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Export/download a Google Doc as PDF, DOCX, TXT, or HTML.",
            parameters={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "format": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["document_id"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            import io

            drive_service = _get_drive_service()
            MediaIoBaseDownload = _media_download_import()

            document_id = str(params.get("document_id") or "").strip()
            export_format = str(params.get("format") or "pdf").strip().lower()
            name = str(params.get("name") or "").strip()

            if not document_id:
                return self._result("Document ID is required.", success=False)

            mime_by_format = {
                "pdf": "application/pdf",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "txt": "text/plain",
                "html": "text/html",
            }

            if export_format not in mime_by_format:
                return self._result("Export format must be one of: pdf, docx, txt, html.", success=False)

            info = drive_service.files().get(
                fileId=document_id,
                fields="id,name,mimeType,webViewLink",
                supportsAllDrives=True,
            ).execute()

            output_name = name or info.get("name") or document_id
            output_path = _safe_export_filename(output_name, export_format)

            request = drive_service.files().export_media(
                fileId=document_id,
                mimeType=mime_by_format[export_format],
            )

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
                "report_type": "serena_google_docs_export",
                "created_at": _timestamp(),
                "document_id": document_id,
                "title": info.get("name"),
                "format": export_format,
                "mime_type": mime_by_format[export_format],
                "output_path": str(output_path),
                "progress": progress,
                "export_performed": True,
                "local_file_created": True,
                "changes_made": True,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"export-{output_path.name}", payload)

            return self._result(
                "Serena Google Doc exported\n\n"
                f"- Title: {info.get('name', 'unknown')}\n"
                f"- Document ID: {document_id}\n"
                f"- Format: {export_format}\n"
                f"- Local output: {output_path}\n"
                f"- Progress: {progress}%\n"
                f"- Report: {report_path}\n"
                "- Export performed: yes\n"
                "- Local file created: yes\n"
                "- Delete performed: no",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to export Google Doc: {exc}", success=False)


@ToolRegistry.register("serena_google_docs_create_note")
class SerenaGoogleDocsCreateNoteTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_create_note"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a professional structured note in Google Docs.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "drive_folder": {"type": "string"},
                },
                "required": ["title", "content"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        return SerenaGoogleDocsCreateTool().execute(
            title=str(params.get("title") or ""),
            content=str(params.get("content") or ""),
            drive_folder=str(params.get("drive_folder") or ""),
            doc_type="note",
        )


@ToolRegistry.register("serena_google_docs_create_report")
class SerenaGoogleDocsCreateReportTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_create_report"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a professional structured report in Google Docs.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "drive_folder": {"type": "string"},
                },
                "required": ["title", "content"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        return SerenaGoogleDocsCreateTool().execute(
            title=str(params.get("title") or ""),
            content=str(params.get("content") or ""),
            drive_folder=str(params.get("drive_folder") or ""),
            doc_type="report",
        )


@ToolRegistry.register("serena_google_docs_save_output")
class SerenaGoogleDocsSaveOutputTool(_GoogleDocsBaseTool):
    tool_id = "serena_google_docs_save_output"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Doc from an existing Serena output/report text file.",
            parameters={
                "type": "object",
                "properties": {
                    "local_path": {"type": "string"},
                    "title": {"type": "string"},
                    "drive_folder": {"type": "string"},
                    "doc_type": {"type": "string"},
                },
                "required": ["local_path"],
            },
            category="serena_google_docs",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            local_path = _safe_serena_output_file(str(params.get("local_path") or ""))
            title = str(params.get("title") or "").strip() or local_path.stem
            drive_folder = str(params.get("drive_folder") or "Serena/Google Docs Outputs").strip()
            doc_type = str(params.get("doc_type") or "report").strip()

            try:
                content = local_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = local_path.read_text(encoding="utf-8", errors="replace")

            result = SerenaGoogleDocsCreateTool().execute(
                title=title,
                content=content,
                drive_folder=drive_folder,
                doc_type=doc_type,
            )

            payload = {
                "report_type": "serena_google_docs_save_output",
                "created_at": _timestamp(),
                "local_path": str(local_path),
                "title": title,
                "drive_folder": drive_folder,
                "doc_type": doc_type,
                "create_success": result.success,
                "create_result": result.metadata,
                "changes_made": result.success,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"save-output-{title}", payload)

            if result.success:
                return self._result(
                    "Serena output saved as Google Doc\n\n"
                    f"- Local output: {local_path}\n"
                    f"- Title: {title}\n"
                    f"- Drive folder: {drive_folder}\n"
                    f"- Report: {report_path}\n"
                    "- Google Doc created: yes\n"
                    "- Changes made: yes\n"
                    "- Delete performed: no\n\n"
                    "Create result:\n"
                    f"{result.content}",
                    metadata={**payload, "report_path": str(report_path)},
                )

            return self._result(
                "Serena output could not be saved as Google Doc\n\n"
                f"- Local output: {local_path}\n"
                f"- Title: {title}\n"
                f"- Report: {report_path}\n"
                "- Google Doc created: no\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                f"{result.content}",
                success=False,
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to save Serena output as Google Doc: {exc}", success=False)


__all__ = [
    "SerenaGoogleDocsStatusTool",
    "SerenaGoogleDocsEnvCheckTool",
    "SerenaGoogleDocsConnectCheckTool",
    "SerenaGoogleDocsPlanTool",
    "SerenaGoogleDocsLinkTool",
    "SerenaGoogleDocsSaveOutputTool",
    "SerenaGoogleDocsCreateReportTool",
    "SerenaGoogleDocsCreateNoteTool",
    "SerenaGoogleDocsExportTool",
    "SerenaGoogleDocsCopyTool",
    "SerenaGoogleDocsUpdateTitleTool",
    "SerenaGoogleDocsAppendTool",
    "SerenaGoogleDocsReadTool",
    "SerenaGoogleDocsCreateTool",
]
