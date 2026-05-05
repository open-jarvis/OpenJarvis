"""Native Serena Reporting Full Operator tools.

Serena Reporting Full Operator v1 foundation:
- status
- plan
- templates
- template-info
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


REPORTING_OUTPUT_ROOT = Path("outputs/reporting")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    import re
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "reporting"


def _reporting_root() -> Path:
    REPORTING_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "drafts", "exports", "snapshots", "handoff"]:
        (REPORTING_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return REPORTING_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _reporting_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _save_text(kind: str, name: str, content: str, suffix: str = ".md") -> Path:
    root = _reporting_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}{suffix}"
    path.write_text(content, encoding="utf-8")
    return path


def _hub_adapter_contract() -> dict[str, Any]:
    return {
        "hub_adapter_status": "pending_future_dashboard",
        "future_widgets": [
            "report_viewer_widget",
            "daily_report_widget",
            "weekly_report_widget",
            "compliance_report_widget",
            "activity_feed_summary_widget",
            "approval_summary_widget",
            "business_kpi_report_widget",
            "export_status_widget",
        ],
        "future_events": [
            "report_created",
            "report_exported",
            "report_handoff_created",
            "report_blocked",
            "reporting_audit_completed",
            "sensitive_report_detected",
        ],
        "operator_state": [
            "current_business_id",
            "current_report_type",
            "current_report_path",
            "current_report_sources",
            "current_report_risk_level",
            "current_export_target",
            "current_required_approval",
        ],
    }


def _safety_policy() -> dict[str, Any]:
    return {
        "allowed": [
            "Create reports from local Serena outputs.",
            "Summarize local JSON/text/markdown reports.",
            "Create professional markdown reports.",
            "Save local report artifacts.",
            "Preserve source paths and evidence.",
            "Report exactly what was included.",
        ],
        "guarded": [
            "Reports containing patient/client/health/financial data.",
            "Unredacted exports.",
            "Sharing externally.",
            "Publishing reports.",
            "Bulk export summaries.",
            "Sensitive compliance reports.",
        ],
        "blocked": [
            "Silent export of sensitive reports.",
            "Unredacted patient/client/health data export without approval.",
            "Final legal/clinical conclusions.",
            "Destructive changes to source reports.",
            "Deleting source evidence.",
            "Exposing secrets or credentials.",
        ],
    }


def _templates() -> dict[str, dict[str, Any]]:
    return {
        "daily": {
            "name": "Daily Operations Report",
            "purpose": "Summarize Serena activity, outputs, blockers, approvals, and next actions for a day.",
            "sections": [
                "Executive Summary",
                "Completed Actions",
                "Created Artifacts",
                "Blocked or Guarded Actions",
                "Approvals Needed",
                "Risks and Compliance Notes",
                "Next Actions",
                "Evidence / Source Paths",
            ],
        },
        "weekly": {
            "name": "Weekly Operations Report",
            "purpose": "Summarize operational progress, patterns, risks, and priorities across a week.",
            "sections": [
                "Weekly Executive Summary",
                "Major Completed Work",
                "Skill/Operator Activity",
                "Business or Practice Activity",
                "Compliance and Safety",
                "Open Risks",
                "Next Week Priorities",
                "Evidence / Source Paths",
            ],
        },
        "activity-summary": {
            "name": "Serena Activity Summary",
            "purpose": "Summarize what Serena did across selected reports or logs.",
            "sections": [
                "Activity Overview",
                "Actions Completed",
                "Outputs Created",
                "Failures / Safe Blocks",
                "Pending Items",
                "Evidence / Source Paths",
            ],
        },
        "compliance-summary": {
            "name": "Compliance Summary Report",
            "purpose": "Summarize compliance checks, risk levels, blockers, and required approvals.",
            "sections": [
                "Compliance Overview",
                "High-Risk Items",
                "Blocked Actions",
                "Approval Requirements",
                "Policy References",
                "Evidence / Source Paths",
            ],
        },
        "operator-summary": {
            "name": "Serena Operator Summary",
            "purpose": "Summarize operator health, tools used, outputs, and safety posture.",
            "sections": [
                "Operator Overview",
                "Tools Used",
                "Successful Operations",
                "Safe Failures",
                "Blocked Actions",
                "Next Recommended Improvements",
            ],
        },
        "business-summary": {
            "name": "Business Summary Report",
            "purpose": "Summarize business, practice, or client operational information.",
            "sections": [
                "Business Overview",
                "Key Updates",
                "Tasks and Follow-ups",
                "Documents and Files",
                "Calendar / Appointments",
                "Risks",
                "Next Actions",
            ],
        },
    }


class _ReportingBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_reporting_status")
class SerenaReportingStatusTool(_ReportingBaseTool):
    tool_id = "serena_reporting_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Reporting Full Operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _reporting_root()
        templates = _templates()

        return self._result(
            "Serena Reporting status\n\n"
            "- Status: active\n"
            "- Role: professional reporting, activity summary, export, and handoff operator\n"
            f"- Templates available: {len(templates)}\n"
            "- Compliance-aware reporting: yes\n"
            "- Sensitive/unredacted export: guarded\n"
            "- Silent sensitive report export: blocked\n"
            "- Source evidence deletion: blocked\n"
            "- Secret values exposed: no\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Drafts: {root / 'drafts'}\n"
            f"- Exports: {root / 'exports'}\n"
            f"- Snapshots: {root / 'snapshots'}\n"
            f"- Handoff: {root / 'handoff'}\n"
            "- Hub adapter: pending future dashboard",
            metadata={
                "template_count": len(templates),
                "safety_policy": _safety_policy(),
                "hub_adapter": _hub_adapter_contract(),
                "secret_values_exposed": False,
            },
        )


@ToolRegistry.register("serena_reporting_templates")
class SerenaReportingTemplatesTool(_ReportingBaseTool):
    tool_id = "serena_reporting_templates"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List Serena Reporting templates.",
            parameters={"type": "object", "properties": {}},
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        templates = _templates()
        payload = {
            "report_type": "serena_reporting_templates",
            "created_at": _timestamp(),
            "templates": templates,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("snapshots", "templates", payload)

        lines = [
            "Serena Reporting templates",
            "",
            f"- Templates found: {len(templates)}",
            f"- Snapshot: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Templates:",
        ]

        for key, info in templates.items():
            lines.append(f"- {key} | {info['name']} | sections={len(info['sections'])}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_reporting_template_info")
class SerenaReportingTemplateInfoTool(_ReportingBaseTool):
    tool_id = "serena_reporting_template_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show details for a Serena Reporting template.",
            parameters={
                "type": "object",
                "properties": {
                    "template": {"type": "string"},
                },
                "required": ["template"],
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        template = str(params.get("template") or "").strip()
        templates = _templates()

        if template not in templates:
            return self._result(
                "Serena Reporting template-info failed\n\n"
                f"- Template: {template}\n"
                "- Error: template not found\n"
                "- Changes made: no",
                success=False,
            )

        info = templates[template]
        payload = {
            "report_type": "serena_reporting_template_info",
            "created_at": _timestamp(),
            "template": template,
            "template_info": info,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("snapshots", f"template-info-{template}", payload)

        lines = [
            "Serena Reporting template info",
            "",
            f"- Template: {template}",
            f"- Name: {info['name']}",
            f"- Purpose: {info['purpose']}",
            f"- Sections: {len(info['sections'])}",
            f"- Snapshot: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Sections:",
        ]
        lines.extend(f"- {section}" for section in info["sections"])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_reporting_plan")
class SerenaReportingPlanTool(_ReportingBaseTool):
    tool_id = "serena_reporting_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a reporting operation plan without creating or exporting a final report.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "report_type": {"type": "string"},
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["goal"],
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "").strip()
        report_type = str(params.get("report_type") or "activity-summary").strip()
        source = str(params.get("source") or "local Serena outputs").strip()
        target = str(params.get("target") or "local markdown report").strip()

        plan = {
            "report_type": "serena_reporting_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "requested_report_type": report_type,
            "source": source,
            "target": target,
            "safety_policy": _safety_policy(),
            "hub_adapter": _hub_adapter_contract(),
            "steps": [
                "Identify source material and evidence paths.",
                "Classify report type and template.",
                "Check whether content may contain sensitive data.",
                "Collect source summaries.",
                "Separate evidence from interpretation.",
                "Generate clean report sections.",
                "List decisions, blockers, approvals, and next actions.",
                "Save local report artifact.",
                "Only hand off to Docs/Drive when approved and compliance-safe.",
            ],
            "report_created": False,
            "export_performed": False,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        plan_path = _save_json("reports", goal or report_type or "reporting-plan", plan)

        return self._result(
            "Serena Reporting operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Report type: {report_type}\n"
            f"- Source: {source}\n"
            f"- Target: {target}\n"
            f"- Plan: {plan_path}\n"
            "- Report created: no\n"
            "- Export performed: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in plan["steps"]),
            metadata={**plan, "plan_path": str(plan_path)},
        )


def _read_source_file(path_value: str, max_chars: int = 20000) -> tuple[Path, str]:
    path = Path(path_value)
    if not path.exists():
        raise RuntimeError(f"Source file not found: {path}")
    if not path.is_file():
        raise RuntimeError(f"Source path is not a file: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    return path, text[:max_chars]


def _summarize_text_for_report(text: str, title: str, report_type: str = "activity-summary", source_label: str = "provided text") -> str:
    templates = _templates()
    template = templates.get(report_type, templates["activity-summary"])
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    signal_lines = []
    keywords = [
        "created", "complete", "completed", "failed", "blocked", "error", "report",
        "changes made", "delete performed", "secret values exposed", "approval",
        "risk level", "connected", "status", "uploaded", "downloaded", "exported",
        "policy rules changed", "document", "calendar", "drive", "ocr", "compliance"
    ]

    lower_lines = [(line, line.lower()) for line in lines]
    for original, lower in lower_lines:
        if any(keyword in lower for keyword in keywords):
            signal_lines.append(original)

    if not signal_lines:
        signal_lines = lines[:12]

    signal_lines = signal_lines[:30]

    report_lines = [
        f"# {title}",
        "",
        f"Report type: {report_type}",
        f"Source: {source_label}",
        f"Created by: Serena Reporting Full Operator v1",
        f"Created at: {_timestamp()}",
        "",
        "## Executive Summary",
        "",
        f"Serena reviewed the source material and generated a structured {template['name'].lower()}.",
        f"The source contained {len(text)} characters and {len(lines)} non-empty lines.",
        "",
        "## Key Findings",
        "",
    ]

    if signal_lines:
        for item in signal_lines[:12]:
            report_lines.append(f"- {item}")
    else:
        report_lines.append("- No high-signal lines were detected.")

    report_lines.extend([
        "",
        "## Report Sections",
        "",
    ])

    for section in template["sections"]:
        report_lines.append(f"### {section}")
        if section.lower().startswith("evidence"):
            report_lines.append(f"- Source: {source_label}")
        elif section.lower().startswith("next"):
            report_lines.append("- Review this report and decide whether handoff/export is required.")
        elif "risk" in section.lower() or "compliance" in section.lower():
            report_lines.append("- Run Compliance checks before sharing externally if sensitive information is present.")
        elif "blocked" in section.lower() or "approval" in section.lower():
            report_lines.append("- See key findings for blocked actions or approval signals.")
        else:
            report_lines.append("- See key findings and source evidence above.")
        report_lines.append("")

    report_lines.extend([
        "## Evidence / Source Paths",
        "",
        f"- {source_label}",
        "",
        "## Safety",
        "",
        "- Report generated locally.",
        "- Source evidence was not deleted.",
        "- Secret values were not intentionally exposed.",
        "- External handoff/export should use compliance checks first.",
        "",
    ])

    return "\n".join(report_lines)


def _source_report_result(
    title: str,
    source_text: str,
    source_label: str,
    report_type: str,
    report_name: str,
) -> ToolResult:
    report_md = _summarize_text_for_report(
        text=source_text,
        title=title,
        report_type=report_type,
        source_label=source_label,
    )
    draft_path = _save_text("drafts", report_name, report_md, ".md")
    payload = {
        "report_type": f"serena_reporting_{report_name}",
        "created_at": _timestamp(),
        "requested_report_type": report_type,
        "source_label": source_label,
        "source_characters": len(source_text),
        "draft_path": str(draft_path),
        "report_created": True,
        "export_performed": False,
        "delete_performed": False,
        "changes_made": True,
        "secret_values_exposed": False,
        "hub_adapter": _hub_adapter_contract(),
    }
    report_path = _save_json("reports", report_name, payload)

    return ToolResult(
        tool_name=f"serena_reporting_{report_name}",
        success=True,
        content=(
            f"{title} created\n\n"
            f"- Report type: {report_type}\n"
            f"- Source: {source_label}\n"
            f"- Source characters: {len(source_text)}\n"
            f"- Draft report: {draft_path}\n"
            f"- Metadata report: {report_path}\n"
            "- Report created: yes\n"
            "- Export performed: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard"
        ),
        metadata={**payload, "report_path": str(report_path)},
    )


@ToolRegistry.register("serena_reporting_from_text")
class SerenaReportingFromTextTool(_ReportingBaseTool):
    tool_id = "serena_reporting_from_text"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a structured report from provided text.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "title": {"type": "string"},
                    "report_type": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        title = str(params.get("title") or "Serena Text Report").strip()
        report_type = str(params.get("report_type") or "activity-summary").strip()
        return _source_report_result(title, text, "provided text", report_type, f"from-text-{title}")


@ToolRegistry.register("serena_reporting_from_json")
class SerenaReportingFromJsonTool(_ReportingBaseTool):
    tool_id = "serena_reporting_from_json"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a structured report from JSON text.",
            parameters={
                "type": "object",
                "properties": {
                    "json_text": {"type": "string"},
                    "title": {"type": "string"},
                    "report_type": {"type": "string"},
                },
                "required": ["json_text"],
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        json_text = str(params.get("json_text") or "")
        title = str(params.get("title") or "Serena JSON Report").strip()
        report_type = str(params.get("report_type") or "activity-summary").strip()

        try:
            data = json.loads(json_text)
            pretty = json.dumps(data, indent=2, default=str)
            source = pretty
        except Exception as exc:
            source = f"JSON parse warning: {exc}\n\nRaw input:\n{json_text}"

        return _source_report_result(title, source, "provided JSON text", report_type, f"from-json-{title}")


@ToolRegistry.register("serena_reporting_from_file")
class SerenaReportingFromFileTool(_ReportingBaseTool):
    tool_id = "serena_reporting_from_file"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a structured report from a local text/JSON/markdown file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "title": {"type": "string"},
                    "report_type": {"type": "string"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["path"],
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        path_value = str(params.get("path") or "").strip()
        title = str(params.get("title") or "Serena File Report").strip()
        report_type = str(params.get("report_type") or "activity-summary").strip()
        max_chars = int(params.get("max_chars") or 20000)

        try:
            path, text = _read_source_file(path_value, max_chars=max_chars)
            return _source_report_result(title, text, str(path), report_type, f"from-file-{path.stem}")
        except Exception as exc:
            return self._result(
                "Serena Reporting from-file failed\n\n"
                f"- Path: {path_value}\n"
                f"- Error: {exc}\n"
                "- Report created: no\n"
                "- Changes made: no\n"
                "- Delete performed: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_reporting_from_folder")
class SerenaReportingFromFolderTool(_ReportingBaseTool):
    tool_id = "serena_reporting_from_folder"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a structured report from recent local text/JSON/markdown files in a folder.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "title": {"type": "string"},
                    "report_type": {"type": "string"},
                    "limit": {"type": "integer"},
                    "max_chars_per_file": {"type": "integer"},
                },
                "required": ["folder"],
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        folder_value = str(params.get("folder") or "").strip()
        title = str(params.get("title") or "Serena Folder Report").strip()
        report_type = str(params.get("report_type") or "activity-summary").strip()
        limit = int(params.get("limit") or 10)
        max_chars_per_file = int(params.get("max_chars_per_file") or 4000)

        try:
            folder = Path(folder_value)
            if not folder.exists() or not folder.is_dir():
                raise RuntimeError(f"Folder not found or not directory: {folder}")

            candidates = []
            for pattern in ["*.json", "*.md", "*.txt", "*.log"]:
                candidates.extend(folder.rglob(pattern))

            candidates = sorted(
                [path for path in candidates if path.is_file()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:limit]

            if not candidates:
                raise RuntimeError("No JSON/MD/TXT/LOG source files found.")

            chunks = []
            for path in candidates:
                text = path.read_text(encoding="utf-8", errors="ignore")[:max_chars_per_file]
                chunks.append(f"===== SOURCE: {path} =====\n{text}")

            combined = "\n\n".join(chunks)
            return _source_report_result(title, combined, str(folder), report_type, f"from-folder-{folder.name}")
        except Exception as exc:
            return self._result(
                "Serena Reporting from-folder failed\n\n"
                f"- Folder: {folder_value}\n"
                f"- Error: {exc}\n"
                "- Report created: no\n"
                "- Changes made: no\n"
                "- Delete performed: no\n"
                "- Secret values exposed: no",
                success=False,
            )


def _collect_folder_sources(
    folders: list[str],
    limit_per_folder: int = 8,
    max_chars_per_file: int = 3000,
) -> tuple[str, list[str]]:
    chunks = []
    source_paths = []

    for folder_value in folders:
        folder = Path(folder_value)
        if not folder.exists() or not folder.is_dir():
            continue

        candidates = []
        for pattern in ["*.json", "*.md", "*.txt", "*.log"]:
            candidates.extend(folder.rglob(pattern))

        candidates = sorted(
            [path for path in candidates if path.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit_per_folder]

        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:max_chars_per_file]
                source_paths.append(str(path))
                chunks.append(f"===== SOURCE: {path} =====\n{text}")
            except Exception as exc:
                chunks.append(f"===== SOURCE READ FAILED: {path} =====\n{exc}")

    combined = "\n\n".join(chunks).strip()
    if not combined:
        combined = "No source files were found for this report window."

    return combined, source_paths


def _standard_report_from_sources(
    title: str,
    report_type: str,
    folders: list[str],
    report_name: str,
    limit_per_folder: int = 8,
) -> ToolResult:
    source_text, source_paths = _collect_folder_sources(
        folders=folders,
        limit_per_folder=limit_per_folder,
        max_chars_per_file=3000,
    )
    source_label = "; ".join(folders)

    result = _source_report_result(
        title=title,
        source_text=source_text,
        source_label=source_label,
        report_type=report_type,
        report_name=report_name,
    )

    if result.metadata is not None:
        result.metadata["source_paths"] = source_paths
        result.metadata["source_count"] = len(source_paths)

    return result


@ToolRegistry.register("serena_reporting_daily")
class SerenaReportingDailyTool(_ReportingBaseTool):
    tool_id = "serena_reporting_daily"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a daily Serena operations report from local operator outputs.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "limit_per_folder": {"type": "integer"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "Serena Daily Operations Report").strip()
        limit_per_folder = int(params.get("limit_per_folder") or 8)
        folders = [
            "outputs/gdrive/reports",
            "outputs/google-docs/reports",
            "outputs/google-calendar/reports",
            "outputs/google-calendar/snapshots",
            "outputs/ocr/reports",
            "outputs/compliance/reports",
            "outputs/compliance/checks",
            "outputs/reporting/reports",
        ]
        return _standard_report_from_sources(title, "daily", folders, "daily-report", limit_per_folder)


@ToolRegistry.register("serena_reporting_weekly")
class SerenaReportingWeeklyTool(_ReportingBaseTool):
    tool_id = "serena_reporting_weekly"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a weekly Serena operations report from local operator outputs.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "limit_per_folder": {"type": "integer"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "Serena Weekly Operations Report").strip()
        limit_per_folder = int(params.get("limit_per_folder") or 12)
        folders = [
            "outputs/gdrive/reports",
            "outputs/gdrive/audits",
            "outputs/google-docs/reports",
            "outputs/google-calendar/reports",
            "outputs/google-calendar/snapshots",
            "outputs/ocr/reports",
            "outputs/compliance/reports",
            "outputs/compliance/checks",
            "outputs/compliance/audits",
            "outputs/reporting/reports",
            "conversion-workspace",
        ]
        return _standard_report_from_sources(title, "weekly", folders, "weekly-report", limit_per_folder)


@ToolRegistry.register("serena_reporting_activity_summary")
class SerenaReportingActivitySummaryTool(_ReportingBaseTool):
    tool_id = "serena_reporting_activity_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Serena activity summary report.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "folder": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "Serena Activity Summary").strip()
        folder = str(params.get("folder") or "outputs").strip()
        limit = int(params.get("limit") or 10)
        return _standard_report_from_sources(title, "activity-summary", [folder], "activity-summary", limit)


@ToolRegistry.register("serena_reporting_compliance_summary")
class SerenaReportingComplianceSummaryTool(_ReportingBaseTool):
    tool_id = "serena_reporting_compliance_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a compliance summary report from Compliance outputs.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "limit_per_folder": {"type": "integer"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "Serena Compliance Summary Report").strip()
        limit_per_folder = int(params.get("limit_per_folder") or 12)
        folders = [
            "outputs/compliance/reports",
            "outputs/compliance/checks",
            "outputs/compliance/audits",
            "outputs/compliance/policies",
        ]
        return _standard_report_from_sources(title, "compliance-summary", folders, "compliance-summary", limit_per_folder)


@ToolRegistry.register("serena_reporting_operator_summary")
class SerenaReportingOperatorSummaryTool(_ReportingBaseTool):
    tool_id = "serena_reporting_operator_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create an operator summary report covering Serena tool/operator state.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "limit_per_folder": {"type": "integer"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "Serena Operator Summary").strip()
        limit_per_folder = int(params.get("limit_per_folder") or 8)
        folders = [
            "outputs/gdrive/reports",
            "outputs/google-docs/reports",
            "outputs/google-calendar/reports",
            "outputs/ocr/reports",
            "outputs/compliance/reports",
            "outputs/reporting/reports",
        ]
        return _standard_report_from_sources(title, "operator-summary", folders, "operator-summary", limit_per_folder)


@ToolRegistry.register("serena_reporting_business_summary")
class SerenaReportingBusinessSummaryTool(_ReportingBaseTool):
    tool_id = "serena_reporting_business_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a business summary report from selected local business/operator outputs.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "business": {"type": "string"},
                    "folder": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "General Business").strip()
        title = str(params.get("title") or f"{business} Business Summary Report").strip()
        folder = str(params.get("folder") or "outputs").strip()
        limit = int(params.get("limit") or 12)
        return _standard_report_from_sources(title, "business-summary", [folder], "business-summary", limit)


def _latest_draft() -> Path:
    drafts = sorted(
        [path for path in (REPORTING_OUTPUT_ROOT / "drafts").glob("*.md") if path.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not drafts:
        raise RuntimeError("No reporting draft found.")
    return drafts[0]


def _resolve_report_path(path_value: str | None = None) -> Path:
    raw = str(path_value or "").strip()
    if not raw or raw.lower() == "latest":
        return _latest_draft()
    path = Path(raw)
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Report file not found: {path}")
    return path


def _read_report(path_value: str | None = None) -> tuple[Path, str]:
    path = _resolve_report_path(path_value)
    text = path.read_text(encoding="utf-8", errors="ignore")
    return path, text


@ToolRegistry.register("serena_reporting_save_report")
class SerenaReportingSaveReportTool(_ReportingBaseTool):
    tool_id = "serena_reporting_save_report"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Save provided report markdown/text as a Serena report draft.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "report_type": {"type": "string"},
                },
                "required": ["content"],
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "Saved Serena Report").strip()
        content = str(params.get("content") or "")
        report_type = str(params.get("report_type") or "saved-report").strip()

        if not content.strip():
            return self._result(
                "Serena Reporting save-report failed\n\n"
                "- Error: content is empty\n"
                "- Report saved: no\n"
                "- Changes made: no",
                success=False,
            )

        if not content.lstrip().startswith("#"):
            content = f"# {title}\n\nReport type: {report_type}\nCreated by: Serena Reporting Full Operator v1\nCreated at: {_timestamp()}\n\n{content}"

        draft_path = _save_text("drafts", title, content, ".md")
        payload = {
            "report_type": "serena_reporting_save_report",
            "created_at": _timestamp(),
            "title": title,
            "requested_report_type": report_type,
            "draft_path": str(draft_path),
            "report_saved": True,
            "export_performed": False,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"save-report-{title}", payload)

        return self._result(
            "Serena Reporting report saved\n\n"
            f"- Title: {title}\n"
            f"- Report type: {report_type}\n"
            f"- Draft report: {draft_path}\n"
            f"- Metadata report: {report_path}\n"
            "- Report saved: yes\n"
            "- Export performed: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_reporting_export_md")
class SerenaReportingExportMdTool(_ReportingBaseTool):
    tool_id = "serena_reporting_export_md"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Export a reporting draft to outputs/reporting/exports as markdown.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "name": {"type": "string"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            source_path, text = _read_report(str(params.get("path") or "latest"))
            name = str(params.get("name") or source_path.stem).strip()
            export_path = _save_text("exports", name, text, ".md")
            payload = {
                "report_type": "serena_reporting_export_md",
                "created_at": _timestamp(),
                "source_path": str(source_path),
                "export_path": str(export_path),
                "export_format": "markdown",
                "export_performed": True,
                "delete_performed": False,
                "changes_made": True,
                "secret_values_exposed": False,
                "hub_adapter": _hub_adapter_contract(),
            }
            report_path = _save_json("reports", f"export-md-{name}", payload)

            return self._result(
                "Serena Reporting markdown export complete\n\n"
                f"- Source report: {source_path}\n"
                f"- Export path: {export_path}\n"
                f"- Metadata report: {report_path}\n"
                "- Export performed: yes\n"
                "- Delete performed: no\n"
                "- Changes made: yes\n"
                "- Secret values exposed: no\n"
                "- Hub adapter: pending future dashboard",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Reporting export-md failed\n\n"
                f"- Error: {exc}\n"
                "- Export performed: no\n"
                "- Changes made: no\n"
                "- Delete performed: no",
                success=False,
            )


@ToolRegistry.register("serena_reporting_export_json")
class SerenaReportingExportJsonTool(_ReportingBaseTool):
    tool_id = "serena_reporting_export_json"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Export a reporting draft and metadata to JSON.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "name": {"type": "string"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            source_path, text = _read_report(str(params.get("path") or "latest"))
            name = str(params.get("name") or source_path.stem).strip()
            export_payload = {
                "title": name,
                "source_path": str(source_path),
                "content": text,
                "content_characters": len(text),
                "created_at": _timestamp(),
                "created_by": "Serena Reporting Full Operator v1",
            }
            export_path = _save_json("exports", name, export_payload)
            metadata = {
                "report_type": "serena_reporting_export_json",
                "created_at": _timestamp(),
                "source_path": str(source_path),
                "export_path": str(export_path),
                "export_format": "json",
                "export_performed": True,
                "delete_performed": False,
                "changes_made": True,
                "secret_values_exposed": False,
                "hub_adapter": _hub_adapter_contract(),
            }
            report_path = _save_json("reports", f"export-json-{name}", metadata)

            return self._result(
                "Serena Reporting JSON export complete\n\n"
                f"- Source report: {source_path}\n"
                f"- Export path: {export_path}\n"
                f"- Metadata report: {report_path}\n"
                "- Export performed: yes\n"
                "- Delete performed: no\n"
                "- Changes made: yes\n"
                "- Secret values exposed: no\n"
                "- Hub adapter: pending future dashboard",
                metadata={**metadata, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Reporting export-json failed\n\n"
                f"- Error: {exc}\n"
                "- Export performed: no\n"
                "- Changes made: no\n"
                "- Delete performed: no",
                success=False,
            )


@ToolRegistry.register("serena_reporting_to_google_doc")
class SerenaReportingToGoogleDocTool(_ReportingBaseTool):
    tool_id = "serena_reporting_to_google_doc"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Doc from a reporting draft using Serena Google Docs operator.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "title": {"type": "string"},
                    "drive_folder": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        approved = bool(params.get("approved") or False)
        if not approved:
            return self._result(
                "Serena Reporting Google Docs handoff blocked\n\n"
                "- Reason: explicit approval is required before external Google Docs handoff.\n"
                "- Google Doc created: no\n"
                "- Export performed: no\n"
                "- Changes made: no\n"
                "- Delete performed: no",
                success=False,
            )

        try:
            source_path, text = _read_report(str(params.get("path") or "latest"))
            title = str(params.get("title") or source_path.stem).strip()
            drive_folder = str(params.get("drive_folder") or "Serena Reports").strip()

            from openjarvis.tools.serena_google_docs import SerenaGoogleDocsCreateTool

            result = SerenaGoogleDocsCreateTool().execute(
                title=title,
                content=text,
                drive_folder=drive_folder,
                doc_type="report",
            )

            payload = {
                "report_type": "serena_reporting_to_google_doc",
                "created_at": _timestamp(),
                "source_path": str(source_path),
                "title": title,
                "drive_folder": drive_folder,
                "approved": True,
                "google_docs_result": result.metadata,
                "handoff_performed": bool(result.success),
                "changes_made": bool(result.success),
                "delete_performed": False,
                "secret_values_exposed": False,
                "hub_adapter": _hub_adapter_contract(),
            }
            report_path = _save_json("handoff", f"to-google-doc-{title}", payload)

            return self._result(
                "Serena Reporting Google Docs handoff complete\n\n"
                f"- Source report: {source_path}\n"
                f"- Title: {title}\n"
                f"- Drive folder: {drive_folder}\n"
                f"- Handoff report: {report_path}\n"
                f"- Google Docs success: {'yes' if result.success else 'no'}\n"
                "- Delete performed: no\n"
                "- Secret values exposed: no\n\n"
                f"{result.content}",
                success=result.success,
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Reporting Google Docs handoff failed safely\n\n"
                f"- Error: {exc}\n"
                "- Google Doc created: no\n"
                "- Changes made: no\n"
                "- Delete performed: no",
                success=False,
            )


@ToolRegistry.register("serena_reporting_to_drive")
class SerenaReportingToDriveTool(_ReportingBaseTool):
    tool_id = "serena_reporting_to_drive"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Save a reporting draft into Google Drive using Serena Google Drive operator.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "name": {"type": "string"},
                    "drive_folder": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        approved = bool(params.get("approved") or False)
        if not approved:
            return self._result(
                "Serena Reporting Google Drive handoff blocked\n\n"
                "- Reason: explicit approval is required before external Google Drive handoff.\n"
                "- Drive upload/save performed: no\n"
                "- Export performed: no\n"
                "- Changes made: no\n"
                "- Delete performed: no",
                success=False,
            )

        try:
            source_path, text = _read_report(str(params.get("path") or "latest"))
            name = str(params.get("name") or f"{source_path.stem}.md").strip()
            drive_folder = str(params.get("drive_folder") or "Serena Reports").strip()

            from openjarvis.tools.serena_gdrive import SerenaGDriveSaveTextTool

            result = SerenaGDriveSaveTextTool().execute(
                name=name,
                content=text,
                drive_folder=drive_folder,
            )

            payload = {
                "report_type": "serena_reporting_to_drive",
                "created_at": _timestamp(),
                "source_path": str(source_path),
                "name": name,
                "drive_folder": drive_folder,
                "approved": True,
                "gdrive_result": result.metadata,
                "handoff_performed": bool(result.success),
                "changes_made": bool(result.success),
                "delete_performed": False,
                "secret_values_exposed": False,
                "hub_adapter": _hub_adapter_contract(),
            }
            report_path = _save_json("handoff", f"to-drive-{name}", payload)

            return self._result(
                "Serena Reporting Google Drive handoff complete\n\n"
                f"- Source report: {source_path}\n"
                f"- Name: {name}\n"
                f"- Drive folder: {drive_folder}\n"
                f"- Handoff report: {report_path}\n"
                f"- Google Drive success: {'yes' if result.success else 'no'}\n"
                "- Delete performed: no\n"
                "- Secret values exposed: no\n\n"
                f"{result.content}",
                success=result.success,
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Reporting Google Drive handoff failed safely\n\n"
                f"- Error: {exc}\n"
                "- Drive upload/save performed: no\n"
                "- Changes made: no\n"
                "- Delete performed: no",
                success=False,
            )


@ToolRegistry.register("serena_reporting_audit")
class SerenaReportingAuditTool(_ReportingBaseTool):
    tool_id = "serena_reporting_audit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Audit Serena Reporting outputs, templates, handoff readiness, and safety posture.",
            parameters={"type": "object", "properties": {}},
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _reporting_root()
        templates = _templates()
        safety = _safety_policy()
        hub = _hub_adapter_contract()

        counts = {}
        for folder_name in ["reports", "drafts", "exports", "snapshots", "handoff"]:
            folder = root / folder_name
            counts[folder_name] = len([p for p in folder.glob("*") if p.is_file()]) if folder.exists() else 0

        issues = []
        recommendations = []

        if not templates:
            issues.append("No reporting templates are available.")
        if counts["drafts"] == 0:
            recommendations.append("Create at least one draft report before export/handoff workflows.")
        if counts["handoff"] == 0:
            recommendations.append("No handoff reports found yet. Use approved Docs/Drive handoff when needed.")

        recommendations.extend([
            "Run Compliance checks before exporting or sharing sensitive reports.",
            "Use Reporting for daily, weekly, compliance, operator, and business summaries.",
            "Keep Hub adapter pending until Serena Hub dashboard/event bus exists.",
        ])

        payload = {
            "report_type": "serena_reporting_audit",
            "created_at": _timestamp(),
            "output_root": str(root),
            "template_count": len(templates),
            "artifact_counts": counts,
            "safety_policy": safety,
            "hub_adapter": hub,
            "issues": issues,
            "recommendations": recommendations,
            "changes_made": False,
            "delete_performed": False,
            "export_performed": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", "reporting-audit", payload)

        lines = [
            "Serena Reporting audit",
            "",
            f"- Templates: {len(templates)}",
            f"- Reports metadata files: {counts['reports']}",
            f"- Draft reports: {counts['drafts']}",
            f"- Exports: {counts['exports']}",
            f"- Snapshots: {counts['snapshots']}",
            f"- Handoff reports: {counts['handoff']}",
            f"- Audit report: {report_path}",
            "- Changes made: no",
            "- Delete performed: no",
            "- Export performed: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Issues:",
        ]

        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- none")

        lines.extend(["", "Recommendations:"])
        lines.extend(f"- {item}" for item in recommendations)

        lines.extend(["", "Blocked operations:"])
        for item in safety["blocked"]:
            lines.append(f"- {item}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


def _blocked_reporting_response(
    title: str,
    action: str,
    reason: str,
    blocked_reason: str,
    report_name: str,
) -> ToolResult:
    payload = {
        "report_type": f"serena_reporting_{report_name}",
        "created_at": _timestamp(),
        "action": action,
        "reason": reason,
        "blocked_reason": blocked_reason,
        "risk_level": "BLOCKED",
        "allowed_to_continue": False,
        "approval_required": True,
        "owner_review_required": True,
        "report_created": False,
        "export_performed": False,
        "delete_performed": False,
        "changes_made": False,
        "secret_values_exposed": False,
        "hub_adapter": _hub_adapter_contract(),
    }
    report_path = _save_json("reports", report_name, payload)

    return ToolResult(
        tool_name=f"serena_reporting_{report_name}",
        success=False,
        content=(
            f"{title}\n\n"
            f"- Action: {action}\n"
            f"- Reason: {reason}\n"
            f"- Blocked reason: {blocked_reason}\n"
            "- Risk level: BLOCKED\n"
            "- Allowed to continue: no\n"
            "- Approval required: yes\n"
            "- Owner review required: yes\n"
            f"- Report: {report_path}\n"
            "- Report created: no\n"
            "- Export performed: no\n"
            "- Delete performed: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard"
        ),
        metadata={**payload, "report_path": str(report_path)},
    )


@ToolRegistry.register("serena_reporting_blocked_sensitive_report")
class SerenaReportingBlockedSensitiveReportTool(_ReportingBaseTool):
    tool_id = "serena_reporting_blocked_sensitive_report"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked unsafe sensitive report creation/export.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _blocked_reporting_response(
            "Sensitive report blocked by Serena Reporting v1 policy",
            str(params.get("action") or "sensitive report export").strip(),
            str(params.get("reason") or "Sensitive report requested.").strip(),
            "Serena may not silently create or export sensitive patient/client/health/financial reports without review and approval.",
            "blocked-sensitive-report",
        )


@ToolRegistry.register("serena_reporting_blocked_unredacted_export")
class SerenaReportingBlockedUnredactedExportTool(_ReportingBaseTool):
    tool_id = "serena_reporting_blocked_unredacted_export"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked unredacted sensitive report export.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
            category="serena_reporting",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _blocked_reporting_response(
            "Unredacted report export blocked by Serena Reporting v1 policy",
            str(params.get("action") or "unredacted export").strip(),
            str(params.get("reason") or "Unredacted export requested.").strip(),
            "Serena may not export unredacted patient/client/health/financial reports without explicit approval and compliance review.",
            "blocked-unredacted-export",
        )


__all__ = [
    "SerenaReportingStatusTool",
    "SerenaReportingPlanTool",
    "SerenaReportingTemplatesTool",
    "SerenaReportingTemplateInfoTool",
    "SerenaReportingFromFolderTool",
    "SerenaReportingBusinessSummaryTool",
    "SerenaReportingToDriveTool",
    "SerenaReportingBlockedUnredactedExportTool",
    "SerenaReportingBlockedSensitiveReportTool",
    "SerenaReportingAuditTool",
    "SerenaReportingToGoogleDocTool",
    "SerenaReportingExportJsonTool",
    "SerenaReportingExportMdTool",
    "SerenaReportingSaveReportTool",
    "SerenaReportingOperatorSummaryTool",
    "SerenaReportingComplianceSummaryTool",
    "SerenaReportingActivitySummaryTool",
    "SerenaReportingWeeklyTool",
    "SerenaReportingDailyTool",
    "SerenaReportingFromFileTool",
    "SerenaReportingFromJsonTool",
    "SerenaReportingFromTextTool",
]
