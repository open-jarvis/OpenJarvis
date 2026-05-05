"""Native Serena Membership / Subscriptions / Patient Programmes Full Operator tools.

Layer 1 foundation:
- status
- env-check
- plan
- source-list
- source-info
"""

from __future__ import annotations

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
    import re
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


__all__ = [
    "SerenaMembershipStatusTool",
    "SerenaMembershipEnvCheckTool",
    "SerenaMembershipPlanTool",
    "SerenaMembershipSourceListTool",
    "SerenaMembershipSourceInfoTool",
    "SerenaMembershipUpdateMemberStatusTool",
    "SerenaMembershipRenewalPlanTool",
    "SerenaMembershipBookingHandoffTool",
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
