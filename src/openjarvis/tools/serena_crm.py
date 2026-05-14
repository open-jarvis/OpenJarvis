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

# ---------------------------------------------------------------------------
# Batch 1 CRM reconciliation / future Hub bridge layer
# ---------------------------------------------------------------------------

def _crm_bridge_scan(root: str = "outputs", limit: int = 300) -> list[dict[str, Any]]:
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
                "handoff_signal": "handoff" in raw,
                "contact_signal": any(t in raw for t in ["contact", "customer", "client", "lead", "member", "subscriber"]),
                "membership_signal": any(t in raw for t in ["membership", "member", "subscription", "programme", "program"]),
                "ecommerce_signal": any(t in raw for t in ["ecommerce", "order", "product", "cart", "checkout"]),
                "booking_signal": any(t in raw for t in ["booking", "appointment", "calendar", "follow-up", "followup"]),
                "wordpress_signal": any(t in raw for t in ["wordpress", "page", "funnel", "cta", "lead"]),
                "accounting_signal": any(t in raw for t in ["accounting", "invoice", "payment", "revenue", "receivable"]),
                "lifecycle_signal": any(t in raw for t in ["lifecycle", "renewal", "retention", "cancel", "pause", "enroll"]),
                "safety_signal": any(t in raw for t in ["blocked", "safety", "approval", "sensitive", "patient", "secret"]),
            }
        )
        if len(rows) >= int(limit):
            break

    return rows


def _crm_bridge_artifact(kind: str, title: str, data: dict[str, Any]) -> str:
    out = CRM_OUTPUT_ROOT / kind
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{_timestamp()}-{_safe_slug(title)}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return str(path)


def _crm_bridge_blockers(approved: bool = True, include_sensitive: bool = False, approval_label: str = "Approval") -> list[str]:
    blockers: list[str] = []
    if not approved:
        blockers.append(f"{approval_label} is missing.")
    if include_sensitive:
        blockers.append("Sensitive/unredacted contact, patient, member, customer, or billing data is blocked from this reconciliation layer.")
    return blockers


class _CrmBridgeBaseTool(_CrmBaseTool):
    is_local = True


