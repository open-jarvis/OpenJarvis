"""Native Serena Bookings / Appointments / Reminders Full Operator tools.

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


BOOKINGS_OUTPUT_ROOT = Path("outputs/bookings")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    import re
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "bookings"


def _bookings_root() -> Path:
    BOOKINGS_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in [
        "reports",
        "snapshots",
        "requests",
        "appointments",
        "reminders",
        "followups",
        "handoff",
    ]:
        (BOOKINGS_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return BOOKINGS_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _bookings_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _save_text(kind: str, name: str, content: str, suffix: str = ".md") -> Path:
    root = _bookings_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}{suffix}"
    path.write_text(content, encoding="utf-8")
    return path


def _hub_adapter_contract() -> dict[str, Any]:
    return {
        "hub_adapter_status": "pending_future_dashboard",
        "future_widgets": [
            "bookings_overview_widget",
            "calendar_schedule_widget",
            "appointment_detail_widget",
            "reminders_widget",
            "no_show_risk_widget",
            "followups_widget",
            "booking_requests_widget",
            "booking_approval_widget",
        ],
        "future_events": [
            "booking_request_created",
            "booking_created",
            "booking_reschedule_planned",
            "booking_cancel_planned",
            "reminder_plan_created",
            "followup_plan_created",
            "booking_calendar_handoff_created",
            "booking_report_created",
            "booking_action_blocked",
        ],
        "operator_state": [
            "current_business_id",
            "current_patient_or_client_id",
            "current_booking_id",
            "current_calendar_event_id",
            "current_appointment_status",
            "current_reminder_status",
            "current_required_approval",
            "current_report_path",
        ],
    }


def _safety_policy() -> dict[str, Any]:
    return {
        "allowed": [
            "Create local booking plans.",
            "Create local booking records.",
            "Create local reminder plans.",
            "Create local follow-up plans.",
            "Prepare Calendar handoff.",
            "Prepare Docs/Drive/Reporting handoff.",
            "Audit appointment state.",
            "Flag no-show risk.",
            "Report exact changes.",
        ],
        "guarded": [
            "Patient/client data.",
            "Health appointment context.",
            "External reminders.",
            "Calendar writes.",
            "Cancellations.",
            "Reschedules.",
            "Reminders containing sensitive details.",
            "Docs/Drive exports.",
            "Reporting handoff.",
        ],
        "blocked": [
            "Bulk appointment cancellation.",
            "Silent cancellation.",
            "Silent reschedule.",
            "Unapproved SMS/email/WhatsApp reminder send.",
            "Exposing patient/client data.",
            "Hidden calendar changes.",
            "Destructive appointment cleanup.",
            "Deleting appointment evidence.",
            "Committing credentials.",
        ],
    }


def _booking_sources() -> dict[str, dict[str, Any]]:
    return {
        "local-bookings": {
            "name": "Local Serena Booking Records",
            "status": "active_local",
            "role": "Local booking requests, appointment records, reminders, follow-ups, handoff plans, reports, and audit evidence.",
            "required_env": [],
            "objects": [
                "booking_requests",
                "appointments",
                "reminder_plans",
                "followup_plans",
                "handoff_records",
                "audit_reports",
            ],
            "notes": [
                "Available without external credentials.",
                "This is the v1 workflow evidence layer.",
            ],
        },
        "google-calendar": {
            "name": "Google Calendar",
            "status": "active_google_ready",
            "role": "Raw scheduling engine for availability checks, appointment creation, reschedules, cancellations, and Google Meet events.",
            "required_env": [
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "GOOGLE_REFRESH_TOKEN",
            ],
            "objects": [
                "calendar_events",
                "availability_windows",
                "google_meet_links",
                "event_attendees",
                "event_updates",
                "calendar_cancellations",
            ],
            "notes": [
                "Calendar operator is already complete.",
                "Bookings v1 prepares safe handoff; live calendar changes remain guarded.",
            ],
        },
        "compliance": {
            "name": "Serena Compliance",
            "status": "active_local",
            "role": "Guard patient/client/health/privacy/POPIA/HPCSA-sensitive appointment workflows.",
            "required_env": [],
            "objects": [
                "sensitivity_checks",
                "patient_data_guards",
                "external_share_review",
                "marketing_or_reminder_review",
            ],
            "notes": [
                "Run Compliance before external reminders or reports containing sensitive data.",
            ],
        },
        "docs-drive": {
            "name": "Google Docs / Google Drive",
            "status": "active_google_ready",
            "role": "Appointment summaries, booking packs, handoff docs, evidence storage, and reporting exports.",
            "required_env": [
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "GOOGLE_REFRESH_TOKEN",
                "GDRIVE_ROOT_FOLDER_ID",
            ],
            "objects": [
                "appointment_summary_docs",
                "booking_reports",
                "drive_evidence_files",
                "handoff_documents",
            ],
            "notes": [
                "Docs/Drive handoff must be approval-gated when patient/client data is included.",
            ],
        },
        "reporting": {
            "name": "Serena Reporting",
            "status": "active_local",
            "role": "Daily/weekly appointment summaries, no-show summaries, follow-up reports, and operational briefs.",
            "required_env": [],
            "objects": [
                "appointment_summary",
                "booking_report",
                "reminder_report",
                "followup_report",
            ],
            "notes": [
                "Use Reporting for shareable operational summaries.",
            ],
        },
        "accounting": {
            "name": "Serena Accounting",
            "status": "active_local",
            "role": "Booking-to-invoice/payment link later, consultation billing context, and payment readiness.",
            "required_env": [],
            "objects": [
                "invoice_plan",
                "payment_status",
                "booking_revenue_context",
            ],
            "notes": [
                "Accounting operator is complete v1.",
                "Live PayFast/Xero credentials remain future setup items.",
            ],
        },
    }


def _env_status() -> dict[str, Any]:
    sources = _booking_sources()
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


class _BookingsBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_bookings_status")
class SerenaBookingsStatusTool(_BookingsBaseTool):
    tool_id = "serena_bookings_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Bookings / Appointments / Reminders operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _bookings_root()
        sources = _booking_sources()
        env = _env_status()
        configured = [sid for sid, item in env.items() if item.get("configured")]

        return self._result(
            "Serena Bookings status\n\n"
            "- Status: active\n"
            "- Role: booking requests, appointments, reminders, follow-ups, Calendar handoff, no-show risk, and appointment reporting operator\n"
            f"- Sources registered: {len(sources)}\n"
            f"- Configured sources: {len(configured)}\n"
            "- Local booking records: active\n"
            "- Google Calendar handoff: ready/guarded\n"
            "- Docs/Drive handoff: ready/guarded\n"
            "- Compliance guardrails: active\n"
            "- Reporting handoff: active\n"
            "- Bulk cancellation: blocked\n"
            "- Silent calendar changes: blocked\n"
            "- Unapproved reminder send: blocked\n"
            "- Patient/client data exposure: blocked\n"
            "- Secret values exposed: no\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Requests: {root / 'requests'}\n"
            f"- Appointments: {root / 'appointments'}\n"
            f"- Reminders: {root / 'reminders'}\n"
            f"- Followups: {root / 'followups'}\n"
            f"- Handoff: {root / 'handoff'}\n"
            "- Hub adapter: pending future dashboard",
            metadata={
                "sources": sources,
                "env_status": env,
                "safety_policy": _safety_policy(),
                "hub_adapter": _hub_adapter_contract(),
                "secret_values_exposed": False,
            },
        )


@ToolRegistry.register("serena_bookings_env_check")
class SerenaBookingsEnvCheckTool(_BookingsBaseTool):
    tool_id = "serena_bookings_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check bookings/calendar environment without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _env_status()
        payload = {
            "report_type": "serena_bookings_env_check",
            "created_at": _timestamp(),
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", "env-check", payload)

        lines = [
            "Serena Bookings env check",
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


@ToolRegistry.register("serena_bookings_source_list")
class SerenaBookingsSourceListTool(_BookingsBaseTool):
    tool_id = "serena_bookings_source_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List registered bookings/appointment/reminder sources.",
            parameters={"type": "object", "properties": {}},
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        sources = _booking_sources()
        payload = {
            "report_type": "serena_bookings_source_list",
            "created_at": _timestamp(),
            "sources": sources,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("snapshots", "source-list", payload)

        lines = [
            "Serena Bookings source list",
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


@ToolRegistry.register("serena_bookings_source_info")
class SerenaBookingsSourceInfoTool(_BookingsBaseTool):
    tool_id = "serena_bookings_source_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show details for one bookings/appointment/reminder source.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                },
                "required": ["source"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        source_id = str(params.get("source") or "").strip()
        sources = _booking_sources()

        if source_id not in sources:
            return self._result(
                "Serena Bookings source-info failed\n\n"
                f"- Source: {source_id}\n"
                "- Error: source not found\n"
                "- Changes made: no",
                success=False,
            )

        source = sources[source_id]
        env = _env_status().get(source_id, {})
        payload = {
            "report_type": "serena_bookings_source_info",
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
            "Serena Bookings source info",
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


@ToolRegistry.register("serena_bookings_plan")
class SerenaBookingsPlanTool(_BookingsBaseTool):
    tool_id = "serena_bookings_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a bookings/appointments/reminders operation plan without external writes.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "business": {"type": "string"},
                    "patient_or_client": {"type": "string"},
                    "appointment_type": {"type": "string"},
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                },
                "required": ["goal"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "").strip()
        business = str(params.get("business") or "General Business").strip()
        patient_or_client = str(params.get("patient_or_client") or "not specified").strip()
        appointment_type = str(params.get("appointment_type") or "appointment").strip()
        date = str(params.get("date") or "not specified").strip()
        time_value = str(params.get("time") or "not specified").strip()

        steps = [
            "Identify business, patient/client, appointment type, date/time preference, and required duration.",
            "Classify whether the request includes patient/client/health-sensitive information.",
            "Create local booking plan or booking request first.",
            "Check Calendar availability through the Calendar operator when live scheduling is needed.",
            "Prepare calendar handoff only after details are clear.",
            "Prepare reminder and follow-up plan.",
            "Run Compliance before external reminder/reporting handoff when sensitive data is included.",
            "Report exact booking status and required approvals.",
            "Block bulk cancellations, silent calendar changes, patient data exposure, and unapproved reminder sending.",
        ]

        payload = {
            "report_type": "serena_bookings_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "business": business,
            "patient_or_client": patient_or_client,
            "appointment_type": appointment_type,
            "date": date,
            "time": time_value,
            "steps": steps,
            "external_api_called": False,
            "calendar_write_performed": False,
            "reminder_sent": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", goal or "bookings-plan", payload)

        return self._result(
            "Serena Bookings operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Business: {business}\n"
            f"- Patient/client: {patient_or_client}\n"
            f"- Appointment type: {appointment_type}\n"
            f"- Date: {date}\n"
            f"- Time: {time_value}\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Calendar write performed: no\n"
            "- Reminder sent: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


__all__ = [
    "SerenaBookingsStatusTool",
    "SerenaBookingsEnvCheckTool",
    "SerenaBookingsPlanTool",
    "SerenaBookingsSourceListTool",
    "SerenaBookingsSourceInfoTool",
]
