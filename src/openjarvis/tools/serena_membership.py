"""Native Serena Membership / Subscriptions / Patient Programmes Full Operator tools.

Layer 1 foundation:
- status
- env-check
- plan
- source-list
- source-info
"""

from __future__ import annotations

from datetime import datetime
import re
import json

import os
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


MEMBERSHIP_OUTPUT_ROOT = Path("outputs/membership")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "membership"


def _membership_root() -> Path:
    MEMBERSHIP_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in [
        "reports",
        "snapshots",
        "plans",
        "members",
        "enrollments",
        "subscriptions",
        "programmes",
        "handoff",
        "audits",
    ]:
        (MEMBERSHIP_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return MEMBERSHIP_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _membership_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _save_text(kind: str, name: str, content: str, suffix: str = ".md") -> Path:
    root = _membership_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}{suffix}"
    path.write_text(content, encoding="utf-8")
    return path


def _hub_adapter_contract() -> dict[str, Any]:
    return {
        "hub_adapter_status": "pending_future_dashboard",
        "future_widgets": [
            "membership_overview_widget",
            "member_profile_widget",
            "subscription_status_widget",
            "programme_progress_widget",
            "renewal_pipeline_widget",
            "membership_payment_widget",
            "membership_approval_widget",
            "membership_exceptions_widget",
        ],
        "future_events": [
            "membership_plan_created",
            "member_profile_created",
            "member_enrolled",
            "membership_status_updated",
            "subscription_record_created",
            "programme_progress_updated",
            "membership_handoff_created",
            "membership_report_created",
            "membership_action_blocked",
        ],
        "operator_state": [
            "current_business_id",
            "current_member_id",
            "current_patient_or_client_id",
            "current_membership_plan_id",
            "current_subscription_id",
            "current_programme_id",
            "current_payment_status",
            "current_required_approval",
            "current_report_path",
        ],
    }


def _safety_policy() -> dict[str, Any]:
    return {
        "allowed": [
            "Create local membership plans.",
            "Create local member profiles.",
            "Create local enrollment records.",
            "Create local subscription records.",
            "Prepare payment/accounting handoff.",
            "Prepare booking handoff.",
            "Create programme progress records.",
            "Create follow-up plans.",
            "Prepare Docs/Drive/Reporting handoff.",
            "Audit membership state.",
            "Report exact changes.",
        ],
        "guarded": [
            "Patient/client data.",
            "Health programme context.",
            "Subscription/payment changes.",
            "Cancellation/pause/renewal workflows.",
            "External exports.",
            "Marketing or reminder use of member data.",
            "Docs/Drive/Reporting handoff.",
            "Accounting/payment handoff.",
        ],
        "blocked": [
            "Bulk membership cancellation.",
            "Silent programme changes.",
            "Unapproved payment amount changes.",
            "Changing subscription price silently.",
            "Exposing patient/client data.",
            "Destructive membership cleanup.",
            "Deleting membership evidence.",
            "Committing credentials.",
            "Final medical, legal, tax, or financial advice.",
        ],
    }


def _membership_sources() -> dict[str, dict[str, Any]]:
    return {
        "local-membership": {
            "name": "Local Serena Membership Records",
            "status": "active_local",
            "role": "Local member profiles, plans, enrollments, subscriptions, programmes, handoffs, reports, and audit evidence.",
            "required_env": [],
            "objects": [
                "membership_plans",
                "member_profiles",
                "enrollments",
                "subscription_records",
                "programme_records",
                "handoff_records",
                "audit_reports",
            ],
            "notes": [
                "Available without external credentials.",
                "This is the v1 membership/programme evidence layer.",
            ],
        },
        "accounting-payments": {
            "name": "Serena Accounting / PayFast / Xero Handoff",
            "status": "active_local_guarded",
            "role": "Invoices, payments, PayFast intake, subscription payment records, Xero readiness, and guarded accounting handoff.",
            "required_env": [],
            "objects": [
                "invoice_plan",
                "payment_record",
                "payfast_payment_record",
                "subscription_payment_context",
                "xero_readiness",
                "payment_summary",
                "blocked_payment_change",
            ],
            "notes": [
                "Payflow is not a standalone skill.",
                "Legacy Payflow concepts are handled here as subscription/payment flow context.",
                "Accounting operator is already complete.",
                "Live PayFast/Xero credentials remain future setup items.",
            ],
        },
        "bookings": {
            "name": "Serena Bookings",
            "status": "active_local",
            "role": "Appointment workflow for programme sessions, member bookings, reminders, no-show risk, and Calendar handoff.",
            "required_env": [],
            "objects": [
                "booking_request",
                "appointment_record",
                "reminder_plan",
                "follow_up_plan",
                "calendar_handoff",
            ],
            "notes": [
                "Bookings operator is already complete.",
                "Calendar writes remain approval-gated through Calendar/Bookings handoff.",
            ],
        },
        "compliance": {
            "name": "Serena Compliance",
            "status": "active_local",
            "role": "Guard patient/client/health/privacy/POPIA/HPCSA-sensitive membership and programme workflows.",
            "required_env": [],
            "objects": [
                "sensitivity_checks",
                "patient_data_guards",
                "external_share_review",
                "marketing_or_reminder_review",
            ],
            "notes": [
                "Run Compliance before external exports or messages containing patient/client/programme data.",
            ],
        },
        "docs-drive": {
            "name": "Google Docs / Google Drive",
            "status": "active_google_ready",
            "role": "Membership summaries, programme documents, consent packs, evidence storage, and handoff exports.",
            "required_env": [
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "GOOGLE_REFRESH_TOKEN",
                "GDRIVE_ROOT_FOLDER_ID",
            ],
            "objects": [
                "member_summary_docs",
                "programme_reports",
                "drive_evidence_files",
                "handoff_documents",
            ],
            "notes": [
                "Docs/Drive handoff must be approval-gated when patient/client/programme data is included.",
            ],
        },
        "reporting": {
            "name": "Serena Reporting",
            "status": "active_local",
            "role": "Membership, subscription, programme progress, renewal, cancellation, and exception reports.",
            "required_env": [],
            "objects": [
                "membership_summary",
                "programme_report",
                "renewal_report",
                "subscription_report",
            ],
            "notes": [
                "Use Reporting for local and shareable operational summaries.",
            ],
        },
        "woocommerce": {
            "name": "WooCommerce / Ecommerce",
            "status": "future_external",
            "role": "Future ecommerce membership purchases, products, orders, subscriptions, revenue, and programme sales.",
            "required_env": [
                "WOOCOMMERCE_URL",
                "WOOCOMMERCE_CONSUMER_KEY",
                "WOOCOMMERCE_CONSUMER_SECRET",
            ],
            "objects": [
                "orders",
                "products",
                "memberships",
                "subscriptions",
                "revenue",
            ],
            "notes": [
                "Future live ecommerce connector.",
                "Do not call WooCommerce APIs in Membership v1.",
                "Ecommerce will be its own later operator and will plug into Membership + Accounting.",
            ],
        },
    }


def _env_status() -> dict[str, Any]:
    sources = _membership_sources()
    env = {}
    for source_id, source in sources.items():
        required = source.get("required_env", [])
        env[source_id] = {
            "required": [
                {
                    "name": name,
                    "present": bool(os.getenv(name)),
                    "length": len(os.getenv(name, "")),
                }
                for name in required
            ],
            "configured": all(bool(os.getenv(name)) for name in required) if required else True,
        }
    return env


class _MembershipBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_membership_status")
class SerenaMembershipStatusTool(_MembershipBaseTool):
    tool_id = "serena_membership_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Membership / Subscriptions / Patient Programmes operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _membership_root()
        sources = _membership_sources()
        env = _env_status()
        configured = [sid for sid, item in env.items() if item.get("configured")]

        return self._result(
            "Serena Membership status\n\n"
            "- Status: active\n"
            "- Role: memberships, subscriptions, patient/client programmes, enrollments, renewals, payment handoff, booking handoff, programme progress, and audit operator\n"
            f"- Sources registered: {len(sources)}\n"
            f"- Configured sources: {len(configured)}\n"
            "- Local membership records: active\n"
            "- Accounting/Payment handoff: active/guarded\n"
            "- Payflow standalone skill: not required\n"
            "- Booking handoff: active/guarded\n"
            "- Docs/Drive handoff: ready/guarded\n"
            "- Compliance guardrails: active\n"
            "- Reporting handoff: active\n"
            "- Bulk membership cancellation: blocked\n"
            "- Silent programme changes: blocked\n"
            "- Unapproved payment changes: blocked\n"
            "- Patient/client data exposure: blocked\n"
            "- Secret values exposed: no\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Plans: {root / 'plans'}\n"
            f"- Members: {root / 'members'}\n"
            f"- Enrollments: {root / 'enrollments'}\n"
            f"- Subscriptions: {root / 'subscriptions'}\n"
            f"- Programmes: {root / 'programmes'}\n"
            f"- Handoff: {root / 'handoff'}\n"
            f"- Audits: {root / 'audits'}\n"
            "- Hub adapter: pending future dashboard",
            metadata={
                "sources": sources,
                "env_status": env,
                "safety_policy": _safety_policy(),
                "hub_adapter": _hub_adapter_contract(),
                "secret_values_exposed": False,
            },
        )