class SerenaCrmMembershipHandoffSummaryTool(_CrmBridgeBaseTool):
    tool_id = "serena_crm_membership_handoff_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Summarize Membership member/subscription lifecycle artifacts for CRM planning. Local report only.",
            parameters={"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = str(params.get("root") or "outputs/membership").strip()
        limit = int(params.get("limit") or 300)
        items = _crm_bridge_scan(root, limit)
        handoffs = [x for x in items if x["handoff_signal"]]
        contacts = [x for x in items if x["contact_signal"] or x["membership_signal"]]
        lifecycle = [x for x in items if x["lifecycle_signal"]]
        safety = [x for x in items if x["safety_signal"]]

        data = {
            "tool": self.tool_id,
            "operator": "crm",
            "source_operator": "membership",
            "root": root,
            "artifact_count": len(items),
            "handoff_count": len(handoffs),
            "contact_signal_count": len(contacts),
            "lifecycle_signal_count": len(lifecycle),
            "safety_signal_count": len(safety),
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _crm_bridge_artifact("bridge-summaries", "membership", data)
        return self._result(
            "Serena CRM Membership handoff summary created\n\n"
            f"- Root: {root}\n"
            f"- Artifacts summarized: {len(items)}\n"
            f"- Handoffs: {len(handoffs)}\n"
            f"- Contact/member signals: {len(contacts)}\n"
            f"- Lifecycle signals: {len(lifecycle)}\n"
            f"- Summary: {path}\n\n"
            "Actions performed: local report only. Contact/member mutation: no. CRM/Hub write: no. Outbound message: no.",
            metadata=data,
        )


class SerenaCrmEcommerceCustomerSummaryTool(_CrmBridgeBaseTool):
    tool_id = "serena_crm_ecommerce_customer_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Summarize Ecommerce customer/order/contact artifacts for CRM planning. Local report only.",
            parameters={"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = str(params.get("root") or "outputs/ecommerce").strip()
        limit = int(params.get("limit") or 300)
        items = _crm_bridge_scan(root, limit)
        customer_items = [x for x in items if x["contact_signal"] or x["ecommerce_signal"]]
        revenue_items = [x for x in items if x["accounting_signal"]]
        safety = [x for x in items if x["safety_signal"]]

        data = {
            "tool": self.tool_id,
            "operator": "crm",
            "source_operator": "ecommerce",
            "root": root,
            "artifact_count": len(items),
            "customer_signal_count": len(customer_items),
            "revenue_signal_count": len(revenue_items),
            "safety_signal_count": len(safety),
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _crm_bridge_artifact("bridge-summaries", "ecommerce", data)
        return self._result(
            "Serena CRM Ecommerce customer summary created\n\n"
            f"- Root: {root}\n"
            f"- Artifacts summarized: {len(items)}\n"
            f"- Customer/order signals: {len(customer_items)}\n"
            f"- Revenue/accounting signals: {len(revenue_items)}\n"
            f"- Summary: {path}\n\n"
            "Actions performed: local report only. Customer mutation: no. Payment action: no. CRM/Hub write: no.",
            metadata=data,
        )


class SerenaCrmBookingsContactSummaryTool(_CrmBridgeBaseTool):
    tool_id = "serena_crm_bookings_contact_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Summarize Bookings appointment/contact/follow-up artifacts for CRM planning. Local report only.",
            parameters={"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = str(params.get("root") or "outputs/bookings").strip()
        limit = int(params.get("limit") or 300)
        items = _crm_bridge_scan(root, limit)
        booking_items = [x for x in items if x["booking_signal"]]
        contact_items = [x for x in items if x["contact_signal"]]
        safety = [x for x in items if x["safety_signal"]]

        data = {
            "tool": self.tool_id,
            "operator": "crm",
            "source_operator": "bookings",
            "root": root,
            "artifact_count": len(items),
            "booking_signal_count": len(booking_items),
            "contact_signal_count": len(contact_items),
            "safety_signal_count": len(safety),
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _crm_bridge_artifact("bridge-summaries", "bookings", data)
        return self._result(
            "Serena CRM Bookings contact summary created\n\n"
            f"- Root: {root}\n"
            f"- Artifacts summarized: {len(items)}\n"
            f"- Booking signals: {len(booking_items)}\n"
            f"- Contact signals: {len(contact_items)}\n"
            f"- Summary: {path}\n\n"
            "Actions performed: local report only. Booking changed: no. Contact mutation: no. Outbound message: no.",
            metadata=data,
        )


class SerenaCrmWordPressLeadSummaryTool(_CrmBridgeBaseTool):
    tool_id = "serena_crm_wordpress_lead_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Summarize WordPress lead/funnel artifacts for CRM planning. Local report only.",
            parameters={"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = str(params.get("root") or "outputs/wordpress").strip()
        limit = int(params.get("limit") or 300)
        items = _crm_bridge_scan(root, limit)
        wordpress_items = [x for x in items if x["wordpress_signal"]]
        lead_items = [x for x in items if x["contact_signal"]]
        safety = [x for x in items if x["safety_signal"]]

        data = {
            "tool": self.tool_id,
            "operator": "crm",
            "source_operator": "wordpress",
            "root": root,
            "artifact_count": len(items),
            "wordpress_signal_count": len(wordpress_items),
            "lead_signal_count": len(lead_items),
            "safety_signal_count": len(safety),
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _crm_bridge_artifact("bridge-summaries", "wordpress", data)
        return self._result(
            "Serena CRM WordPress lead summary created\n\n"
            f"- Root: {root}\n"
            f"- Artifacts summarized: {len(items)}\n"
            f"- WordPress/funnel signals: {len(wordpress_items)}\n"
            f"- Lead/contact signals: {len(lead_items)}\n"
            f"- Summary: {path}\n\n"
            "Actions performed: local report only. WordPress live update: no. Lead contacted: no. CRM/Hub write: no.",
            metadata=data,
        )


class SerenaCrmAccountingCustomerSummaryTool(_CrmBridgeBaseTool):
    tool_id = "serena_crm_accounting_customer_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Summarize Accounting customer/revenue artifacts for CRM planning. Local report only.",
            parameters={"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = str(params.get("root") or "outputs/accounting").strip()
        limit = int(params.get("limit") or 300)
        items = _crm_bridge_scan(root, limit)
        customer_items = [x for x in items if x["contact_signal"]]
        accounting_items = [x for x in items if x["accounting_signal"]]
        safety = [x for x in items if x["safety_signal"]]

        data = {
            "tool": self.tool_id,
            "operator": "crm",
            "source_operator": "accounting",
            "root": root,
            "artifact_count": len(items),
            "customer_signal_count": len(customer_items),
            "accounting_signal_count": len(accounting_items),
            "safety_signal_count": len(safety),
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _crm_bridge_artifact("bridge-summaries", "accounting", data)
        return self._result(
            "Serena CRM Accounting customer summary created\n\n"
            f"- Root: {root}\n"
            f"- Artifacts summarized: {len(items)}\n"
            f"- Customer signals: {len(customer_items)}\n"
            f"- Accounting/revenue signals: {len(accounting_items)}\n"
            f"- Summary: {path}\n\n"
            "Actions performed: local report only. Accounting write: no. Payment action: no. CRM/Hub write: no.",
            metadata=data,
        )


class SerenaCrmContactLifecyclePlanTool(_CrmBridgeBaseTool):
    tool_id = "serena_crm_contact_lifecycle_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create an approval-gated CRM contact lifecycle plan. Planning only; no contact/customer write.",
            parameters={
                "type": "object",
                "properties": {
                    "programme": {"type": "string"},
                    "focus": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "include_sensitive": {"type": "boolean"},
                },
            },
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        programme = str(params.get("programme") or "CRM contact lifecycle").strip()
        focus = str(params.get("focus") or "lead,prospect,customer,member,retention").strip()
        approved = bool(params.get("approved", False))
        include_sensitive = bool(params.get("include_sensitive", False))
        blockers = _crm_bridge_blockers(approved, include_sensitive, "Contact lifecycle approval")

        data = {
            "tool": self.tool_id,
            "operator": "crm",
            "programme": programme,
            "focus": focus,
            "approved": approved,
            "include_sensitive": include_sensitive,
            "ready": len(blockers) == 0,
            "blockers": blockers,
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _crm_bridge_artifact("lifecycle", programme, data)
        return self._result(
            "Serena CRM contact lifecycle plan created\n\n"
            f"- Programme: {programme}\n"
            f"- Focus: {focus}\n"
            f"- Lifecycle ready: {data['ready']}\n"
            f"- Plan: {path}\n\n"
            "Blockers:\n"
            + "\n".join(f"- {b}" for b in blockers or ["None."])
            + "\n\nActions performed: local lifecycle planning only. Contact/customer/member mutation: no. CRM/Hub write: no.",
            metadata=data,
        )


class SerenaCrmFollowupReadinessPlanTool(_CrmBridgeBaseTool):
    tool_id = "serena_crm_followup_readiness_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create an approval-gated CRM follow-up readiness plan. Planning only; no outbound message.",
            parameters={
                "type": "object",
                "properties": {
                    "audience": {"type": "string"},
                    "channel": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "include_sensitive": {"type": "boolean"},
                },
            },
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        audience = str(params.get("audience") or "CRM contacts").strip()
        channel = str(params.get("channel") or "manual review").strip()
        approved = bool(params.get("approved", False))
        include_sensitive = bool(params.get("include_sensitive", False))
        blockers = _crm_bridge_blockers(approved, include_sensitive, "Follow-up readiness approval")

        data = {
            "tool": self.tool_id,
            "operator": "crm",
            "audience": audience,
            "channel": channel,
            "approved": approved,
            "include_sensitive": include_sensitive,
            "ready": len(blockers) == 0,
            "blockers": blockers,
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _crm_bridge_artifact("plans", audience, data)
        return self._result(
            "Serena CRM follow-up readiness plan created\n\n"
            f"- Audience: {audience}\n"
            f"- Channel: {channel}\n"
            f"- Follow-up ready: {data['ready']}\n"
            f"- Plan: {path}\n\n"
            "Blockers:\n"
            + "\n".join(f"- {b}" for b in blockers or ["None."])
            + "\n\nActions performed: local follow-up planning only. Outbound message/campaign: no. CRM/Hub write: no.",
            metadata=data,
        )


class SerenaCrmBlockedUnapprovedContactWriteTool(_CrmBridgeBaseTool):
    tool_id = "serena_crm_blocked_unapproved_contact_write"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Record a blocked unapproved contact/customer/member write attempt. Local audit only.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reference": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["action"],
            },
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        action = str(params.get("action") or "").strip()
        if not action:
            return self._result("action is required.", success=False)
        reference = str(params.get("reference") or action).strip()
        reason = str(params.get("reason") or "Missing explicit approval for contact/customer write.").strip()
        data = {
            "tool": self.tool_id,
            "operator": "crm",
            "action": action,
            "reference": reference,
            "reason": reason,
            "blocked": True,
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _crm_bridge_artifact("blocked-actions", reference, data)
        return self._result(
            "Serena CRM contact/customer write blocked\n\n"
            f"- Action: {action}\n"
            f"- Reference: {reference}\n"
            f"- Reason: {reason}\n"
            f"- Audit: {path}\n\n"
            "Actions performed: local blocked-action audit only. Contact/customer/member mutation: no. CRM/Hub write: no. Outbound message: no.",
            metadata=data,
        )


class SerenaCrmHubContactPlanTool(_CrmBridgeBaseTool):
    tool_id = "serena_crm_hub_contact_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a future Serena Hub contact metadata plan. Planning only; no Hub/CRM write.",
            parameters={
                "type": "object",
                "properties": {
                    "scope": {"type": "string"},
                    "include_sensitive": {"type": "boolean"},
                },
            },
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        scope = str(params.get("scope") or "crm,membership,ecommerce,bookings,wordpress,accounting").strip()
        include_sensitive = bool(params.get("include_sensitive", False))
        blockers = _crm_bridge_blockers(True, include_sensitive, "Hub contact plan approval")
        data = {
            "tool": self.tool_id,
            "operator": "crm",
            "scope": scope,
            "include_sensitive": include_sensitive,
            "ready": len(blockers) == 0,
            "blockers": blockers,
            "planned_metadata": [
                "membership_lifecycle_signal_count",
                "ecommerce_customer_signal_count",
                "bookings_contact_signal_count",
                "wordpress_lead_signal_count",
                "accounting_customer_signal_count",
                "blocked_contact_write_count",
                "followup_readiness_status",
            ],
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _crm_bridge_artifact("hub-contact-plans", scope, data)
        return self._result(
            "Serena CRM Hub contact plan created\n\n"
            f"- Scope: {scope}\n"
            f"- Hub contact ready: {data['ready']}\n"
            f"- Plan: {path}\n\n"
            "Blockers:\n"
            + "\n".join(f"- {b}" for b in blockers or ["None."])
            + "\n\nActions performed: local Hub metadata planning only. Hub write: no. CRM/contact write: no.",
            metadata=data,
        )


class SerenaCrmDashboardHandoffTool(_CrmBridgeBaseTool):
    tool_id = "serena_crm_dashboard_handoff"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a CRM dashboard handoff for future Serena Hub/Analytics UI. Local artifact only.",
            parameters={
                "type": "object",
                "properties": {
                    "dashboard_name": {"type": "string"},
                    "scope": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
            },
            category="serena_crm",
        )

    def execute(self, **params: Any) -> ToolResult:
        dashboard_name = str(params.get("dashboard_name") or "Serena CRM Dashboard").strip()
        scope = str(params.get("scope") or "crm,membership,ecommerce,bookings,wordpress,accounting").strip()
        approved = bool(params.get("approved", False))
        blockers = _crm_bridge_blockers(approved, False, "Dashboard handoff approval")
        data = {
            "tool": self.tool_id,
            "operator": "crm",
            "dashboard_name": dashboard_name,
            "scope": scope,
            "approved": approved,
            "ready": len(blockers) == 0,
            "blockers": blockers,
            "recommended_widgets": [
                "contact_lifecycle_status",
                "followup_readiness",
                "membership_handoffs",
                "ecommerce_customers",
                "bookings_contacts",
                "wordpress_leads",
                "accounting_customer_signals",
                "blocked_contact_writes",
            ],
            "actions": _actions(),
            "created_at": _timestamp(),
        }
        path = _crm_bridge_artifact("dashboard-handoffs", dashboard_name, data)
        return self._result(
            "Serena CRM dashboard handoff created\n\n"
            f"- Dashboard: {dashboard_name}\n"
            f"- Scope: {scope}\n"
            f"- Dashboard ready: {data['ready']}\n"
            f"- Handoff: {path}\n\n"
            "Blockers:\n"
            + "\n".join(f"- {b}" for b in blockers or ["None."])
            + "\n\nActions performed: local dashboard handoff only. Dashboard created: no. Hub write: no. CRM/contact write: no.",
            metadata=data,
        )


_BATCH1_CRM_TOOLS = [
    SerenaCrmMembershipHandoffSummaryTool,
    SerenaCrmEcommerceCustomerSummaryTool,
    SerenaCrmBookingsContactSummaryTool,
    SerenaCrmWordPressLeadSummaryTool,
    SerenaCrmAccountingCustomerSummaryTool,
    SerenaCrmContactLifecyclePlanTool,
    SerenaCrmFollowupReadinessPlanTool,
    SerenaCrmBlockedUnapprovedContactWriteTool,
    SerenaCrmHubContactPlanTool,
    SerenaCrmDashboardHandoffTool,
]

for _cls in _BATCH1_CRM_TOOLS:
    CRM_TOOL_CLASSES[_cls.tool_id] = _cls
    ToolRegistry.register(_cls.tool_id)(_cls)

