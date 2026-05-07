"""Native Serena CRM / Contacts / Customer Relationship Full Operator tools.

CRM v1 is local-only and approval-gated:
- no live CRM write
- no Hub write
- no contact/customer/member mutation
- no outbound message/campaign
- no payment action
- no WordPress live update
- no accounting write
- no sensitive patient/member/contact export
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


CRM_OUTPUT_ROOT = Path("outputs/crm")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "crm"


def _crm_root() -> Path:
    CRM_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in [
        "reports",
        "plans",
        "contacts",
        "leads",
        "lifecycle",
        "handoff",
        "audits",
        "blocked-actions",
    ]:
        (CRM_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return CRM_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _crm_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _actions() -> dict[str, bool]:
    return {
        "local_report_created": True,
        "contact_created": False,
        "contact_updated": False,
        "customer_updated": False,
        "member_updated": False,
        "outbound_message_sent": False,
        "campaign_sent": False,
        "crm_write_performed": False,
        "hub_write_performed": False,
        "wordpress_live_update": False,
        "accounting_system_write": False,
        "payment_action_performed": False,
        "external_export_performed": False,
        "dashboard_created": False,
        "sensitive_contact_export_performed": False,
        "secret_values_exposed": False,
    }


def _scan_artifacts(root: str = "outputs", limit: int = 300) -> list[dict[str, Any]]:
    base = Path(root)
    if not base.exists():
        return []

    files: list[Path] = []
    for pattern in ("*.json", "*.md", "*.txt", "*.csv", "*.xlsx"):
        files.extend(base.rglob(pattern))

    rows = []
    for item in sorted(files, key=lambda x: str(x).lower()):
        try:
            stat = item.stat()
        except OSError:
            continue

        raw = str(item).lower()
        rows.append(
            {
                "path": str(item),
                "suffix": item.suffix.lower(),
                "size_bytes": stat.st_size,
                "contact_signal": any(t in raw for t in ["contact", "customer", "client", "lead", "member", "subscriber"]),
                "lifecycle_signal": any(t in raw for t in ["lifecycle", "follow-up", "followup", "retention", "renewal", "enroll", "cancel"]),
                "revenue_signal": any(t in raw for t in ["revenue", "payment", "invoice", "order", "subscription"]),
                "booking_signal": any(t in raw for t in ["booking", "appointment", "calendar"]),
                "wordpress_signal": any(t in raw for t in ["wordpress", "page", "funnel", "lead", "cta"]),
                "safety_signal": any(t in raw for t in ["blocked", "safety", "approval", "sensitive", "patient", "secret"]),
                "handoff_signal": "handoff" in raw,
            }
        )
        if len(rows) >= int(limit):
            break
    return rows


class _CrmBaseTool(BaseTool):
    is_local = True

    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=self.tool_id,
            content=content,
            success=success,
            metadata=metadata or {},
        )


class SerenaCrmStatusTool(_CrmBaseTool):
    tool_id = "serena_crm_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena CRM / Contacts / Customer Relationship operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        _crm_root()
        return self._result(
            "Serena CRM status\n\n"
            "- Status: active\n"
            "- Role: local CRM, contacts, leads, lifecycle, follow-up, and customer relationship bridge\n"
            "- Live CRM writes: blocked\n"
            "- Hub writes: blocked pending future Hub layer\n"
            "- Outbound messages/campaigns: blocked without future explicit approval layer\n"
            "- Sensitive patient/member/contact export: blocked\n"
            f"- Output root: {CRM_OUTPUT_ROOT}\n"
            "- Hub adapter: pending future dashboard"
        )


class SerenaCrmEnvCheckTool(_CrmBaseTool):
    tool_id = "serena_crm_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check CRM environment without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        payload = {
            "tool": self.tool_id,
            "operator": "crm",
            "configured_external_crm": False,
            "local_records_ready": True,
            "hub_adapter_status": "pending_future_dashboard",
            "secret_values_exposed": False,
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _save_json("reports", "env-check", payload)
        return self._result(
            "Serena CRM env check\n\n"
            f"- Report: {path}\n"
            "- External CRM configured: no\n"
            "- Local CRM records: ready\n"
            "- Hub adapter: pending future dashboard\n"
            "- Secret values exposed: no\n"
            "- Changes made: no",
            metadata=payload,
        )


class SerenaCrmSourceListTool(_CrmBaseTool):
    tool_id = "serena_crm_source_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List CRM source registries and upstream signal sources.",
            parameters={"type": "object", "properties": {}},
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        sources = [
            "local-crm",
            "membership",
            "ecommerce",
            "bookings",
            "wordpress",
            "accounting",
            "reporting",
            "future-hub",
        ]
        payload = {"sources": sources, "actions": _actions(), "created_at": _timestamp()}
        path = _save_json("reports", "source-list", payload)
        return self._result(
            "Serena CRM sources\n\n"
            + "\n".join(f"- {source}" for source in sources)
            + f"\n\nReport: {path}",
            metadata=payload,
        )


class SerenaCrmSourceInfoTool(_CrmBaseTool):
    tool_id = "serena_crm_source_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show CRM source details.",
            parameters={"type": "object", "properties": {"source": {"type": "string"}}, "required": ["source"]},
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        source = str(params.get("source") or "").strip()
        if not source:
            return self._result("source is required.", success=False)
        payload = {
            "source": source,
            "operator": "crm",
            "status": "local_or_upstream_signal_source",
            "external_write_allowed": False,
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _save_json("reports", f"source-{source}", payload)
        return self._result(
            "Serena CRM source info\n\n"
            f"- Source: {source}\n"
            "- External write allowed: no\n"
            f"- Report: {path}",
            metadata=payload,
        )


def _generic_artifact(
    *,
    tool_id: str,
    title: str,
    kind: str,
    artifact_name: str,
    summary_lines: list[str],
    params: dict[str, Any],
    success: bool = True,
) -> ToolResult:
    payload = {
        "tool": tool_id,
        "operator": "crm",
        "title": title,
        "params": params,
        "actions": _actions(),
        "created_at": _timestamp(),
    }
    path = _save_json(kind, artifact_name, payload)
    content = "\n".join(summary_lines) + f"\n\nArtifact: {path}"
    return ToolResult(tool_name=tool_id, content=content, success=success, metadata=payload)


def _make_tool_class(tool_id: str, description: str, parameters: dict[str, Any], category: str = "serena_crm"):
    class _GeneratedCrmTool(_CrmBaseTool):
        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(
                name=tool_id,
                description=description,
                parameters=parameters,
                category=category,
            )

        def execute(self, **params: Any) -> ToolResult:
            name = (
                params.get("contact_name")
                or params.get("lead_name")
                or params.get("programme")
                or params.get("source")
                or params.get("reference")
                or params.get("goal")
                or params.get("action")
                or tool_id
            )
            include_sensitive = bool(params.get("include_sensitive", False))
            approved = bool(params.get("approved", False))
            blockers: list[str] = []
            if tool_id in {
                "serena_crm_contact_lifecycle_plan",
                "serena_crm_followup_readiness_plan",
                "serena_crm_hub_contact_plan",
                "serena_crm_dashboard_handoff",
            } and not approved and tool_id != "serena_crm_hub_contact_plan":
                blockers.append("Approval is missing.")
            if include_sensitive:
                blockers.append("Sensitive/unredacted contact, patient, member, or customer data is blocked from this layer.")

            kind = "plans"
            if "blocked" in tool_id:
                kind = "blocked-actions"
            elif "handoff" in tool_id:
                kind = "handoff"
            elif "summary" in tool_id or "audit" in tool_id:
                kind = "reports"
            elif "profile" in tool_id:
                kind = "contacts"
            elif "lead" in tool_id:
                kind = "leads"
            elif "lifecycle" in tool_id or "followup" in tool_id or "follow-up" in tool_id:
                kind = "lifecycle"

            lines = [
                f"Serena CRM {description[0].lower() + description[1:]}",
                "",
                f"- Reference: {name}",
                f"- Ready: {len(blockers) == 0}",
            ]
            if blockers:
                lines.append("")
                lines.append("Blockers:")
                lines.extend(f"- {b}" for b in blockers)
            lines.append("")
            lines.append("Actions performed: local CRM artifact only. Contact/customer/member mutation: no. Outbound message: no. CRM/Hub write: no.")

            return _generic_artifact(
                tool_id=tool_id,
                title=description,
                kind=kind,
                artifact_name=str(name),
                summary_lines=lines,
                params={**params, "blockers": blockers, "ready": len(blockers) == 0},
                success=True,
            )

    _GeneratedCrmTool.__name__ = "".join(part.title() for part in tool_id.split("_")) + "Tool"
    _GeneratedCrmTool.tool_id = tool_id
    return _GeneratedCrmTool


TOOL_DEFS: dict[str, tuple[str, dict[str, Any]]] = {
    "serena_crm_plan": (
        "Create a CRM operation plan without external CRM/Hub writes.",
        {"type": "object", "properties": {"goal": {"type": "string"}, "source_scope": {"type": "string"}}, "required": ["goal"]},
    ),
    "serena_crm_contact_profile": (
        "Create a local contact profile draft. Does not write to CRM/Hub.",
        {"type": "object", "properties": {"contact_name": {"type": "string"}, "notes": {"type": "string"}, "approved": {"type": "boolean"}}, "required": ["contact_name"]},
    ),
    "serena_crm_contact_list": (
        "List local CRM contact artifacts.",
        {"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
    ),
    "serena_crm_contact_info": (
        "Create/read a local CRM contact info summary by reference.",
        {"type": "object", "properties": {"reference": {"type": "string"}}, "required": ["reference"]},
    ),
    "serena_crm_contact_summary": (
        "Create a local contact/customer summary.",
        {"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
    ),
    "serena_crm_lead_capture": (
        "Create a local lead capture record. Does not contact the lead.",
        {"type": "object", "properties": {"lead_name": {"type": "string"}, "source": {"type": "string"}, "notes": {"type": "string"}}, "required": ["lead_name"]},
    ),
    "serena_crm_lead_qualification_plan": (
        "Create a local lead qualification plan without outbound contact.",
        {"type": "object", "properties": {"lead_name": {"type": "string"}, "source": {"type": "string"}, "approved": {"type": "boolean"}, "include_sensitive": {"type": "boolean"}}, "required": ["lead_name"]},
    ),
    "serena_crm_follow_up_plan": (
        "Create a local follow-up plan without sending messages.",
        {"type": "object", "properties": {"contact_name": {"type": "string"}, "reason": {"type": "string"}, "approved": {"type": "boolean"}, "include_sensitive": {"type": "boolean"}}, "required": ["contact_name"]},
    ),
    "serena_crm_relationship_summary": (
        "Create a local relationship summary from available notes/signals.",
        {"type": "object", "properties": {"reference": {"type": "string"}, "notes": {"type": "string"}, "include_sensitive": {"type": "boolean"}}, "required": ["reference"]},
    ),
    "serena_crm_customer_lifecycle_plan": (
        "Create a local customer lifecycle plan without mutating records.",
        {"type": "object", "properties": {"programme": {"type": "string"}, "focus": {"type": "string"}, "approved": {"type": "boolean"}, "include_sensitive": {"type": "boolean"}}},
    ),
    "serena_crm_membership_handoff": (
        "Create a local Membership-to-CRM handoff plan.",
        {"type": "object", "properties": {"reference": {"type": "string"}, "notes": {"type": "string"}}},
    ),
    "serena_crm_ecommerce_handoff": (
        "Create a local Ecommerce-to-CRM handoff plan.",
        {"type": "object", "properties": {"reference": {"type": "string"}, "notes": {"type": "string"}}},
    ),
    "serena_crm_bookings_handoff": (
        "Create a local Bookings-to-CRM handoff plan.",
        {"type": "object", "properties": {"reference": {"type": "string"}, "notes": {"type": "string"}}},
    ),
    "serena_crm_wordpress_handoff": (
        "Create a local WordPress-to-CRM handoff plan.",
        {"type": "object", "properties": {"reference": {"type": "string"}, "notes": {"type": "string"}}},
    ),
    "serena_crm_accounting_handoff": (
        "Create a local Accounting-to-CRM handoff plan.",
        {"type": "object", "properties": {"reference": {"type": "string"}, "notes": {"type": "string"}}},
    ),
    "serena_crm_reporting_handoff": (
        "Create a local Reporting-to-CRM handoff plan.",
        {"type": "object", "properties": {"reference": {"type": "string"}, "notes": {"type": "string"}}},
    ),
    "serena_crm_audit": (
        "Audit local CRM artifacts and safety posture.",
        {"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
    ),
    "serena_crm_blocked_bulk_contact_export": (
        "Record a blocked bulk contact export attempt. Local audit only.",
        {"type": "object", "properties": {"reason": {"type": "string"}, "reference": {"type": "string"}}},
    ),
    "serena_crm_blocked_patient_data_exposure": (
        "Record a blocked patient/contact data exposure attempt. Local audit only.",
        {"type": "object", "properties": {"reason": {"type": "string"}, "reference": {"type": "string"}}},
    ),
    "serena_crm_blocked_silent_contact_change": (
        "Record a blocked silent contact change attempt. Local audit only.",
        {"type": "object", "properties": {"reason": {"type": "string"}, "reference": {"type": "string"}}},
    ),
    "serena_crm_blocked_unapproved_message_send": (
        "Record a blocked unapproved message/campaign send attempt. Local audit only.",
        {"type": "object", "properties": {"reason": {"type": "string"}, "reference": {"type": "string"}}},
    ),
    "serena_crm_blocked_unapproved_crm_write": (
        "Record a blocked unapproved CRM/Hub/contact write attempt. Local audit only.",
        {"type": "object", "properties": {"action": {"type": "string"}, "reason": {"type": "string"}, "reference": {"type": "string"}}, "required": ["action"]},
    ),
}


CRM_TOOL_CLASSES: dict[str, type[_CrmBaseTool]] = {
    "serena_crm_status": SerenaCrmStatusTool,
    "serena_crm_env_check": SerenaCrmEnvCheckTool,
    "serena_crm_source_list": SerenaCrmSourceListTool,
    "serena_crm_source_info": SerenaCrmSourceInfoTool,
}

ToolRegistry.register("serena_crm_status")(SerenaCrmStatusTool)
ToolRegistry.register("serena_crm_env_check")(SerenaCrmEnvCheckTool)
ToolRegistry.register("serena_crm_source_list")(SerenaCrmSourceListTool)
ToolRegistry.register("serena_crm_source_info")(SerenaCrmSourceInfoTool)

for _tool_id, (_description, _parameters) in TOOL_DEFS.items():
    _cls = _make_tool_class(_tool_id, _description, _parameters)
    CRM_TOOL_CLASSES[_tool_id] = _cls
    ToolRegistry.register(_tool_id)(_cls)