@ToolRegistry.register("serena_membership_env_check")
class SerenaMembershipEnvCheckTool(_MembershipBaseTool):
    tool_id = "serena_membership_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check membership environment without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _env_status()
        payload = {
            "report_type": "serena_membership_env_check",
            "created_at": _timestamp(),
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", "env-check", payload)

        lines = [
            "Serena Membership env check",
            "",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Sources:",
        ]

        for source_id, item in env.items():
            lines.append(f"- {source_id} | configured={'yes' if item['configured'] else 'no'}")
            for var in item["required"]:
                lines.append(f"  - {var['name']} | present={'yes' if var['present'] else 'no'} | length={var['length']}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_membership_source_list")
class SerenaMembershipSourceListTool(_MembershipBaseTool):
    tool_id = "serena_membership_source_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List registered membership/subscription/programme sources.",
            parameters={"type": "object", "properties": {}},
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        sources = _membership_sources()
        payload = {
            "report_type": "serena_membership_source_list",
            "created_at": _timestamp(),
            "sources": sources,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("snapshots", "source-list", payload)

        lines = [
            "Serena Membership source list",
            "",
            f"- Sources registered: {len(sources)}",
            f"- Snapshot: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Sources:",
        ]

        for source_id, source in sources.items():
            lines.append(f"- {source_id} | {source['name']} | status={source['status']} | objects={len(source['objects'])}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_membership_source_info")
class SerenaMembershipSourceInfoTool(_MembershipBaseTool):
    tool_id = "serena_membership_source_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show details for one membership/subscription/programme source.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                },
                "required": ["source"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        source_id = str(params.get("source") or "").strip()
        sources = _membership_sources()

        if source_id not in sources:
            return self._result(
                "Serena Membership source-info failed\n\n"
                f"- Source: {source_id}\n"
                "- Error: source not found\n"
                "- Changes made: no",
                success=False,
            )

        source = sources[source_id]
        env = _env_status().get(source_id, {})
        payload = {
            "report_type": "serena_membership_source_info",
            "created_at": _timestamp(),
            "source_id": source_id,
            "source": source,
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("snapshots", f"source-info-{source_id}", payload)

        lines = [
            "Serena Membership source info",
            "",
            f"- Source: {source_id}",
            f"- Name: {source['name']}",
            f"- Status: {source['status']}",
            f"- Role: {source['role']}",
            f"- Objects: {len(source['objects'])}",
            f"- Required env vars: {len(source['required_env'])}",
            f"- Snapshot: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Objects:",
        ]

        lines.extend(f"- {item}" for item in source["objects"])

        lines.extend(["", "Required env:"])
        if source["required_env"]:
            for item in env.get("required", []):
                lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")
        else:
            lines.append("- none")

        lines.extend(["", "Notes:"])
        lines.extend(f"- {note}" for note in source["notes"])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_membership_plan")
class SerenaMembershipPlanTool(_MembershipBaseTool):
    tool_id = "serena_membership_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a membership/subscription/programme operation plan without external writes.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "business": {"type": "string"},
                    "member": {"type": "string"},
                    "membership_plan": {"type": "string"},
                    "programme": {"type": "string"},
                    "payment_context": {"type": "string"},
                },
                "required": ["goal"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "").strip()
        business = str(params.get("business") or "General Business").strip()
        member = str(params.get("member") or "not specified").strip()
        membership_plan = str(params.get("membership_plan") or "not specified").strip()
        programme = str(params.get("programme") or "not specified").strip()
        payment_context = str(params.get("payment_context") or "not specified").strip()

        steps = [
            "Identify business, member/patient/client, membership plan, programme, and payment context.",
            "Classify whether patient/client/health-sensitive information is included.",
            "Create local membership plan/profile/enrollment/subscription evidence first.",
            "Use Accounting handoff for payments, invoices, PayFast, Xero readiness, and legacy Payflow-style subscription events.",
            "Use Bookings handoff for appointments, reminders, and Calendar workflows.",
            "Use Compliance before external exports/messages involving sensitive member/programme data.",
            "Prepare Docs/Drive/Reporting handoff only after approval when sensitive data is included.",
            "Report exact membership status, payment status, programme state, and required approvals.",
            "Block bulk cancellations, silent programme changes, unapproved payment changes, and patient data exposure.",
        ]

        payload = {
            "report_type": "serena_membership_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "business": business,
            "member": member,
            "membership_plan": membership_plan,
            "programme": programme,
            "payment_context": payment_context,
            "steps": steps,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("plans", goal or "membership-plan", payload)

        return self._result(
            "Serena Membership operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Business: {business}\n"
            f"- Member: {member}\n"
            f"- Membership plan: {membership_plan}\n"
            f"- Programme: {programme}\n"
            f"- Payment context: {payment_context}\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Programme changed: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


def _load_json_records(folder: str) -> list[dict[str, Any]]:
    root = MEMBERSHIP_OUTPUT_ROOT / folder
    if not root.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                data["_path"] = str(path)
                records.append(data)
        except Exception:
            continue
    return records


def _default_membership_plans() -> dict[str, dict[str, Any]]:
    return {
        "basic-care": {
            "plan_id": "basic-care",
            "name": "Basic Care Membership",
            "category": "care",
            "billing_model": "monthly",
            "default_price": 0.0,
            "programme_length": "ongoing",
            "includes": [
                "member profile",
                "basic follow-up planning",
                "booking handoff",
                "reporting handoff",
            ],
            "guardrails": [
                "payment changes require approval",
                "patient/client data is sensitive",
                "external exports require Compliance review",
            ],
        },
        "twelve-week-care": {
            "plan_id": "twelve-week-care",
            "name": "12-Week Care Programme",
            "category": "patient programme",
            "billing_model": "monthly subscription or once-off package",
            "default_price": 0.0,
            "programme_length": "12 weeks",
            "includes": [
                "programme enrollment",
                "progress tracking",
                "appointment/booking handoff",
                "follow-up planning",
                "reporting handoff",
            ],
            "guardrails": [
                "medical advice remains outside Membership v1",
                "payment changes require Accounting handoff and approval",
                "programme changes require visible audit trail",
            ],
        },
        "corporate-wellness": {
            "plan_id": "corporate-wellness",
            "name": "Corporate Wellness Programme",
            "category": "business programme",
            "billing_model": "package or subscription",
            "default_price": 0.0,
            "programme_length": "custom",
            "includes": [
                "member/group profile",
                "programme planning",
                "reporting handoff",
                "booking handoff",
            ],
            "guardrails": [
                "health data must be protected",
                "external reporting requires Compliance review",
                "bulk member actions remain guarded",
            ],
        },
    }



def _find_member_profile(member_id: str) -> dict[str, Any] | None:
    records = _load_json_records("members")
    profiles = [
        r for r in records
        if str(r.get("member_id") or "") == member_id
        and str(r.get("record_type") or "") == "member_profile"
    ]
    if profiles:
        return profiles[0]
    return next((r for r in records if str(r.get("member_id") or "") == member_id), None)

def _member_summary_line(record: dict[str, Any]) -> str:
    return (
        f"{record.get('member_id')} | "
        f"{record.get('member_name', 'unknown')} | "
        f"{record.get('membership_plan', 'no plan')} | "
        f"status={record.get('status', 'unknown')} | "
        f"payment={record.get('payment_status', 'unknown')}"
    )


@ToolRegistry.register("serena_membership_plan_list")
class SerenaMembershipPlanListTool(_MembershipBaseTool):
    tool_id = "serena_membership_plan_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List available local membership/programme plan templates.",
            parameters={"type": "object", "properties": {}},
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        plans = _default_membership_plans()
        payload = {
            "report_type": "serena_membership_plan_list",
            "created_at": _timestamp(),
            "plans": plans,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("snapshots", "membership-plan-list", payload)

        lines = [
            "Serena Membership plan list",
            "",
            f"- Plans available: {len(plans)}",
            f"- Snapshot: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Plans:",
        ]

        for plan_id, plan in plans.items():
            lines.append(f"- {plan_id} | {plan['name']} | {plan['billing_model']} | length={plan['programme_length']}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_membership_plan_info")
class SerenaMembershipPlanInfoTool(_MembershipBaseTool):
    tool_id = "serena_membership_plan_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show details for one local membership/programme plan template.",
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                },
                "required": ["plan_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        plan_id = str(params.get("plan_id") or "").strip()
        plans = _default_membership_plans()

        if plan_id not in plans:
            return self._result(
                "Serena Membership plan-info failed\n\n"
                f"- Plan ID: {plan_id}\n"
                "- Error: plan not found\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        plan = plans[plan_id]
        payload = {
            "report_type": "serena_membership_plan_info",
            "created_at": _timestamp(),
            "plan": plan,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("snapshots", f"membership-plan-info-{plan_id}", payload)

        lines = [
            "Serena Membership plan info",
            "",
            f"- Plan ID: {plan['plan_id']}",
            f"- Name: {plan['name']}",
            f"- Category: {plan['category']}",
            f"- Billing model: {plan['billing_model']}",
            f"- Default price: {plan['default_price']}",
            f"- Programme length: {plan['programme_length']}",
            f"- Snapshot: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Includes:",
        ]

        lines.extend(f"- {item}" for item in plan["includes"])
        lines.extend(["", "Guardrails:"])
        lines.extend(f"- {item}" for item in plan["guardrails"])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_membership_create_member_profile")
class SerenaMembershipCreateMemberProfileTool(_MembershipBaseTool):
    tool_id = "serena_membership_create_member_profile"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local member/patient/client profile for membership/programme workflows.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "business": {"type": "string"},
                    "member_name": {"type": "string"},
                    "contact": {"type": "string"},
                    "membership_plan": {"type": "string"},
                    "programme": {"type": "string"},
                    "payment_status": {"type": "string"},
                    "status": {"type": "string"},
                    "notes": {"type": "string"},
                    "sensitive": {"type": "boolean"},
                },
                "required": ["member_name"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or f"MEM-{_timestamp()}").strip()
        business = str(params.get("business") or "General Business").strip()
        member_name = str(params.get("member_name") or "").strip()
        contact = str(params.get("contact") or "").strip()
        membership_plan = str(params.get("membership_plan") or "not assigned").strip()
        programme = str(params.get("programme") or "not assigned").strip()
        payment_status = str(params.get("payment_status") or "not started").strip()
        status = str(params.get("status") or "profile_created").strip()
        notes = str(params.get("notes") or "").strip()
        sensitive = bool(params.get("sensitive") or False)

        record = {
            "record_type": "member_profile",
            "created_at": _timestamp(),
            "member_id": member_id,
            "business": business,
            "member_name": member_name,
            "contact": contact,
            "membership_plan": membership_plan,
            "programme": programme,
            "payment_status": payment_status,
            "status": status,
            "notes": notes,
            "sensitive": sensitive,
            "member_profile_created": True,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": False,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("members", f"member-{member_id}", record)

        return self._result(
            "Serena member profile created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Business: {business}\n"
            f"- Member: {member_name}\n"
            f"- Membership plan: {membership_plan}\n"
            f"- Programme: {programme}\n"
            f"- Payment status: {payment_status}\n"
            f"- Status: {status}\n"
            f"- Sensitive: {'yes' if sensitive else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Member profile created: yes\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Programme changed: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_member_info")
class SerenaMembershipMemberInfoTool(_MembershipBaseTool):
    tool_id = "serena_membership_member_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show local member profile details by member ID.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        match = _find_member_profile(member_id)

        if not match:
            return self._result(
                "Serena member info failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        return self._result(
            "Serena member info\n\n"
            f"- Member ID: {match.get('member_id')}\n"
            f"- Business: {match.get('business')}\n"
            f"- Member: {match.get('member_name')}\n"
            f"- Membership plan: {match.get('membership_plan')}\n"
            f"- Programme: {match.get('programme')}\n"
            f"- Payment status: {match.get('payment_status')}\n"
            f"- Status: {match.get('status')}\n"
            f"- Sensitive: {'yes' if match.get('sensitive') else 'no'}\n"
            f"- Record: {match.get('_path')}\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata=match,
        )


@ToolRegistry.register("serena_membership_member_list")
class SerenaMembershipMemberListTool(_MembershipBaseTool):
    tool_id = "serena_membership_member_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List local member profiles.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "").strip()
        status_filter = str(params.get("status") or "").strip()
        limit = int(params.get("limit") or 20)

        records = _load_json_records("members")
        selected = []

        for record in records:
            if business and str(record.get("business") or "") != business:
                continue
            if status_filter and str(record.get("status") or "") != status_filter:
                continue
            selected.append(record)

        payload = {
            "report_type": "serena_membership_member_list",
            "created_at": _timestamp(),
            "business": business or "all",
            "status_filter": status_filter or "all",
            "member_count": len(selected),
            "member_paths": [item.get("_path") for item in selected],
            "external_api_called": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"member-list-{business or 'all'}", payload)

        lines = [
            "Serena member list",
            "",
            f"- Business: {business or 'all'}",
            f"- Status filter: {status_filter or 'all'}",
            f"- Members found: {len(selected)}",
            f"- Report: {report_path}",
            "- External API called: no",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Members:",
        ]

        if selected:
            for record in selected[:limit]:
                lines.append(f"- {_member_summary_line(record)}")
        else:
            lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_membership_update_member_status")
class SerenaMembershipUpdateMemberStatusTool(_MembershipBaseTool):
    tool_id = "serena_membership_update_member_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local member status update record. Does not overwrite/delete original profile.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "new_status": {"type": "string"},
                    "reason": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["member_id", "new_status"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        new_status = str(params.get("new_status") or "").strip()
        reason = str(params.get("reason") or "Status update requested.").strip()
        approved = bool(params.get("approved") or False)

        match = _find_member_profile(member_id)

        if not match:
            return self._result(
                "Serena member status update failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        guarded_statuses = {"cancelled", "paused", "payment_changed", "programme_changed"}
        if new_status.lower() in guarded_statuses and not approved:
            return self._result(
                "Serena member status update blocked\n\n"
                f"- Member ID: {member_id}\n"
                f"- Requested status: {new_status}\n"
                "- Reason: guarded status changes require approval.\n"
                "- Status update created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        record = {
            "record_type": "member_status_update",
            "created_at": _timestamp(),
            "member_id": member_id,
            "business": match.get("business"),
            "member_name": match.get("member_name"),
            "old_status": match.get("status"),
            "new_status": new_status,
            "reason": reason,
            "approved": approved,
            "sensitive": bool(match.get("sensitive")),
            "status_update_created": True,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": new_status.lower() == "programme_changed",
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("members", f"member-status-update-{member_id}", record)

        return self._result(
            "Serena member status update created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {match.get('member_name')}\n"
            f"- Old status: {match.get('status')}\n"
            f"- New status: {new_status}\n"
            f"- Reason: {reason}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Status update created: yes\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_enrollment_plan")
class SerenaMembershipEnrollmentPlanTool(_MembershipBaseTool):
    tool_id = "serena_membership_enrollment_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local membership/programme enrollment plan without external writes.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "programme": {"type": "string"},
                    "payment_model": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        plan_id = str(params.get("plan_id") or "not specified").strip()
        programme = str(params.get("programme") or "not specified").strip()
        payment_model = str(params.get("payment_model") or "not specified").strip()
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena enrollment plan failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Enrollment planned: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Confirm member profile and consent context.",
            "Confirm membership plan/programme scope.",
            "Confirm payment model and whether Accounting handoff is needed.",
            "Confirm whether Bookings handoff is needed for programme sessions.",
            "Check sensitive data handling before external handoff.",
            "Create local enrollment record only after details are confirmed.",
            "Do not perform payment, accounting, booking, or external writes from this command.",
        ]

        payload = {
            "report_type": "serena_membership_enrollment_plan",
            "created_at": _timestamp(),
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "plan_id": plan_id,
            "programme": programme,
            "payment_model": payment_model,
            "notes": notes,
            "steps": steps,
            "sensitive": bool(member.get("sensitive")),
            "enrollment_planned": True,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("enrollments", f"enrollment-plan-{member_id}-{plan_id}", payload)

        return self._result(
            "Serena enrollment plan created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Plan ID: {plan_id}\n"
            f"- Programme: {programme}\n"
            f"- Payment model: {payment_model}\n"
            f"- Sensitive: {'yes' if member.get('sensitive') else 'no'}\n"
            f"- Plan: {report_path}\n"
            "- Enrollment planned: yes\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Programme changed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_membership_enroll_member")
class SerenaMembershipEnrollMemberTool(_MembershipBaseTool):
    tool_id = "serena_membership_enroll_member"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local member enrollment record. Does not perform payment/accounting/booking writes.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "programme": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "payment_model": {"type": "string"},
                    "payment_status": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id", "plan_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        plan_id = str(params.get("plan_id") or "").strip()
        programme = str(params.get("programme") or "not specified").strip()
        start_date = str(params.get("start_date") or "not specified").strip()
        end_date = str(params.get("end_date") or "not specified").strip()
        payment_model = str(params.get("payment_model") or "not specified").strip()
        payment_status = str(params.get("payment_status") or "pending").strip()
        approved = bool(params.get("approved") or False)
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena member enrollment failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Enrollment created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if bool(member.get("sensitive")) and not approved:
            return self._result(
                "Serena member enrollment blocked\n\n"
                f"- Member ID: {member_id}\n"
                "- Reason: sensitive member/programme enrollment requires approval.\n"
                "- Enrollment created: no\n"
                "- External API called: no\n"
                "- Payment action performed: no\n"
                "- Accounting write performed: no\n"
                "- Booking write performed: no\n"
                "- Programme changed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        record = {
            "record_type": "membership_enrollment",
            "created_at": _timestamp(),
            "enrollment_id": f"ENR-{_timestamp()}",
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "plan_id": plan_id,
            "programme": programme,
            "start_date": start_date,
            "end_date": end_date,
            "payment_model": payment_model,
            "payment_status": payment_status,
            "approved": approved,
            "notes": notes,
            "sensitive": bool(member.get("sensitive")),
            "enrollment_created": True,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": True,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("enrollments", f"enrollment-{member_id}-{plan_id}", record)

        return self._result(
            "Serena member enrollment created\n\n"
            f"- Enrollment ID: {record['enrollment_id']}\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Plan ID: {plan_id}\n"
            f"- Programme: {programme}\n"
            f"- Start date: {start_date}\n"
            f"- End date: {end_date}\n"
            f"- Payment model: {payment_model}\n"
            f"- Payment status: {payment_status}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Sensitive: {'yes' if member.get('sensitive') else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Enrollment created: yes\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Programme changed: yes\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_cancel_membership_plan")
class SerenaMembershipCancelMembershipPlanTool(_MembershipBaseTool):
    tool_id = "serena_membership_cancel_membership_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local membership cancellation plan. Does not cancel subscriptions or payments.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "effective_date": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        reason = str(params.get("reason") or "Cancellation requested.").strip()
        effective_date = str(params.get("effective_date") or "not specified").strip()
        approved = bool(params.get("approved") or False)

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena membership cancellation plan failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Cancellation planned: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if not approved:
            return self._result(
                "Serena membership cancellation blocked\n\n"
                f"- Member ID: {member_id}\n"
                f"- Reason: {reason}\n"
                "- Blocked reason: membership cancellation requires explicit approval.\n"
                "- Cancellation planned: no\n"
                "- Payment action performed: no\n"
                "- Accounting write performed: no\n"
                "- Programme changed: no\n"
                "- Delete performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Confirm exact member and plan.",
            "Confirm effective cancellation date.",
            "Check payment/subscription implications through Accounting handoff.",
            "Check booking/session implications through Bookings handoff.",
            "Preserve member/enrollment/subscription evidence.",
            "Do not cancel live payment/subscription from Membership v1.",
        ]

        payload = {
            "report_type": "serena_membership_cancel_membership_plan",
            "created_at": _timestamp(),
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "membership_plan": member.get("membership_plan"),
            "programme": member.get("programme"),
            "reason": reason,
            "effective_date": effective_date,
            "approved": approved,
            "steps": steps,
            "cancellation_planned": True,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "subscription_cancelled": False,
            "membership_cancelled": False,
            "programme_changed": False,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("plans", f"cancel-membership-{member_id}", payload)

        return self._result(
            "Serena membership cancellation plan created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Effective date: {effective_date}\n"
            f"- Reason: {reason}\n"
            f"- Approved: yes\n"
            f"- Plan: {report_path}\n"
            "- Cancellation planned: yes\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Subscription cancelled: no\n"
            "- Membership cancelled: no\n"
            "- Programme changed: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_membership_pause_membership_plan")
class SerenaMembershipPauseMembershipPlanTool(_MembershipBaseTool):
    tool_id = "serena_membership_pause_membership_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local membership pause plan. Does not pause live subscriptions or payments.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "pause_start": {"type": "string"},
                    "pause_end": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        reason = str(params.get("reason") or "Pause requested.").strip()
        pause_start = str(params.get("pause_start") or "not specified").strip()
        pause_end = str(params.get("pause_end") or "not specified").strip()
        approved = bool(params.get("approved") or False)

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena membership pause plan failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Pause planned: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if not approved:
            return self._result(
                "Serena membership pause blocked\n\n"
                f"- Member ID: {member_id}\n"
                f"- Reason: {reason}\n"
                "- Blocked reason: membership pause requires explicit approval.\n"
                "- Pause planned: no\n"
                "- Payment action performed: no\n"
                "- Accounting write performed: no\n"
                "- Programme changed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Confirm exact member and programme.",
            "Confirm pause period.",
            "Check subscription/payment impact through Accounting handoff.",
            "Check appointment/session impact through Bookings handoff.",
            "Create restart/follow-up reminder plan.",
            "Do not pause live payment/subscription from Membership v1.",
        ]

        payload = {
            "report_type": "serena_membership_pause_membership_plan",
            "created_at": _timestamp(),
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "reason": reason,
            "pause_start": pause_start,
            "pause_end": pause_end,
            "approved": approved,
            "steps": steps,
            "pause_planned": True,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "subscription_paused": False,
            "membership_paused": False,
            "programme_changed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("plans", f"pause-membership-{member_id}", payload)

        return self._result(
            "Serena membership pause plan created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Pause start: {pause_start}\n"
            f"- Pause end: {pause_end}\n"
            f"- Reason: {reason}\n"
            f"- Approved: yes\n"
            f"- Plan: {report_path}\n"
            "- Pause planned: yes\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Subscription paused: no\n"
            "- Membership paused: no\n"
            "- Programme changed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_membership_renewal_plan")
class SerenaMembershipRenewalPlanTool(_MembershipBaseTool):
    tool_id = "serena_membership_renewal_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local membership/programme renewal plan.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "renewal_date": {"type": "string"},
                    "next_plan_id": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        renewal_date = str(params.get("renewal_date") or "not specified").strip()
        next_plan_id = str(params.get("next_plan_id") or "same/current plan").strip()
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena renewal plan failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Renewal planned: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Review current membership/programme state.",
            "Review payment/subscription status via Accounting handoff.",
            "Review programme progress and outcomes.",
            "Confirm renewal date and next plan.",
            "Prepare member follow-up plan if needed.",
            "Do not change price/payment/subscription silently.",
        ]

        payload = {
            "report_type": "serena_membership_renewal_plan",
            "created_at": _timestamp(),
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "current_plan": member.get("membership_plan"),
            "current_programme": member.get("programme"),
            "renewal_date": renewal_date,
            "next_plan_id": next_plan_id,
            "notes": notes,
            "steps": steps,
            "renewal_planned": True,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("plans", f"renewal-plan-{member_id}", payload)

        return self._result(
            "Serena renewal plan created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Current plan: {member.get('membership_plan')}\n"
            f"- Renewal date: {renewal_date}\n"
            f"- Next plan: {next_plan_id}\n"
            f"- Plan: {report_path}\n"
            "- Renewal planned: yes\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Programme changed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


def _money(value: Any) -> float:
    try:
        return round(float(str(value).replace("R", "").replace(",", "").strip() or 0), 2)
    except Exception:
        return 0.0


@ToolRegistry.register("serena_membership_subscription_plan")
class SerenaMembershipSubscriptionPlanTool(_MembershipBaseTool):
    tool_id = "serena_membership_subscription_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local subscription/payment plan for a member. Does not create live subscriptions.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "billing_model": {"type": "string"},
                    "amount": {"type": "number"},
                    "currency": {"type": "string"},
                    "interval": {"type": "string"},
                    "start_date": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        billing_model = str(params.get("billing_model") or "monthly subscription").strip()
        amount = _money(params.get("amount") or 0)
        currency = str(params.get("currency") or "ZAR").strip()
        interval = str(params.get("interval") or "monthly").strip()
        start_date = str(params.get("start_date") or "not specified").strip()
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena subscription plan failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Subscription planned: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Confirm member, membership plan, programme, billing model, interval, and amount.",
            "Confirm whether PayFast payment link or subscription event is needed through Accounting handoff.",
            "Confirm whether Xero invoice/contact setup is needed through Accounting handoff.",
            "Do not create live subscriptions from Membership v1.",
            "Do not change price/payment terms without approval.",
            "Preserve subscription plan evidence.",
        ]

        payload = {
            "report_type": "serena_membership_subscription_plan",
            "created_at": _timestamp(),
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "membership_plan": member.get("membership_plan"),
            "programme": member.get("programme"),
            "billing_model": billing_model,
            "amount": amount,
            "currency": currency,
            "interval": interval,
            "start_date": start_date,
            "notes": notes,
            "steps": steps,
            "subscription_planned": True,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "subscription_created_live": False,
            "price_changed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("subscriptions", f"subscription-plan-{member_id}", payload)

        return self._result(
            "Serena subscription plan created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Billing model: {billing_model}\n"
            f"- Amount: {amount} {currency}\n"
            f"- Interval: {interval}\n"
            f"- Start date: {start_date}\n"
            f"- Plan: {report_path}\n"
            "- Subscription planned: yes\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Live subscription created: no\n"
            "- Price changed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_membership_subscription_record")
class SerenaMembershipSubscriptionRecordTool(_MembershipBaseTool):
    tool_id = "serena_membership_subscription_record"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local subscription record. Does not create live PayFast/Xero subscription.",
            parameters={
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string"},
                    "member_id": {"type": "string"},
                    "billing_model": {"type": "string"},
                    "amount": {"type": "number"},
                    "currency": {"type": "string"},
                    "interval": {"type": "string"},
                    "status": {"type": "string"},
                    "payment_reference": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        subscription_id = str(params.get("subscription_id") or f"SUB-{_timestamp()}").strip()
        member_id = str(params.get("member_id") or "").strip()
        billing_model = str(params.get("billing_model") or "monthly subscription").strip()
        amount = _money(params.get("amount") or 0)
        currency = str(params.get("currency") or "ZAR").strip()
        interval = str(params.get("interval") or "monthly").strip()
        status = str(params.get("status") or "local_pending").strip()
        payment_reference = str(params.get("payment_reference") or "").strip()
        approved = bool(params.get("approved") or False)
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena subscription record failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Subscription record created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if amount > 0 and not approved:
            return self._result(
                "Serena subscription record blocked\n\n"
                f"- Member ID: {member_id}\n"
                f"- Amount: {amount} {currency}\n"
                "- Reason: subscription/payment amount records require approval.\n"
                "- Subscription record created: no\n"
                "- Payment action performed: no\n"
                "- Accounting write performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        record = {
            "record_type": "subscription_record",
            "created_at": _timestamp(),
            "subscription_id": subscription_id,
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "membership_plan": member.get("membership_plan"),
            "programme": member.get("programme"),
            "billing_model": billing_model,
            "amount": amount,
            "currency": currency,
            "interval": interval,
            "status": status,
            "payment_reference": payment_reference,
            "approved": approved,
            "notes": notes,
            "subscription_record_created": True,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "live_subscription_created": False,
            "price_changed": False,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("subscriptions", f"subscription-record-{subscription_id}", record)

        return self._result(
            "Serena subscription record created\n\n"
            f"- Subscription ID: {subscription_id}\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Billing model: {billing_model}\n"
            f"- Amount: {amount} {currency}\n"
            f"- Interval: {interval}\n"
            f"- Status: {status}\n"
            f"- Payment reference: {payment_reference or 'not linked'}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Subscription record created: yes\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Live subscription created: no\n"
            "- Price changed: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_payment_handoff")
class SerenaMembershipPaymentHandoffTool(_MembershipBaseTool):
    tool_id = "serena_membership_payment_handoff"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create Accounting/PayFast payment handoff for a member/subscription. Does not perform payment actions.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "amount": {"type": "number"},
                    "currency": {"type": "string"},
                    "payment_reason": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        amount = _money(params.get("amount") or 0)
        currency = str(params.get("currency") or "ZAR").strip()
        payment_reason = str(params.get("payment_reason") or "membership/subscription payment").strip()
        approved = bool(params.get("approved") or False)
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena payment handoff failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Handoff created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if amount > 0 and not approved:
            return self._result(
                "Serena payment handoff blocked\n\n"
                f"- Member ID: {member_id}\n"
                f"- Amount: {amount} {currency}\n"
                "- Reason: payment handoff with amount requires approval.\n"
                "- Handoff created: no\n"
                "- Payment action performed: no\n"
                "- Accounting write performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        payload = {
            "record_type": "payment_handoff",
            "created_at": _timestamp(),
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "membership_plan": member.get("membership_plan"),
            "programme": member.get("programme"),
            "amount": amount,
            "currency": currency,
            "payment_reason": payment_reason,
            "approved": approved,
            "notes": notes,
            "target_operator": "serena_accounting",
            "handoff_created": True,
            "external_api_called": False,
            "payment_action_performed": False,
            "payfast_action_performed": False,
            "accounting_write_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("handoff", f"payment-handoff-{member_id}", payload)

        return self._result(
            "Serena payment handoff created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Amount: {amount} {currency}\n"
            f"- Payment reason: {payment_reason}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Target operator: serena_accounting\n"
            f"- Record: {record_path}\n"
            "- Handoff created: yes\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- PayFast action performed: no\n"
            "- Accounting write performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**payload, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_accounting_handoff")
class SerenaMembershipAccountingHandoffTool(_MembershipBaseTool):
    tool_id = "serena_membership_accounting_handoff"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create Accounting handoff for membership invoices/payments/subscription records. Does not write accounting records.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "handoff_type": {"type": "string"},
                    "amount": {"type": "number"},
                    "approved": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        handoff_type = str(params.get("handoff_type") or "invoice/payment/subscription handoff").strip()
        amount = _money(params.get("amount") or 0)
        approved = bool(params.get("approved") or False)
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena accounting handoff failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Handoff created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if amount > 0 and not approved:
            return self._result(
                "Serena accounting handoff blocked\n\n"
                f"- Member ID: {member_id}\n"
                f"- Amount: {amount}\n"
                "- Reason: accounting handoff with amount requires approval.\n"
                "- Handoff created: no\n"
                "- Accounting write performed: no\n"
                "- Payment action performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        payload = {
            "record_type": "accounting_handoff",
            "created_at": _timestamp(),
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "membership_plan": member.get("membership_plan"),
            "programme": member.get("programme"),
            "handoff_type": handoff_type,
            "amount": amount,
            "approved": approved,
            "notes": notes,
            "target_operator": "serena_accounting",
            "handoff_created": True,
            "external_api_called": False,
            "accounting_write_performed": False,
            "payment_action_performed": False,
            "xero_write_performed": False,
            "payfast_action_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("handoff", f"accounting-handoff-{member_id}", payload)

        return self._result(
            "Serena accounting handoff created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Handoff type: {handoff_type}\n"
            f"- Amount: {amount}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Target operator: serena_accounting\n"
            f"- Record: {record_path}\n"
            "- Handoff created: yes\n"
            "- External API called: no\n"
            "- Accounting write performed: no\n"
            "- Payment action performed: no\n"
            "- Xero write performed: no\n"
            "- PayFast action performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**payload, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_booking_handoff")
class SerenaMembershipBookingHandoffTool(_MembershipBaseTool):
    tool_id = "serena_membership_booking_handoff"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create Bookings handoff for membership/programme appointments. Does not create bookings/calendar events.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "appointment_type": {"type": "string"},
                    "preferred_date": {"type": "string"},
                    "preferred_time": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        appointment_type = str(params.get("appointment_type") or "programme appointment").strip()
        preferred_date = str(params.get("preferred_date") or "not specified").strip()
        preferred_time = str(params.get("preferred_time") or "not specified").strip()
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena booking handoff failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Handoff created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        payload = {
            "record_type": "booking_handoff",
            "created_at": _timestamp(),
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "membership_plan": member.get("membership_plan"),
            "programme": member.get("programme"),
            "appointment_type": appointment_type,
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
            "notes": notes,
            "target_operator": "serena_bookings",
            "handoff_created": True,
            "external_api_called": False,
            "booking_write_performed": False,
            "calendar_write_performed": False,
            "reminder_sent": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("handoff", f"booking-handoff-{member_id}", payload)

        return self._result(
            "Serena booking handoff created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Appointment type: {appointment_type}\n"
            f"- Preferred date: {preferred_date}\n"
            f"- Preferred time: {preferred_time}\n"
            f"- Target operator: serena_bookings\n"
            f"- Record: {record_path}\n"
            "- Handoff created: yes\n"
            "- External API called: no\n"
            "- Booking write performed: no\n"
            "- Calendar write performed: no\n"
            "- Reminder sent: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**payload, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_programme_plan")
class SerenaMembershipProgrammePlanTool(_MembershipBaseTool):
    tool_id = "serena_membership_programme_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local patient/client programme plan. Does not provide medical advice or change live systems.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "programme_id": {"type": "string"},
                    "programme_name": {"type": "string"},
                    "duration": {"type": "string"},
                    "goals": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        programme_id = str(params.get("programme_id") or f"PROG-{_timestamp()}").strip()
        programme_name = str(params.get("programme_name") or "member programme").strip()
        duration = str(params.get("duration") or "not specified").strip()
        goals = str(params.get("goals") or "").strip()
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena programme plan failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Programme planned: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Confirm member profile and consent context.",
            "Define programme scope, duration, non-clinical goals, and operational milestones.",
            "Keep clinical/medical advice outside Membership v1.",
            "Use Bookings handoff for programme sessions.",
            "Use Accounting handoff for programme payments/subscriptions.",
            "Use Compliance before external reporting or messaging.",
            "Track progress locally with auditable records.",
        ]

        payload = {
            "report_type": "serena_membership_programme_plan",
            "created_at": _timestamp(),
            "programme_id": programme_id,
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "programme_name": programme_name,
            "duration": duration,
            "goals": goals,
            "notes": notes,
            "steps": steps,
            "sensitive": bool(member.get("sensitive")),
            "programme_planned": True,
            "medical_advice_given": False,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("programmes", f"programme-plan-{member_id}-{programme_id}", payload)

        return self._result(
            "Serena programme plan created\n\n"
            f"- Programme ID: {programme_id}\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Programme: {programme_name}\n"
            f"- Duration: {duration}\n"
            f"- Sensitive: {'yes' if member.get('sensitive') else 'no'}\n"
            f"- Plan: {report_path}\n"
            "- Programme planned: yes\n"
            "- Medical advice given: no\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Programme changed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_membership_programme_enroll")
class SerenaMembershipProgrammeEnrollTool(_MembershipBaseTool):
    tool_id = "serena_membership_programme_enroll"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local programme enrollment record. Does not perform booking/payment/accounting writes.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "programme_id": {"type": "string"},
                    "programme_name": {"type": "string"},
                    "start_date": {"type": "string"},
                    "target_end_date": {"type": "string"},
                    "status": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id", "programme_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        programme_id = str(params.get("programme_id") or "").strip()
        programme_name = str(params.get("programme_name") or "member programme").strip()
        start_date = str(params.get("start_date") or "not specified").strip()
        target_end_date = str(params.get("target_end_date") or "not specified").strip()
        status = str(params.get("status") or "enrolled_local").strip()
        approved = bool(params.get("approved") or False)
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena programme enrollment failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Programme enrollment created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if bool(member.get("sensitive")) and not approved:
            return self._result(
                "Serena programme enrollment blocked\n\n"
                f"- Member ID: {member_id}\n"
                "- Reason: sensitive member/programme enrollment requires approval.\n"
                "- Programme enrollment created: no\n"
                "- Medical advice given: no\n"
                "- External API called: no\n"
                "- Payment action performed: no\n"
                "- Accounting write performed: no\n"
                "- Booking write performed: no\n"
                "- Programme changed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        record = {
            "record_type": "programme_enrollment",
            "created_at": _timestamp(),
            "programme_enrollment_id": f"PENR-{_timestamp()}",
            "programme_id": programme_id,
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "programme_name": programme_name,
            "start_date": start_date,
            "target_end_date": target_end_date,
            "status": status,
            "approved": approved,
            "notes": notes,
            "sensitive": bool(member.get("sensitive")),
            "programme_enrollment_created": True,
            "medical_advice_given": False,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": True,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("programmes", f"programme-enroll-{member_id}-{programme_id}", record)

        return self._result(
            "Serena programme enrollment created\n\n"
            f"- Programme enrollment ID: {record['programme_enrollment_id']}\n"
            f"- Programme ID: {programme_id}\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Programme: {programme_name}\n"
            f"- Start date: {start_date}\n"
            f"- Target end date: {target_end_date}\n"
            f"- Status: {status}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Sensitive: {'yes' if member.get('sensitive') else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Programme enrollment created: yes\n"
            "- Medical advice given: no\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Programme changed: yes\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_programme_progress")
class SerenaMembershipProgrammeProgressTool(_MembershipBaseTool):
    tool_id = "serena_membership_programme_progress"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local programme progress record. Does not provide medical advice.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "programme_id": {"type": "string"},
                    "progress_status": {"type": "string"},
                    "milestone": {"type": "string"},
                    "progress_note": {"type": "string"},
                    "next_step": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["member_id", "programme_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        programme_id = str(params.get("programme_id") or "").strip()
        progress_status = str(params.get("progress_status") or "in_progress").strip()
        milestone = str(params.get("milestone") or "not specified").strip()
        progress_note = str(params.get("progress_note") or "").strip()
        next_step = str(params.get("next_step") or "not specified").strip()
        approved = bool(params.get("approved") or False)

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena programme progress failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Progress recorded: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        sensitive_note = bool(member.get("sensitive")) and bool(progress_note.strip())
        if sensitive_note and not approved:
            return self._result(
                "Serena programme progress blocked\n\n"
                f"- Member ID: {member_id}\n"
                f"- Programme ID: {programme_id}\n"
                "- Reason: sensitive programme progress note requires approval.\n"
                "- Progress recorded: no\n"
                "- Medical advice given: no\n"
                "- External API called: no\n"
                "- Programme changed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        record = {
            "record_type": "programme_progress",
            "created_at": _timestamp(),
            "progress_id": f"PROGPROG-{_timestamp()}",
            "programme_id": programme_id,
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "progress_status": progress_status,
            "milestone": milestone,
            "progress_note": progress_note,
            "next_step": next_step,
            "approved": approved,
            "sensitive": bool(member.get("sensitive")),
            "progress_recorded": True,
            "medical_advice_given": False,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": True,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("programmes", f"programme-progress-{member_id}-{programme_id}", record)

        return self._result(
            "Serena programme progress recorded\n\n"
            f"- Progress ID: {record['progress_id']}\n"
            f"- Programme ID: {programme_id}\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Progress status: {progress_status}\n"
            f"- Milestone: {milestone}\n"
            f"- Next step: {next_step}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Sensitive: {'yes' if member.get('sensitive') else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Progress recorded: yes\n"
            "- Medical advice given: no\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Programme changed: yes\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_programme_follow_up")
class SerenaMembershipProgrammeFollowUpTool(_MembershipBaseTool):
    tool_id = "serena_membership_programme_follow_up"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local programme follow-up plan. Does not send external messages.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "programme_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "timing": {"type": "string"},
                    "channel": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id", "programme_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        programme_id = str(params.get("programme_id") or "").strip()
        reason = str(params.get("reason") or "programme follow-up").strip()
        timing = str(params.get("timing") or "not specified").strip()
        channel = str(params.get("channel") or "manual/local").strip()
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena programme follow-up failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Follow-up planned: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Confirm programme status and follow-up reason.",
            "Avoid sensitive health details in external messages.",
            "Use Bookings handoff if follow-up requires an appointment.",
            "Use Compliance before external messaging or reporting.",
            "Do not send SMS/email/WhatsApp from Membership v1.",
            "Preserve follow-up plan evidence.",
        ]

        record = {
            "record_type": "programme_follow_up",
            "created_at": _timestamp(),
            "follow_up_id": f"PFU-{_timestamp()}",
            "programme_id": programme_id,
            "member_id": member_id,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "reason": reason,
            "timing": timing,
            "channel": channel,
            "notes": notes,
            "steps": steps,
            "sensitive": bool(member.get("sensitive")),
            "follow_up_planned": True,
            "external_message_sent": False,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("programmes", f"programme-follow-up-{member_id}-{programme_id}", record)

        return self._result(
            "Serena programme follow-up plan created\n\n"
            f"- Follow-up ID: {record['follow_up_id']}\n"
            f"- Programme ID: {programme_id}\n"
            f"- Member ID: {member_id}\n"
            f"- Member: {member.get('member_name')}\n"
            f"- Reason: {reason}\n"
            f"- Timing: {timing}\n"
            f"- Channel: {channel}\n"
            f"- Sensitive: {'yes' if member.get('sensitive') else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Follow-up planned: yes\n"
            "- External message sent: no\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Programme changed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**record, "record_path": str(record_path)},
        )


def _member_summary_markdown(member: dict[str, Any], title: str, notes: str = "") -> str:
    sensitive = bool(member.get("sensitive"))
    lines = [
        f"# {title}",
        "",
        "Created by: Serena Membership / Subscriptions / Patient Programmes Full Operator v1",
        f"Created at: {_timestamp()}",
        "",
        "## Member / Programme",
        "",
        f"- Member ID: {member.get('member_id')}",
        f"- Business: {member.get('business')}",
        f"- Membership plan: {member.get('membership_plan')}",
        f"- Programme: {member.get('programme')}",
        f"- Payment status: {member.get('payment_status')}",
        f"- Status: {member.get('status')}",
        f"- Sensitive: {'yes' if sensitive else 'no'}",
        "",
        "## Patient/client handling",
        "",
    ]

    if sensitive:
        lines.extend([
            "- Patient/client details are sensitive.",
            "- Avoid sharing externally without Compliance review and approval.",
            "- Use minimal public-facing wording.",
        ])
    else:
        lines.append(f"- Member: {member.get('member_name')}")

    lines.extend([
        "",
        "## Safety",
        "",
        "- External API called: no",
        "- Google Doc created: no",
        "- Drive upload performed: no",
        "- Report created locally: yes",
        "- Medical advice given: no",
        "- Secret values exposed: no",
        "",
    ])

    if notes:
        lines.extend(["## Notes", "", notes, ""])

    return "\n".join(lines)


@ToolRegistry.register("serena_membership_docs_handoff")
class SerenaMembershipDocsHandoffTool(_MembershipBaseTool):
    tool_id = "serena_membership_docs_handoff"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Docs handoff plan for a member/programme. Does not create a Google Doc.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "title": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        title = str(params.get("title") or f"Member Summary {member_id}").strip()
        approved = bool(params.get("approved") or False)
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena Membership Docs handoff failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Google Doc created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if bool(member.get("sensitive")) and not approved:
            return self._result(
                "Serena Membership Docs handoff blocked\n\n"
                f"- Member ID: {member_id}\n"
                "- Reason: sensitive member/programme Docs handoff requires approval and Compliance review.\n"
                "- Google Doc created: no\n"
                "- External API called: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        payload = {
            "record_type": "membership_docs_handoff",
            "created_at": _timestamp(),
            "member_id": member_id,
            "title": title,
            "approved": approved,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "membership_plan": member.get("membership_plan"),
            "programme": member.get("programme"),
            "payment_status": member.get("payment_status"),
            "sensitive": bool(member.get("sensitive")),
            "notes": notes,
            "target_operator": "serena_google_docs",
            "handoff_created": True,
            "external_api_called": False,
            "google_doc_created": False,
            "drive_upload_performed": False,
            "medical_advice_given": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("handoff", f"docs-handoff-{member_id}", payload)

        return self._result(
            "Serena Membership Docs handoff created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Title: {title}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Sensitive: {'yes' if member.get('sensitive') else 'no'}\n"
            f"- Target operator: serena_google_docs\n"
            f"- Record: {record_path}\n"
            "- Handoff created: yes\n"
            "- External API called: no\n"
            "- Google Doc created: no\n"
            "- Drive upload performed: no\n"
            "- Medical advice given: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Next safe step:\n"
            "- Use Google Docs operator only after approval when sensitive member/programme data is included.",
            metadata={**payload, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_drive_handoff")
class SerenaMembershipDriveHandoffTool(_MembershipBaseTool):
    tool_id = "serena_membership_drive_handoff"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Drive evidence/storage handoff plan for a member/programme. Does not upload to Drive.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "folder": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        folder = str(params.get("folder") or "Membership").strip()
        approved = bool(params.get("approved") or False)
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena Membership Drive handoff failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Drive upload performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if bool(member.get("sensitive")) and not approved:
            return self._result(
                "Serena Membership Drive handoff blocked\n\n"
                f"- Member ID: {member_id}\n"
                "- Reason: sensitive member/programme Drive handoff requires approval and Compliance review.\n"
                "- Drive upload performed: no\n"
                "- External API called: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        payload = {
            "record_type": "membership_drive_handoff",
            "created_at": _timestamp(),
            "member_id": member_id,
            "folder": folder,
            "approved": approved,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "membership_plan": member.get("membership_plan"),
            "programme": member.get("programme"),
            "payment_status": member.get("payment_status"),
            "sensitive": bool(member.get("sensitive")),
            "notes": notes,
            "target_operator": "serena_gdrive",
            "handoff_created": True,
            "external_api_called": False,
            "drive_upload_performed": False,
            "google_doc_created": False,
            "medical_advice_given": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("handoff", f"drive-handoff-{member_id}", payload)

        return self._result(
            "Serena Membership Drive handoff created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Folder: {folder}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Sensitive: {'yes' if member.get('sensitive') else 'no'}\n"
            f"- Target operator: serena_gdrive\n"
            f"- Record: {record_path}\n"
            "- Handoff created: yes\n"
            "- External API called: no\n"
            "- Drive upload performed: no\n"
            "- Google Doc created: no\n"
            "- Medical advice given: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Next safe step:\n"
            "- Use Google Drive operator only after approval when sensitive member/programme data is included.",
            metadata={**payload, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_reporting_handoff")
class SerenaMembershipReportingHandoffTool(_MembershipBaseTool):
    tool_id = "serena_membership_reporting_handoff"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Reporting handoff plan for membership/programme data. Does not export externally.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "report_type": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        report_type = str(params.get("report_type") or "member-summary").strip()
        approved = bool(params.get("approved") or False)
        notes = str(params.get("notes") or "").strip()

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena Membership Reporting handoff failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Report exported: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if bool(member.get("sensitive")) and not approved:
            return self._result(
                "Serena Membership Reporting handoff blocked\n\n"
                f"- Member ID: {member_id}\n"
                "- Reason: sensitive member/programme Reporting handoff requires approval and Compliance review.\n"
                "- Report exported: no\n"
                "- External API called: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        payload = {
            "record_type": "membership_reporting_handoff",
            "created_at": _timestamp(),
            "member_id": member_id,
            "report_type": report_type,
            "approved": approved,
            "business": member.get("business"),
            "member_name": member.get("member_name"),
            "membership_plan": member.get("membership_plan"),
            "programme": member.get("programme"),
            "payment_status": member.get("payment_status"),
            "sensitive": bool(member.get("sensitive")),
            "notes": notes,
            "target_operator": "serena_reporting",
            "handoff_created": True,
            "external_api_called": False,
            "report_exported": False,
            "drive_upload_performed": False,
            "google_doc_created": False,
            "medical_advice_given": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("handoff", f"reporting-handoff-{member_id}", payload)

        return self._result(
            "Serena Membership Reporting handoff created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Report type: {report_type}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Sensitive: {'yes' if member.get('sensitive') else 'no'}\n"
            f"- Target operator: serena_reporting\n"
            f"- Record: {record_path}\n"
            "- Handoff created: yes\n"
            "- External API called: no\n"
            "- Report exported: no\n"
            "- Drive upload performed: no\n"
            "- Google Doc created: no\n"
            "- Medical advice given: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Next safe step:\n"
            "- Use Reporting operator only after approval when sensitive member/programme data is included.",
            metadata={**payload, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_membership_member_summary")
class SerenaMembershipMemberSummaryTool(_MembershipBaseTool):
    tool_id = "serena_membership_member_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local member/programme summary in JSON and Markdown.",
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string"},
                    "title": {"type": "string"},
                    "notes": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["member_id"],
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        member_id = str(params.get("member_id") or "").strip()
        title = str(params.get("title") or f"Member Summary {member_id}").strip()
        notes = str(params.get("notes") or "").strip()
        approved = bool(params.get("approved") or False)

        member = _find_member_profile(member_id)
        if not member:
            return self._result(
                "Serena member summary failed\n\n"
                f"- Member ID: {member_id}\n"
                "- Error: member not found\n"
                "- Summary created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if bool(member.get("sensitive")) and not approved:
            return self._result(
                "Serena member summary blocked\n\n"
                f"- Member ID: {member_id}\n"
                "- Reason: sensitive member summary requires approval.\n"
                "- Summary created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        payload = {
            "report_type": "serena_membership_member_summary",
            "created_at": _timestamp(),
            "member": member,
            "title": title,
            "notes": notes,
            "approved": approved,
            "summary_created": True,
            "external_api_called": False,
            "drive_upload_performed": False,
            "google_doc_created": False,
            "report_exported": False,
            "medical_advice_given": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        json_path = _save_json("reports", f"member-summary-{member_id}", payload)
        md_path = _save_text("reports", f"member-summary-{member_id}", _member_summary_markdown(member, title, notes), ".md")

        return self._result(
            "Serena member summary created\n\n"
            f"- Member ID: {member_id}\n"
            f"- Title: {title}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Sensitive: {'yes' if member.get('sensitive') else 'no'}\n"
            f"- JSON report: {json_path}\n"
            f"- Markdown report: {md_path}\n"
            "- Summary created: yes\n"
            "- External API called: no\n"
            "- Drive upload performed: no\n"
            "- Google Doc created: no\n"
            "- Report exported: no\n"
            "- Medical advice given: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**payload, "json_path": str(json_path), "markdown_path": str(md_path)},
        )


def _membership_record_counts() -> dict[str, int]:
    return {
        "members": len(_load_json_records("members")),
        "enrollments": len(_load_json_records("enrollments")),
        "subscriptions": len(_load_json_records("subscriptions")),
        "programmes": len(_load_json_records("programmes")),
        "handoff": len(_load_json_records("handoff")),
        "reports": len(_load_json_records("reports")),
        "plans": len(_load_json_records("plans")),
        "audits": len(_load_json_records("audits")),
    }


def _blocked_membership_response(
    title: str,
    report_name: str,
    action: str,
    reason: str,
    blocked_reason: str,
    extra_flags: dict[str, Any] | None = None,
) -> ToolResult:
    payload = {
        "report_type": f"serena_membership_{report_name}",
        "created_at": _timestamp(),
        "action": action,
        "reason": reason,
        "blocked_reason": blocked_reason,
        "risk_level": "BLOCKED",
        "allowed_to_continue": False,
        "approval_required": True,
        "owner_review_required": True,
        "compliance_review_required": True,
        "external_api_called": False,
        "payment_action_performed": False,
        "accounting_write_performed": False,
        "booking_write_performed": False,
        "programme_changed": False,
        "bulk_cancel_performed": False,
        "membership_cancelled": False,
        "subscription_cancelled": False,
        "payment_changed": False,
        "patient_data_exposed": False,
        "medical_advice_given": False,
        "delete_performed": False,
        "changes_made": False,
        "secret_values_exposed": False,
        "hub_adapter": _hub_adapter_contract(),
    }

    if extra_flags:
        payload.update(extra_flags)

    report_path = _save_json("audits", report_name, payload)

    return ToolResult(
        tool_name=f"serena_membership_{report_name}",
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
            "- Compliance review required: yes\n"
            f"- Report: {report_path}\n"
            "- External API called: no\n"
            "- Payment action performed: no\n"
            "- Accounting write performed: no\n"
            "- Booking write performed: no\n"
            "- Programme changed: no\n"
            "- Bulk cancel performed: no\n"
            "- Membership cancelled: no\n"
            "- Subscription cancelled: no\n"
            "- Payment changed: no\n"
            "- Patient data exposed: no\n"
            "- Medical advice given: no\n"
            "- Delete performed: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard"
        ),
        metadata={**payload, "report_path": str(report_path)},
    )


@ToolRegistry.register("serena_membership_audit")
class SerenaMembershipAuditTool(_MembershipBaseTool):
    tool_id = "serena_membership_audit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Audit Serena Membership outputs, records, handoffs, programmes, subscriptions, and safety posture.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                },
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "").strip()
        sources = _membership_sources()
        env = _env_status()
        counts = _membership_record_counts()
        safety = _safety_policy()

        members = _load_json_records("members")
        enrollments = _load_json_records("enrollments")
        subscriptions = _load_json_records("subscriptions")
        programmes = _load_json_records("programmes")
        handoffs = _load_json_records("handoff")

        if business:
            members = [x for x in members if str(x.get("business") or "") == business]
            enrollments = [x for x in enrollments if str(x.get("business") or "") == business]
            subscriptions = [x for x in subscriptions if str(x.get("business") or "") == business]
            programmes = [x for x in programmes if str(x.get("business") or "") == business]
            handoffs = [x for x in handoffs if str(x.get("business") or "") == business]

        member_profiles = [x for x in members if str(x.get("record_type") or "") == "member_profile"]
        sensitive_members = [x for x in member_profiles if bool(x.get("sensitive"))]
        pending_payments = [
            x for x in subscriptions
            if str(x.get("payment_status") or x.get("status") or "").lower() in {"pending", "local_pending", "not started"}
        ]
        members_without_subscription = []
        subscription_member_ids = {str(x.get("member_id") or "") for x in subscriptions}
        for member in member_profiles:
            if str(member.get("member_id") or "") not in subscription_member_ids:
                members_without_subscription.append(member)

        issues = []
        recommendations = []

        if sensitive_members:
            recommendations.append(f"{len(sensitive_members)} sensitive member(s) require Compliance review before external sharing.")

        if pending_payments:
            recommendations.append(f"{len(pending_payments)} subscription/payment record(s) are pending or local-only.")

        if members_without_subscription:
            issues.append(f"{len(members_without_subscription)} member profile(s) do not have a local subscription record.")

        recommendations.extend([
            "Use Accounting handoff for payment, invoice, PayFast, and Xero workflows.",
            "Use Bookings handoff for programme appointments and reminders.",
            "Use Docs/Drive/Reporting handoff only after approval for sensitive member/programme data.",
            "Keep Payflow as absorbed subscription/payment-flow context, not a standalone skill.",
            "Keep bulk cancellation, silent programme changes, unapproved payment changes, and patient data exposure blocked.",
            "Hub adapter remains pending until Serena Hub dashboard/event bus exists.",
        ])

        payload = {
            "report_type": "serena_membership_audit",
            "created_at": _timestamp(),
            "business": business or "all",
            "sources_registered": len(sources),
            "record_counts": counts,
            "member_profiles_considered": len(member_profiles),
            "sensitive_members": len(sensitive_members),
            "subscriptions_considered": len(subscriptions),
            "pending_payment_or_subscription_records": len(pending_payments),
            "members_without_subscription": len(members_without_subscription),
            "programme_records": len(programmes),
            "handoff_records": len(handoffs),
            "env_status": env,
            "safety_policy": safety,
            "issues": issues,
            "recommendations": recommendations,
            "external_api_called": False,
            "payment_action_performed": False,
            "accounting_write_performed": False,
            "booking_write_performed": False,
            "programme_changed": False,
            "medical_advice_given": False,
            "patient_data_exposed": False,
            "delete_performed": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("audits", f"membership-audit-{business or 'all'}", payload)

        lines = [
            "Serena Membership audit",
            "",
            f"- Business: {business or 'all'}",
            f"- Sources registered: {len(sources)}",
            f"- Members: {counts.get('members', 0)}",
            f"- Enrollments: {counts.get('enrollments', 0)}",
            f"- Subscriptions: {counts.get('subscriptions', 0)}",
            f"- Programmes: {counts.get('programmes', 0)}",
            f"- Handoff records: {counts.get('handoff', 0)}",
            f"- Reports: {counts.get('reports', 0)}",
            f"- Member profiles considered: {len(member_profiles)}",
            f"- Sensitive members: {len(sensitive_members)}",
            f"- Pending payment/subscription records: {len(pending_payments)}",
            f"- Members without subscription: {len(members_without_subscription)}",
            f"- Audit report: {report_path}",
            "- External API called: no",
            "- Payment action performed: no",
            "- Accounting write performed: no",
            "- Booking write performed: no",
            "- Programme changed: no",
            "- Medical advice given: no",
            "- Patient data exposed: no",
            "- Delete performed: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Issues:",
        ]

        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- none")

        lines.extend(["", "Recommendations:"])
        lines.extend(f"- {item}" for item in recommendations)

        lines.extend(["", "Blocked operations:"])
        lines.extend(f"- {item}" for item in safety["blocked"])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_membership_blocked_bulk_cancel")
class SerenaMembershipBlockedBulkCancelTool(_MembershipBaseTool):
    tool_id = "serena_membership_blocked_bulk_cancel"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked bulk membership cancellation command.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _blocked_membership_response(
            "Bulk membership cancellation blocked by Serena Membership v1 policy",
            "blocked-bulk-cancel",
            str(params.get("action") or "bulk cancel memberships").strip(),
            str(params.get("reason") or "Bulk membership cancellation requested.").strip(),
            "Bulk membership cancellation is blocked. Serena may only prepare one exact member cancellation plan at a time with approval.",
            {"bulk_cancel_performed": False},
        )


@ToolRegistry.register("serena_membership_blocked_unapproved_payment_change")
class SerenaMembershipBlockedUnapprovedPaymentChangeTool(_MembershipBaseTool):
    tool_id = "serena_membership_blocked_unapproved_payment_change"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked unapproved membership/subscription payment change command.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _blocked_membership_response(
            "Unapproved payment change blocked by Serena Membership v1 policy",
            "blocked-unapproved-payment-change",
            str(params.get("action") or "change subscription payment amount").strip(),
            str(params.get("reason") or "Payment change requested without approval.").strip(),
            "Payment amount, subscription price, billing interval, PayFast, Xero, and accounting changes require explicit approval and Accounting handoff.",
            {"payment_changed": False, "payment_action_performed": False},
        )


@ToolRegistry.register("serena_membership_blocked_patient_data_exposure")
class SerenaMembershipBlockedPatientDataExposureTool(_MembershipBaseTool):
    tool_id = "serena_membership_blocked_patient_data_exposure"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked patient/client membership/programme data exposure command.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _blocked_membership_response(
            "Patient/client data exposure blocked by Serena Membership v1 policy",
            "blocked-patient-data-exposure",
            str(params.get("action") or "expose member patient/client details").strip(),
            str(params.get("reason") or "Patient/client data exposure requested.").strip(),
            "Patient/client membership and programme data may not be exposed externally or placed in public-facing docs/reports/messages without approval and Compliance review.",
            {"patient_data_exposed": False},
        )


@ToolRegistry.register("serena_membership_blocked_silent_programme_change")
class SerenaMembershipBlockedSilentProgrammeChangeTool(_MembershipBaseTool):
    tool_id = "serena_membership_blocked_silent_programme_change"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked silent programme change command.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
            category="serena_membership",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _blocked_membership_response(
            "Silent programme change blocked by Serena Membership v1 policy",
            "blocked-silent-programme-change",
            str(params.get("action") or "silently change programme").strip(),
            str(params.get("reason") or "Silent programme change requested.").strip(),
            "Programme enrollment, progress, pause, cancellation, renewal, or member status changes must be explicit, targeted, reported, and approval-gated when sensitive or material.",
            {"programme_changed": False},
        )


__all__ = [
    "SerenaMembershipStatusTool",
    "SerenaMembershipEnvCheckTool",
    "SerenaMembershipPlanTool",
    "SerenaMembershipSourceListTool",
    "SerenaMembershipSourceInfoTool",
    "SerenaMembershipUpdateMemberStatusTool",
    "SerenaMembershipRenewalPlanTool",
    "SerenaMembershipBookingHandoffTool",
    "SerenaMembershipProgrammeFollowUpTool",
    "SerenaMembershipMemberSummaryTool",
    "SerenaMembershipBlockedSilentProgrammeChangeTool",
    "SerenaMembershipBlockedPatientDataExposureTool",
    "SerenaMembershipBlockedUnapprovedPaymentChangeTool",
    "SerenaMembershipBlockedBulkCancelTool",
    "SerenaMembershipAuditTool",
    "SerenaMembershipReportingHandoffTool",
    "SerenaMembershipDriveHandoffTool",
    "SerenaMembershipDocsHandoffTool",
    "SerenaMembershipProgrammeProgressTool",
    "SerenaMembershipProgrammeEnrollTool",
    "SerenaMembershipProgrammePlanTool",
    "SerenaMembershipAccountingHandoffTool",
    "SerenaMembershipPaymentHandoffTool",
    "SerenaMembershipSubscriptionRecordTool",
    "SerenaMembershipSubscriptionPlanTool",
    "SerenaMembershipPauseMembershipPlanTool",
    "SerenaMembershipCancelMembershipPlanTool",
    "SerenaMembershipEnrollMemberTool",
    "SerenaMembershipEnrollmentPlanTool",
    "SerenaMembershipMemberListTool",
    "SerenaMembershipMemberInfoTool",
    "SerenaMembershipCreateMemberProfileTool",
    "SerenaMembershipPlanInfoTool",
    "SerenaMembershipPlanListTool",
]

# ---------------------------------------------------------------------------
# Batch 1 reconciliation extension layer
# ---------------------------------------------------------------------------

def _membership_reconcile_now():
    return datetime.now().isoformat(timespec="seconds")


def _membership_reconcile_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _membership_reconcile_slug(value):
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").lower()).strip("-") or "membership"


def _membership_reconcile_actions():
    return {
        "local_report_created": True,
        "member_created": False,
        "member_updated": False,
        "member_cancelled": False,
        "subscription_activated": False,
        "subscription_cancelled": False,
        "payment_captured": False,
        "refund_issued": False,
        "customer_contacted": False,
        "crm_write_performed": False,
        "hub_write_performed": False,
        "wordpress_live_update": False,
        "accounting_system_write": False,
        "external_export_performed": False,
        "dashboard_created": False,
        "sensitive_member_export_performed": False,
        "secret_values_exposed": False,
    }


def _membership_reconcile_artifact(kind, title, data):
    out = Path("outputs/membership") / kind
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{_membership_reconcile_stamp()}-{_membership_reconcile_slug(title)}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _membership_scan_local_artifacts(root="outputs", limit=300):
    base = Path(root)
    if not base.exists():
        return []

    files = []
    for pattern in ("*.json", "*.md", "*.txt", "*.csv", "*.xlsx"):
        files.extend(base.rglob(pattern))

    rows = []
    for item in sorted(files, key=lambda x: str(x).lower()):
        try:
            stat = item.stat()
        except OSError:
            continue

        raw = str(item).lower()
        if "membership" in raw:
            operator_guess = "membership"
        elif "ecommerce" in raw:
            operator_guess = "ecommerce"
        elif "accounting" in raw:
            operator_guess = "accounting"
        elif "bookings" in raw:
            operator_guess = "bookings"
        elif "wordpress" in raw:
            operator_guess = "wordpress"
        elif "reporting" in raw:
            operator_guess = "reporting"
        else:
            operator_guess = "unknown"

        rows.append(
            {
                "path": str(item),
                "operator_guess": operator_guess,
                "suffix": item.suffix.lower(),
                "size_bytes": stat.st_size,
                "handoff_signal": "handoff" in raw,
                "member_signal": any(t in raw for t in ["member", "membership", "subscriber", "subscription", "programme", "program"]),
                "revenue_signal": any(t in raw for t in ["revenue", "payment", "order", "invoice", "subscription", "payfast"]),
                "booking_signal": any(t in raw for t in ["booking", "appointment", "follow-up", "programme"]),
                "funnel_signal": any(t in raw for t in ["landing", "funnel", "wordpress", "page", "cta", "membership"]),
                "lifecycle_signal": any(t in raw for t in ["enroll", "renewal", "pause", "cancel", "retention", "follow-up"]),
                "safety_signal": any(t in raw for t in ["blocked", "safety", "approval", "sensitive", "patient", "secret"]),
            }
        )

        if len(rows) >= int(limit):
            break

    return rows


def _membership_count_by(items, key):
    counts = {}
    for item in items:
        value = item.get(key) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


class _SerenaMembershipReconcileBase(BaseTool):
    is_local = True

    def _result(self, content, success=True, metadata=None):
        return ToolResult(
            tool_name=self.tool_id,
            content=content,
            success=success,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_membership_ecommerce_handoff_summary")
class SerenaMembershipEcommerceHandoffSummaryTool(_SerenaMembershipReconcileBase):
    tool_id = "serena_membership_ecommerce_handoff_summary"

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Summarize Ecommerce membership/subscription handoff artifacts. Local report only.",
            parameters={"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
            category="serena_membership",
        )

    def execute(self, **params):
        root = str(params.get("root") or "outputs/ecommerce").strip()
        limit = int(params.get("limit") or 300)
        items = _membership_scan_local_artifacts(root=root, limit=limit)

        handoffs = [x for x in items if x.get("handoff_signal")]
        member_items = [x for x in items if x.get("member_signal")]
        revenue_items = [x for x in items if x.get("revenue_signal")]
        lifecycle_items = [x for x in items if x.get("lifecycle_signal")]
        safety_items = [x for x in items if x.get("safety_signal")]

        data = {
            "tool": self.tool_id,
            "operator": "membership",
            "source_operator": "ecommerce",
            "reconciliation_layer": "batch1",
            "root": root,
            "artifact_count": len(items),
            "handoff_count": len(handoffs),
            "member_signal_count": len(member_items),
            "revenue_signal_count": len(revenue_items),
            "lifecycle_signal_count": len(lifecycle_items),
            "safety_signal_count": len(safety_items),
            "counts_by_suffix": _membership_count_by(items, "suffix"),
            "future_hub_event": {
                "event_type": "membership.ecommerce_handoff_summary_created",
                "entity_type": "ecommerce_membership_handoff_summary",
                "entity_ref": root,
                "approval_required": False,
            },
            "actions": _membership_reconcile_actions(),
            "created_at": _membership_reconcile_now(),
        }
        path = _membership_reconcile_artifact("operator-handoff-summaries", "ecommerce", data)

        return self._result(
            "Serena Membership Ecommerce handoff summary created\n\n"
            f"- Root: {root}\n"
            f"- Artifacts summarized: {len(items)}\n"
            f"- Handoffs: {len(handoffs)}\n"
            f"- Member signals: {len(member_items)}\n"
            f"- Revenue signals: {len(revenue_items)}\n"
            f"- Summary: {path}\n\n"
            "Actions performed: local report only. Member created: no. Subscription changed: no. Payment captured: no.",
            metadata=data,
        )


@ToolRegistry.register("serena_membership_accounting_revenue_summary")
class SerenaMembershipAccountingRevenueSummaryTool(_SerenaMembershipReconcileBase):
    tool_id = "serena_membership_accounting_revenue_summary"

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Summarize Accounting revenue/billing artifacts for Membership planning. Local report only.",
            parameters={"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
            category="serena_membership",
        )

    def execute(self, **params):
        root = str(params.get("root") or "outputs/accounting").strip()
        limit = int(params.get("limit") or 300)
        items = _membership_scan_local_artifacts(root=root, limit=limit)

        revenue_items = [x for x in items if x.get("revenue_signal")]
        member_items = [x for x in items if x.get("member_signal")]
        safety_items = [x for x in items if x.get("safety_signal")]
        handoffs = [x for x in items if x.get("handoff_signal")]

        data = {
            "tool": self.tool_id,
            "operator": "membership",
            "source_operator": "accounting",
            "reconciliation_layer": "batch1",
            "root": root,
            "artifact_count": len(items),
            "revenue_signal_count": len(revenue_items),
            "member_signal_count": len(member_items),
            "handoff_count": len(handoffs),
            "safety_signal_count": len(safety_items),
            "future_hub_event": {
                "event_type": "membership.accounting_revenue_summary_created",
                "entity_type": "accounting_membership_revenue_summary",
                "entity_ref": root,
                "approval_required": False,
            },
            "actions": _membership_reconcile_actions(),
            "created_at": _membership_reconcile_now(),
        }
        path = _membership_reconcile_artifact("operator-revenue-summaries", "accounting", data)

        return self._result(
            "Serena Membership Accounting revenue summary created\n\n"
            f"- Root: {root}\n"
            f"- Artifacts summarized: {len(items)}\n"
            f"- Revenue signals: {len(revenue_items)}\n"
            f"- Member signals: {len(member_items)}\n"
            f"- Summary: {path}\n\n"
            "Actions performed: local report only. Payment captured: no. Refund issued: no. Accounting write: no.",
            metadata=data,
        )


@ToolRegistry.register("serena_membership_bookings_member_summary")
class SerenaMembershipBookingsMemberSummaryTool(_SerenaMembershipReconcileBase):
    tool_id = "serena_membership_bookings_member_summary"

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Summarize Bookings appointment/member signals for Membership planning. Local report only.",
            parameters={"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
            category="serena_membership",
        )

    def execute(self, **params):
        root = str(params.get("root") or "outputs/bookings").strip()
        limit = int(params.get("limit") or 300)
        items = _membership_scan_local_artifacts(root=root, limit=limit)

        booking_items = [x for x in items if x.get("booking_signal")]
        member_items = [x for x in items if x.get("member_signal")]
        lifecycle_items = [x for x in items if x.get("lifecycle_signal")]
        safety_items = [x for x in items if x.get("safety_signal")]

        data = {
            "tool": self.tool_id,
            "operator": "membership",
            "source_operator": "bookings",
            "reconciliation_layer": "batch1",
            "root": root,
            "artifact_count": len(items),
            "booking_signal_count": len(booking_items),
            "member_signal_count": len(member_items),
            "lifecycle_signal_count": len(lifecycle_items),
            "safety_signal_count": len(safety_items),
            "future_hub_event": {
                "event_type": "membership.bookings_member_summary_created",
                "entity_type": "bookings_member_summary",
                "entity_ref": root,
                "approval_required": False,
            },
            "actions": _membership_reconcile_actions(),
            "created_at": _membership_reconcile_now(),
        }
        path = _membership_reconcile_artifact("operator-member-summaries", "bookings", data)

        return self._result(
            "Serena Membership Bookings member summary created\n\n"
            f"- Root: {root}\n"
            f"- Artifacts summarized: {len(items)}\n"
            f"- Booking signals: {len(booking_items)}\n"
            f"- Member signals: {len(member_items)}\n"
            f"- Summary: {path}\n\n"
            "Actions performed: local report only. Member updated: no. Customer contacted: no. Booking changed: no.",
            metadata=data,
        )


@ToolRegistry.register("serena_membership_wordpress_funnel_summary")
class SerenaMembershipWordPressFunnelSummaryTool(_SerenaMembershipReconcileBase):
    tool_id = "serena_membership_wordpress_funnel_summary"

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Summarize WordPress membership funnel/page artifacts for Membership planning. Local report only.",
            parameters={"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer"}}},
            category="serena_membership",
        )

    def execute(self, **params):
        root = str(params.get("root") or "outputs/wordpress").strip()
        limit = int(params.get("limit") or 300)
        items = _membership_scan_local_artifacts(root=root, limit=limit)

        funnel_items = [x for x in items if x.get("funnel_signal")]
        member_items = [x for x in items if x.get("member_signal")]
        lifecycle_items = [x for x in items if x.get("lifecycle_signal")]
        safety_items = [x for x in items if x.get("safety_signal")]

        data = {
            "tool": self.tool_id,
            "operator": "membership",
            "source_operator": "wordpress",
            "reconciliation_layer": "batch1",
            "root": root,
            "artifact_count": len(items),
            "funnel_signal_count": len(funnel_items),
            "member_signal_count": len(member_items),
            "lifecycle_signal_count": len(lifecycle_items),
            "safety_signal_count": len(safety_items),
            "future_hub_event": {
                "event_type": "membership.wordpress_funnel_summary_created",
                "entity_type": "wordpress_membership_funnel_summary",
                "entity_ref": root,
                "approval_required": False,
            },
            "actions": _membership_reconcile_actions(),
            "created_at": _membership_reconcile_now(),
        }
        path = _membership_reconcile_artifact("operator-funnel-summaries", "wordpress", data)

        return self._result(
            "Serena Membership WordPress funnel summary created\n\n"
            f"- Root: {root}\n"
            f"- Artifacts summarized: {len(items)}\n"
            f"- Funnel signals: {len(funnel_items)}\n"
            f"- Member signals: {len(member_items)}\n"
            f"- Summary: {path}\n\n"
            "Actions performed: local report only. WordPress live update: no. Member created: no. Hub write: no.",
            metadata=data,
        )


@ToolRegistry.register("serena_membership_lifecycle_plan")
class SerenaMembershipLifecyclePlanTool(_SerenaMembershipReconcileBase):
    tool_id = "serena_membership_lifecycle_plan"

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Create an approval-gated membership lifecycle plan. Planning only; no member/subscription/customer write.",
            parameters={
                "type": "object",
                "properties": {
                    "programme": {"type": "string"},
                    "period": {"type": "string"},
                    "focus": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "include_sensitive": {"type": "boolean"},
                },
            },
            category="serena_membership",
        )

    def execute(self, **params):
        programme = str(params.get("programme") or "membership programme").strip()
        period = str(params.get("period") or "current").strip()
        focus = str(params.get("focus") or "enrollment,retention,renewal,cancellation").strip()
        approved = bool(params.get("approved", False))
        include_sensitive = bool(params.get("include_sensitive", False))

        blockers = []
        if not approved:
            blockers.append("Membership lifecycle planning approval is missing.")
        if include_sensitive:
            blockers.append("Sensitive/unredacted member or patient data is blocked from this planning layer.")

        data = {
            "tool": self.tool_id,
            "operator": "membership",
            "reconciliation_layer": "batch1",
            "programme": programme,
            "period": period,
            "focus": focus,
            "approved": approved,
            "include_sensitive": include_sensitive,
            "lifecycle_ready": len(blockers) == 0,
            "blockers": blockers,
            "lifecycle_plan": [
                "Review local Ecommerce, Accounting, Bookings, and WordPress membership signals.",
                "Separate prospect, active member, paused, renewal, cancellation, and follow-up states.",
                "Prepare member lifecycle actions as draft recommendations only.",
                "Require approval before member creation, subscription changes, customer contact, CRM/Hub writes, or payment changes.",
                "Record all evidence locally before any external action.",
            ],
            "future_hub_event": {
                "event_type": "membership.lifecycle_plan_created",
                "entity_type": "membership_lifecycle_plan",
                "entity_ref": programme,
                "approval_required": True,
                "blocked": len(blockers) > 0,
            },
            "actions": _membership_reconcile_actions(),
            "created_at": _membership_reconcile_now(),
        }
        path = _membership_reconcile_artifact("lifecycle-plans", programme, data)

        return self._result(
            "Serena Membership lifecycle plan created\n\n"
            f"- Programme: {programme}\n"
            f"- Period: {period}\n"
            f"- Focus: {focus}\n"
            f"- Lifecycle ready: {data['lifecycle_ready']}\n"
            f"- Plan: {path}\n\n"
            "Blockers:\n"
            + "\n".join(f"- {x}" for x in blockers or ["None."])
            + "\n\nActions performed: local lifecycle planning only. Member/subscription/customer write: no.",
            metadata=data,
        )


@ToolRegistry.register("serena_membership_subscription_readiness_plan")
class SerenaMembershipSubscriptionReadinessPlanTool(_SerenaMembershipReconcileBase):
    tool_id = "serena_membership_subscription_readiness_plan"

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Create an approval-gated subscription readiness plan. Planning only; no payment/subscription write.",
            parameters={
                "type": "object",
                "properties": {
                    "offer": {"type": "string"},
                    "billing_model": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "include_sensitive": {"type": "boolean"},
                },
            },
            category="serena_membership",
        )

    def execute(self, **params):
        offer = str(params.get("offer") or "membership offer").strip()
        billing_model = str(params.get("billing_model") or "monthly subscription").strip()
        approved = bool(params.get("approved", False))
        include_sensitive = bool(params.get("include_sensitive", False))

        blockers = []
        if not approved:
            blockers.append("Subscription readiness approval is missing.")
        if include_sensitive:
            blockers.append("Sensitive/unredacted member, patient, billing, or payment data is blocked from this planning layer.")

        data = {
            "tool": self.tool_id,
            "operator": "membership",
            "reconciliation_layer": "batch1",
            "offer": offer,
            "billing_model": billing_model,
            "approved": approved,
            "include_sensitive": include_sensitive,
            "subscription_ready": len(blockers) == 0,
            "blockers": blockers,
            "readiness_plan": [
                "Confirm offer, billing cadence, cancellation policy, and fulfilment obligations.",
                "Confirm Accounting/PayFast/payment readiness before any payment action.",
                "Confirm WordPress membership page/funnel readiness before public launch.",
                "Confirm onboarding, booking, and follow-up flow.",
                "Require approval before subscription activation, payment capture, refund, or customer contact.",
            ],
            "future_hub_event": {
                "event_type": "membership.subscription_readiness_plan_created",
                "entity_type": "subscription_readiness_plan",
                "entity_ref": offer,
                "approval_required": True,
                "blocked": len(blockers) > 0,
            },
            "actions": _membership_reconcile_actions(),
            "created_at": _membership_reconcile_now(),
        }
        path = _membership_reconcile_artifact("subscription-readiness-plans", offer, data)

        return self._result(
            "Serena Membership subscription readiness plan created\n\n"
            f"- Offer: {offer}\n"
            f"- Billing model: {billing_model}\n"
            f"- Subscription ready: {data['subscription_ready']}\n"
            f"- Plan: {path}\n\n"
            "Blockers:\n"
            + "\n".join(f"- {x}" for x in blockers or ["None."])
            + "\n\nActions performed: local subscription planning only. Payment/subscription/customer write: no.",
            metadata=data,
        )


@ToolRegistry.register("serena_membership_blocked_unapproved_member_write")
class SerenaMembershipBlockedUnapprovedMemberWriteTool(_SerenaMembershipReconcileBase):
    tool_id = "serena_membership_blocked_unapproved_member_write"

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Record a blocked unapproved member/subscription/programme write attempt. Local audit only.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reference": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["action"],
            },
            category="serena_membership",
        )

    def execute(self, **params):
        action = str(params.get("action") or "").strip()
        reference = str(params.get("reference") or action).strip()
        reason = str(params.get("reason") or "Missing explicit approval for member/subscription write action.").strip()

        if not action:
            return self._result("action is required.", success=False)

        data = {
            "tool": self.tool_id,
            "operator": "membership",
            "reconciliation_layer": "batch1",
            "action": action,
            "reference": reference,
            "reason": reason,
            "blocked": True,
            "safe_alternative": "Create a local lifecycle or subscription readiness plan first, then require explicit approval before any write.",
            "future_hub_event": {
                "event_type": "membership.member_write_blocked",
                "entity_type": "blocked_member_write",
                "entity_ref": reference,
                "approval_required": True,
                "blocked": True,
            },
            "actions": _membership_reconcile_actions(),
            "created_at": _membership_reconcile_now(),
        }
        path = _membership_reconcile_artifact("blocked-actions", reference, data)

        return self._result(
            "Serena Membership member/subscription write blocked\n\n"
            f"- Action: {action}\n"
            f"- Reference: {reference}\n"
            f"- Reason: {reason}\n"
            f"- Audit: {path}\n\n"
            "Actions performed: local blocked-action audit only. Member/subscription/payment/CRM/Hub write: no.",
            metadata=data,
        )


@ToolRegistry.register("serena_membership_hub_member_plan")
class SerenaMembershipHubMemberPlanTool(_SerenaMembershipReconcileBase):
    tool_id = "serena_membership_hub_member_plan"

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Create a future Serena Hub member/subscription metadata plan. Planning only; no Hub/member write.",
            parameters={
                "type": "object",
                "properties": {
                    "scope": {"type": "string"},
                    "include_sensitive": {"type": "boolean"},
                },
            },
            category="serena_membership",
        )

    def execute(self, **params):
        scope = str(params.get("scope") or "membership,ecommerce,accounting,bookings,wordpress").strip()
        include_sensitive = bool(params.get("include_sensitive", False))

        blockers = []
        if include_sensitive:
            blockers.append("Sensitive/unredacted member, patient, billing, or programme data is blocked from this Hub metadata planning layer.")

        data = {
            "tool": self.tool_id,
            "operator": "membership",
            "reconciliation_layer": "batch1",
            "scope": scope,
            "include_sensitive": include_sensitive,
            "hub_member_ready": len(blockers) == 0,
            "blockers": blockers,
            "planned_metadata": [
                "ecommerce_membership_signal_count",
                "accounting_subscription_revenue_signal_count",
                "bookings_member_signal_count",
                "wordpress_membership_funnel_signal_count",
                "lifecycle_plan_count",
                "subscription_readiness_plan_count",
                "blocked_member_write_count",
                "sensitive_member_block_count",
                "future_hub_event_coverage",
            ],
            "future_hub_event": {
                "event_type": "membership.hub_member_plan_created",
                "entity_type": "hub_member_plan",
                "entity_ref": scope,
                "approval_required": True,
                "blocked": len(blockers) > 0,
            },
            "actions": _membership_reconcile_actions(),
            "created_at": _membership_reconcile_now(),
        }
        path = _membership_reconcile_artifact("hub-member-plans", _membership_reconcile_slug(scope), data)

        return self._result(
            "Serena Membership Hub member plan created\n\n"
            f"- Scope: {scope}\n"
            f"- Hub member ready: {data['hub_member_ready']}\n"
            f"- Plan: {path}\n\n"
            "Blockers:\n"
            + "\n".join(f"- {x}" for x in blockers or ["None."])
            + "\n\nActions performed: local Hub metadata planning only. Hub write: no. Member/subscription write: no.",
            metadata=data,
        )


@ToolRegistry.register("serena_membership_dashboard_handoff")
class SerenaMembershipDashboardHandoffTool(_SerenaMembershipReconcileBase):
    tool_id = "serena_membership_dashboard_handoff"

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Create a Membership dashboard handoff for future Serena Hub/Analytics UI. Local artifact only.",
            parameters={
                "type": "object",
                "properties": {
                    "dashboard_name": {"type": "string"},
                    "scope": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
            },
            category="serena_membership",
        )

    def execute(self, **params):
        dashboard_name = str(params.get("dashboard_name") or "Serena Membership Dashboard").strip()
        scope = str(params.get("scope") or "membership,ecommerce,accounting,bookings,wordpress").strip()
        approved = bool(params.get("approved", False))

        blockers = []
        if not approved:
            blockers.append("Dashboard handoff approval is missing.")

        data = {
            "tool": self.tool_id,
            "operator": "membership",
            "reconciliation_layer": "batch1",
            "dashboard_name": dashboard_name,
            "scope": scope,
            "approved": approved,
            "dashboard_ready": len(blockers) == 0,
            "blockers": blockers,
            "recommended_widgets": [
                "membership_funnel_signals",
                "subscription_revenue_readiness",
                "bookings_member_followups",
                "lifecycle_plan_status",
                "subscription_readiness_status",
                "blocked_member_writes",
                "sensitive_member_blocks",
                "hub_member_metadata_coverage",
            ],
            "future_hub_event": {
                "event_type": "membership.dashboard_handoff_created",
                "entity_type": "dashboard_handoff",
                "entity_ref": dashboard_name,
                "approval_required": True,
                "blocked": len(blockers) > 0,
            },
            "actions": _membership_reconcile_actions(),
            "created_at": _membership_reconcile_now(),
        }
        path = _membership_reconcile_artifact("dashboard-handoffs", dashboard_name, data)

        return self._result(
            "Serena Membership dashboard handoff created\n\n"
            f"- Dashboard: {dashboard_name}\n"
            f"- Scope: {scope}\n"
            f"- Dashboard ready: {data['dashboard_ready']}\n"
            f"- Handoff: {path}\n\n"
            "Blockers:\n"
            + "\n".join(f"- {x}" for x in blockers or ["None."])
            + "\n\nActions performed: local dashboard handoff only. Dashboard created: no. Hub write: no. Member/subscription write: no.",
            metadata=data,
        )

