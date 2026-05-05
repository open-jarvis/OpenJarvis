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


def _load_json_records(folder: str) -> list[dict[str, Any]]:
    root = BOOKINGS_OUTPUT_ROOT / folder
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


def _booking_record_summary(record: dict[str, Any]) -> str:
    return (
        f"{record.get('booking_id') or record.get('request_id')} | "
        f"{record.get('patient_or_client', 'unknown')} | "
        f"{record.get('appointment_type', 'appointment')} | "
        f"{record.get('date', 'date?')} {record.get('time', 'time?')} | "
        f"status={record.get('status', 'unknown')}"
    )


@ToolRegistry.register("serena_bookings_availability_plan")
class SerenaBookingsAvailabilityPlanTool(_BookingsBaseTool):
    tool_id = "serena_bookings_availability_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create an availability checking plan without calling Calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "date": {"type": "string"},
                    "days": {"type": "integer"},
                    "duration_minutes": {"type": "integer"},
                    "work_start": {"type": "string"},
                    "work_end": {"type": "string"},
                    "appointment_type": {"type": "string"},
                },
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "General Business").strip()
        date = str(params.get("date") or "today").strip()
        days = int(params.get("days") or 1)
        duration = int(params.get("duration_minutes") or 60)
        work_start = str(params.get("work_start") or "08:00").strip()
        work_end = str(params.get("work_end") or "17:00").strip()
        appointment_type = str(params.get("appointment_type") or "appointment").strip()

        steps = [
            "Confirm business/calendar context.",
            "Confirm appointment type and required duration.",
            "Use Google Calendar availability when live scheduling is required.",
            "Avoid exposing patient/client context in public calendar details.",
            "Prepare candidate slots and required approvals.",
            "Create local booking request before calendar write.",
        ]

        payload = {
            "report_type": "serena_bookings_availability_plan",
            "created_at": _timestamp(),
            "business": business,
            "date": date,
            "days": days,
            "duration_minutes": duration,
            "work_start": work_start,
            "work_end": work_end,
            "appointment_type": appointment_type,
            "steps": steps,
            "external_api_called": False,
            "calendar_read_performed": False,
            "calendar_write_performed": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"availability-plan-{business}-{date}", payload)

        return self._result(
            "Serena availability plan\n\n"
            f"- Business: {business}\n"
            f"- Date: {date}\n"
            f"- Days: {days}\n"
            f"- Duration minutes: {duration}\n"
            f"- Work window: {work_start}-{work_end}\n"
            f"- Appointment type: {appointment_type}\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Calendar read performed: no\n"
            "- Calendar write performed: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_bookings_booking_request")
class SerenaBookingsBookingRequestTool(_BookingsBaseTool):
    tool_id = "serena_bookings_booking_request"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local booking request record.",
            parameters={
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "business": {"type": "string"},
                    "patient_or_client": {"type": "string"},
                    "appointment_type": {"type": "string"},
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "contact": {"type": "string"},
                    "notes": {"type": "string"},
                    "sensitive": {"type": "boolean"},
                },
                "required": ["patient_or_client"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        request_id = str(params.get("request_id") or f"BR-{_timestamp()}").strip()
        business = str(params.get("business") or "General Business").strip()
        patient_or_client = str(params.get("patient_or_client") or "").strip()
        appointment_type = str(params.get("appointment_type") or "appointment").strip()
        date = str(params.get("date") or "not specified").strip()
        time_value = str(params.get("time") or "not specified").strip()
        duration = int(params.get("duration_minutes") or 60)
        contact = str(params.get("contact") or "").strip()
        notes = str(params.get("notes") or "").strip()
        sensitive = bool(params.get("sensitive") or False)

        record = {
            "record_type": "booking_request",
            "created_at": _timestamp(),
            "request_id": request_id,
            "business": business,
            "patient_or_client": patient_or_client,
            "appointment_type": appointment_type,
            "date": date,
            "time": time_value,
            "duration_minutes": duration,
            "contact": contact,
            "notes": notes,
            "sensitive": sensitive,
            "status": "requested",
            "booking_request_created": True,
            "external_api_called": False,
            "calendar_write_performed": False,
            "reminder_sent": False,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("requests", f"booking-request-{request_id}", record)

        return self._result(
            "Serena booking request created\n\n"
            f"- Request ID: {request_id}\n"
            f"- Business: {business}\n"
            f"- Patient/client: {patient_or_client}\n"
            f"- Appointment type: {appointment_type}\n"
            f"- Date: {date}\n"
            f"- Time: {time_value}\n"
            f"- Duration minutes: {duration}\n"
            f"- Sensitive: {'yes' if sensitive else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Booking request created: yes\n"
            "- External API called: no\n"
            "- Calendar write performed: no\n"
            "- Reminder sent: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_bookings_create_booking")
class SerenaBookingsCreateBookingTool(_BookingsBaseTool):
    tool_id = "serena_bookings_create_booking"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local appointment/booking record. Does not write to Calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "business": {"type": "string"},
                    "patient_or_client": {"type": "string"},
                    "appointment_type": {"type": "string"},
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "location": {"type": "string"},
                    "contact": {"type": "string"},
                    "calendar_event_id": {"type": "string"},
                    "status": {"type": "string"},
                    "notes": {"type": "string"},
                    "sensitive": {"type": "boolean"},
                },
                "required": ["patient_or_client", "date", "time"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or f"BK-{_timestamp()}").strip()
        business = str(params.get("business") or "General Business").strip()
        patient_or_client = str(params.get("patient_or_client") or "").strip()
        appointment_type = str(params.get("appointment_type") or "appointment").strip()
        date = str(params.get("date") or "").strip()
        time_value = str(params.get("time") or "").strip()
        duration = int(params.get("duration_minutes") or 60)
        location = str(params.get("location") or "").strip()
        contact = str(params.get("contact") or "").strip()
        calendar_event_id = str(params.get("calendar_event_id") or "").strip()
        status = str(params.get("status") or "scheduled_local").strip()
        notes = str(params.get("notes") or "").strip()
        sensitive = bool(params.get("sensitive") or False)

        record = {
            "record_type": "booking",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "business": business,
            "patient_or_client": patient_or_client,
            "appointment_type": appointment_type,
            "date": date,
            "time": time_value,
            "duration_minutes": duration,
            "location": location,
            "contact": contact,
            "calendar_event_id": calendar_event_id,
            "status": status,
            "notes": notes,
            "sensitive": sensitive,
            "booking_created": True,
            "calendar_write_performed": False,
            "reminder_sent": False,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("appointments", f"booking-{booking_id}", record)

        return self._result(
            "Serena local booking created\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Business: {business}\n"
            f"- Patient/client: {patient_or_client}\n"
            f"- Appointment type: {appointment_type}\n"
            f"- Date: {date}\n"
            f"- Time: {time_value}\n"
            f"- Duration minutes: {duration}\n"
            f"- Location: {location or 'not specified'}\n"
            f"- Calendar event ID: {calendar_event_id or 'not linked'}\n"
            f"- Status: {status}\n"
            f"- Sensitive: {'yes' if sensitive else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Booking created: yes\n"
            "- Calendar write performed: no\n"
            "- Reminder sent: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_bookings_booking_info")
class SerenaBookingsBookingInfoTool(_BookingsBaseTool):
    tool_id = "serena_bookings_booking_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show local booking details by booking ID.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                },
                "required": ["booking_id"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        records = _load_json_records("appointments")

        match = None
        for record in records:
            if str(record.get("booking_id") or "") == booking_id:
                match = record
                break

        if not match:
            return self._result(
                "Serena booking info failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        return self._result(
            "Serena booking info\n\n"
            f"- Booking ID: {match.get('booking_id')}\n"
            f"- Business: {match.get('business')}\n"
            f"- Patient/client: {match.get('patient_or_client')}\n"
            f"- Appointment type: {match.get('appointment_type')}\n"
            f"- Date: {match.get('date')}\n"
            f"- Time: {match.get('time')}\n"
            f"- Duration minutes: {match.get('duration_minutes')}\n"
            f"- Location: {match.get('location') or 'not specified'}\n"
            f"- Calendar event ID: {match.get('calendar_event_id') or 'not linked'}\n"
            f"- Status: {match.get('status')}\n"
            f"- Sensitive: {'yes' if match.get('sensitive') else 'no'}\n"
            f"- Record: {match.get('_path')}\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata=match,
        )


@ToolRegistry.register("serena_bookings_booking_list")
class SerenaBookingsBookingListTool(_BookingsBaseTool):
    tool_id = "serena_bookings_booking_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List local booking records.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "").strip()
        status_filter = str(params.get("status") or "").strip()
        limit = int(params.get("limit") or 20)

        records = _load_json_records("appointments")

        selected = []
        for record in records:
            if business and str(record.get("business") or "") != business:
                continue
            if status_filter and str(record.get("status") or "") != status_filter:
                continue
            selected.append(record)

        payload = {
            "report_type": "serena_bookings_booking_list",
            "created_at": _timestamp(),
            "business": business or "all",
            "status_filter": status_filter or "all",
            "booking_count": len(selected),
            "booking_paths": [item.get("_path") for item in selected],
            "external_api_called": False,
            "calendar_read_performed": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"booking-list-{business or 'all'}", payload)

        lines = [
            "Serena booking list",
            "",
            f"- Business: {business or 'all'}",
            f"- Status filter: {status_filter or 'all'}",
            f"- Bookings found: {len(selected)}",
            f"- Report: {report_path}",
            "- External API called: no",
            "- Calendar read performed: no",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Bookings:",
        ]

        if selected:
            for record in selected[:limit]:
                lines.append(f"- {_booking_record_summary(record)}")
        else:
            lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_bookings_reschedule_booking")
class SerenaBookingsRescheduleBookingTool(_BookingsBaseTool):
    tool_id = "serena_bookings_reschedule_booking"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local booking reschedule plan. Does not update Calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "new_date": {"type": "string"},
                    "new_time": {"type": "string"},
                    "reason": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["booking_id", "new_date", "new_time"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        new_date = str(params.get("new_date") or "").strip()
        new_time = str(params.get("new_time") or "").strip()
        reason = str(params.get("reason") or "Reschedule requested.").strip()
        approved = bool(params.get("approved") or False)

        records = _load_json_records("appointments")
        match = None
        for record in records:
            if str(record.get("booking_id") or "") == booking_id:
                match = record
                break

        if not match:
            return self._result(
                "Serena booking reschedule failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Calendar write performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        payload = {
            "report_type": "serena_bookings_reschedule_plan",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "business": match.get("business"),
            "patient_or_client": match.get("patient_or_client"),
            "appointment_type": match.get("appointment_type"),
            "old_date": match.get("date"),
            "old_time": match.get("time"),
            "new_date": new_date,
            "new_time": new_time,
            "reason": reason,
            "approved": approved,
            "calendar_event_id": match.get("calendar_event_id"),
            "sensitive": bool(match.get("sensitive")),
            "reschedule_planned": True,
            "calendar_write_performed": False,
            "reminder_sent": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"reschedule-{booking_id}", payload)

        return self._result(
            "Serena booking reschedule plan created\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Patient/client: {match.get('patient_or_client')}\n"
            f"- Old time: {match.get('date')} {match.get('time')}\n"
            f"- New time: {new_date} {new_time}\n"
            f"- Reason: {reason}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Calendar event ID: {match.get('calendar_event_id') or 'not linked'}\n"
            f"- Report: {report_path}\n"
            "- Reschedule planned: yes\n"
            "- Calendar write performed: no\n"
            "- Reminder sent: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Next safe step:\n"
            "- Use bookings calendar-update-plan or calendar handoff after approval.",
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_bookings_cancel_booking")
class SerenaBookingsCancelBookingTool(_BookingsBaseTool):
    tool_id = "serena_bookings_cancel_booking"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local booking cancellation plan. Does not cancel Calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["booking_id"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        reason = str(params.get("reason") or "Cancellation requested.").strip()
        approved = bool(params.get("approved") or False)

        if not approved:
            return self._result(
                "Serena booking cancellation blocked\n\n"
                f"- Booking ID: {booking_id}\n"
                f"- Reason: {reason}\n"
                "- Blocked reason: cancellation requires explicit approval.\n"
                "- Cancellation planned: no\n"
                "- Calendar write performed: no\n"
                "- Delete performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        records = _load_json_records("appointments")
        match = None
        for record in records:
            if str(record.get("booking_id") or "") == booking_id:
                match = record
                break

        if not match:
            return self._result(
                "Serena booking cancellation failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Calendar write performed: no\n"
                "- Delete performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        payload = {
            "report_type": "serena_bookings_cancel_plan",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "business": match.get("business"),
            "patient_or_client": match.get("patient_or_client"),
            "appointment_type": match.get("appointment_type"),
            "date": match.get("date"),
            "time": match.get("time"),
            "reason": reason,
            "approved": approved,
            "calendar_event_id": match.get("calendar_event_id"),
            "sensitive": bool(match.get("sensitive")),
            "cancellation_planned": True,
            "calendar_write_performed": False,
            "appointment_deleted": False,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"cancel-{booking_id}", payload)

        return self._result(
            "Serena booking cancellation plan created\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Patient/client: {match.get('patient_or_client')}\n"
            f"- Appointment: {match.get('appointment_type')} | {match.get('date')} {match.get('time')}\n"
            f"- Reason: {reason}\n"
            f"- Approved: yes\n"
            f"- Calendar event ID: {match.get('calendar_event_id') or 'not linked'}\n"
            f"- Report: {report_path}\n"
            "- Cancellation planned: yes\n"
            "- Calendar write performed: no\n"
            "- Appointment deleted: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Next safe step:\n"
            "- Use bookings calendar-cancel-plan or Calendar operator cancellation only with explicit event targeting.",
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_bookings_cancellation_policy")
class SerenaBookingsCancellationPolicyTool(_BookingsBaseTool):
    tool_id = "serena_bookings_cancellation_policy"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create or display a local appointment cancellation policy note.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "notice_hours": {"type": "integer"},
                    "notes": {"type": "string"},
                },
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "General Business").strip()
        notice_hours = int(params.get("notice_hours") or 24)
        notes = str(params.get("notes") or "").strip()

        policy = [
            f"Preferred cancellation/reschedule notice: {notice_hours} hours.",
            "Cancellations must target one specific booking.",
            "Bulk cancellations are blocked.",
            "Silent calendar cancellation is blocked.",
            "Patient/client-sensitive details must not be exposed in cancellation messages.",
            "Cancellation fees/payment implications must be handled by Accounting/PayFast policy later.",
            "Calendar cancellation handoff requires exact event targeting and approval.",
        ]

        payload = {
            "report_type": "serena_bookings_cancellation_policy",
            "created_at": _timestamp(),
            "business": business,
            "notice_hours": notice_hours,
            "notes": notes,
            "policy": policy,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"cancellation-policy-{business}", payload)

        return self._result(
            "Serena cancellation policy\n\n"
            f"- Business: {business}\n"
            f"- Notice hours: {notice_hours}\n"
            f"- Report: {report_path}\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Policy:\n"
            + "\n".join(f"- {item}" for item in policy),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_bookings_no_show_policy")
class SerenaBookingsNoShowPolicyTool(_BookingsBaseTool):
    tool_id = "serena_bookings_no_show_policy"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create or display a local no-show policy and prevention workflow.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "General Business").strip()
        notes = str(params.get("notes") or "").strip()

        policy = [
            "Create reminders for upcoming appointments.",
            "Flag higher no-show risk when contact details are missing, reminder status is pending, or appointment was rescheduled repeatedly.",
            "Do not send reminders externally without approval.",
            "Do not include sensitive health details in reminders.",
            "Create follow-up plan for missed appointments.",
            "Preserve appointment evidence and reminder records.",
            "Use Reporting for no-show summaries.",
        ]

        payload = {
            "report_type": "serena_bookings_no_show_policy",
            "created_at": _timestamp(),
            "business": business,
            "notes": notes,
            "policy": policy,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"no-show-policy-{business}", payload)

        return self._result(
            "Serena no-show policy\n\n"
            f"- Business: {business}\n"
            f"- Report: {report_path}\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Policy:\n"
            + "\n".join(f"- {item}" for item in policy),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_bookings_reminder_plan")
class SerenaBookingsReminderPlanTool(_BookingsBaseTool):
    tool_id = "serena_bookings_reminder_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create an appointment reminder plan. Does not send reminders.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "channels": {"type": "string"},
                    "timing": {"type": "string"},
                    "message_type": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["booking_id"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        channels = str(params.get("channels") or "email/sms/whatsapp planned").strip()
        timing = str(params.get("timing") or "24 hours before appointment").strip()
        message_type = str(params.get("message_type") or "minimal appointment reminder").strip()
        notes = str(params.get("notes") or "").strip()

        records = _load_json_records("appointments")
        booking = next((r for r in records if str(r.get("booking_id") or "") == booking_id), None)

        if not booking:
            return self._result(
                "Serena reminder plan failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Reminder sent: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        safety_notes = [
            "Do not include sensitive health details in reminder content.",
            "Do not send reminders externally without approval.",
            "Use minimal wording: appointment date/time/location/contact only.",
            "Run Compliance before reminder send if content contains patient/client/health data.",
        ]

        payload = {
            "record_type": "reminder_plan",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "business": booking.get("business"),
            "patient_or_client": booking.get("patient_or_client"),
            "appointment_type": booking.get("appointment_type"),
            "date": booking.get("date"),
            "time": booking.get("time"),
            "channels": channels,
            "timing": timing,
            "message_type": message_type,
            "notes": notes,
            "sensitive": bool(booking.get("sensitive")),
            "safety_notes": safety_notes,
            "reminder_plan_created": True,
            "reminder_sent": False,
            "external_api_called": False,
            "calendar_write_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("reminders", f"reminder-plan-{booking_id}", payload)

        return self._result(
            "Serena reminder plan created\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Patient/client: {booking.get('patient_or_client')}\n"
            f"- Appointment: {booking.get('appointment_type')} | {booking.get('date')} {booking.get('time')}\n"
            f"- Channels: {channels}\n"
            f"- Timing: {timing}\n"
            f"- Message type: {message_type}\n"
            f"- Sensitive: {'yes' if booking.get('sensitive') else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Reminder plan created: yes\n"
            "- Reminder sent: no\n"
            "- External API called: no\n"
            "- Calendar write performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Safety notes:\n"
            + "\n".join(f"- {item}" for item in safety_notes),
            metadata={**payload, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_bookings_reminder_schedule")
class SerenaBookingsReminderScheduleTool(_BookingsBaseTool):
    tool_id = "serena_bookings_reminder_schedule"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local reminder schedule record. Does not send reminders.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "reminder_time": {"type": "string"},
                    "channel": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "message": {"type": "string"},
                },
                "required": ["booking_id", "reminder_time"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        reminder_time = str(params.get("reminder_time") or "").strip()
        channel = str(params.get("channel") or "manual/local").strip()
        approved = bool(params.get("approved") or False)
        message = str(params.get("message") or "").strip()

        records = _load_json_records("appointments")
        booking = next((r for r in records if str(r.get("booking_id") or "") == booking_id), None)

        if not booking:
            return self._result(
                "Serena reminder schedule failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Reminder schedule created: no\n"
                "- Reminder sent: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if message and bool(booking.get("sensitive")) and not approved:
            return self._result(
                "Serena reminder schedule blocked\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Reason: sensitive reminder message requires approval before scheduling/sending.\n"
                "- Reminder schedule created: no\n"
                "- Reminder sent: no\n"
                "- External API called: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        record = {
            "record_type": "reminder_schedule",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "business": booking.get("business"),
            "patient_or_client": booking.get("patient_or_client"),
            "appointment_type": booking.get("appointment_type"),
            "date": booking.get("date"),
            "time": booking.get("time"),
            "reminder_time": reminder_time,
            "channel": channel,
            "approved": approved,
            "message_preview": message[:300],
            "status": "scheduled_local",
            "sensitive": bool(booking.get("sensitive")),
            "reminder_schedule_created": True,
            "reminder_sent": False,
            "external_api_called": False,
            "calendar_write_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("reminders", f"reminder-schedule-{booking_id}", record)

        return self._result(
            "Serena reminder schedule created\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Reminder time: {reminder_time}\n"
            f"- Channel: {channel}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Status: scheduled_local\n"
            f"- Sensitive: {'yes' if booking.get('sensitive') else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Reminder schedule created: yes\n"
            "- Reminder sent: no\n"
            "- External API called: no\n"
            "- Calendar write performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_bookings_reminder_status")
class SerenaBookingsReminderStatusTool(_BookingsBaseTool):
    tool_id = "serena_bookings_reminder_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show local reminder status for a booking.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                },
                "required": ["booking_id"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        reminders = _load_json_records("reminders")
        selected = [r for r in reminders if str(r.get("booking_id") or "") == booking_id]

        payload = {
            "report_type": "serena_bookings_reminder_status",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "reminder_records": len(selected),
            "records": selected,
            "external_api_called": False,
            "reminder_sent": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"reminder-status-{booking_id}", payload)

        lines = [
            "Serena reminder status",
            "",
            f"- Booking ID: {booking_id}",
            f"- Reminder records: {len(selected)}",
            f"- Report: {report_path}",
            "- External API called: no",
            "- Reminder sent: no",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Records:",
        ]

        if selected:
            for r in selected[:20]:
                lines.append(
                    f"- {r.get('record_type')} | status={r.get('status', 'planned')} | channel={r.get('channel', r.get('channels', 'n/a'))} | time={r.get('reminder_time', r.get('timing', 'n/a'))}"
                )
        else:
            lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_bookings_no_show_risk")
class SerenaBookingsNoShowRiskTool(_BookingsBaseTool):
    tool_id = "serena_bookings_no_show_risk"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Estimate no-show risk from local booking/reminder data.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                },
                "required": ["booking_id"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        records = _load_json_records("appointments")
        booking = next((r for r in records if str(r.get("booking_id") or "") == booking_id), None)

        if not booking:
            return self._result(
                "Serena no-show risk failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        reminders = [r for r in _load_json_records("reminders") if str(r.get("booking_id") or "") == booking_id]
        score = 0
        reasons = []

        if not str(booking.get("contact") or "").strip():
            score += 30
            reasons.append("Missing contact details.")

        if not reminders:
            score += 30
            reasons.append("No reminder plan/schedule found.")

        if bool(booking.get("sensitive")):
            score += 10
            reasons.append("Sensitive appointment requires careful approved reminder workflow.")

        if str(booking.get("calendar_event_id") or "").strip() == "":
            score += 15
            reasons.append("No linked Calendar event ID.")

        if str(booking.get("status") or "").lower() not in {"scheduled", "scheduled_local", "confirmed"}:
            score += 15
            reasons.append("Booking status is not confirmed/scheduled.")

        risk = "low"
        if score >= 60:
            risk = "high"
        elif score >= 30:
            risk = "medium"

        payload = {
            "report_type": "serena_bookings_no_show_risk",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "business": booking.get("business"),
            "patient_or_client": booking.get("patient_or_client"),
            "score": score,
            "risk": risk,
            "reasons": reasons,
            "reminder_records": len(reminders),
            "external_api_called": False,
            "reminder_sent": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"no-show-risk-{booking_id}", payload)

        return self._result(
            "Serena no-show risk report\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Patient/client: {booking.get('patient_or_client')}\n"
            f"- Risk: {risk}\n"
            f"- Score: {score}\n"
            f"- Reminder records: {len(reminders)}\n"
            f"- Report: {report_path}\n"
            "- External API called: no\n"
            "- Reminder sent: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Reasons:\n"
            + ("\n".join(f"- {item}" for item in reasons) if reasons else "- none"),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_bookings_follow_up_plan")
class SerenaBookingsFollowUpPlanTool(_BookingsBaseTool):
    tool_id = "serena_bookings_follow_up_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a follow-up plan for an appointment. Does not send external messages.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "timing": {"type": "string"},
                    "channel": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["booking_id"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        reason = str(params.get("reason") or "Follow-up after appointment.").strip()
        timing = str(params.get("timing") or "after appointment").strip()
        channel = str(params.get("channel") or "manual/local").strip()
        notes = str(params.get("notes") or "").strip()

        records = _load_json_records("appointments")
        booking = next((r for r in records if str(r.get("booking_id") or "") == booking_id), None)

        if not booking:
            return self._result(
                "Serena follow-up plan failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Follow-up plan created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Confirm appointment outcome/status.",
            "Confirm follow-up reason and appropriate timing.",
            "Avoid sensitive details in external messages.",
            "Run Compliance before sending patient/client/health-related follow-up externally.",
            "Create Reporting handoff if this belongs in daily/weekly appointment report.",
        ]

        payload = {
            "record_type": "follow_up_plan",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "business": booking.get("business"),
            "patient_or_client": booking.get("patient_or_client"),
            "appointment_type": booking.get("appointment_type"),
            "date": booking.get("date"),
            "time": booking.get("time"),
            "reason": reason,
            "timing": timing,
            "channel": channel,
            "notes": notes,
            "steps": steps,
            "sensitive": bool(booking.get("sensitive")),
            "follow_up_plan_created": True,
            "external_message_sent": False,
            "external_api_called": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("followups", f"follow-up-{booking_id}", payload)

        return self._result(
            "Serena follow-up plan created\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Patient/client: {booking.get('patient_or_client')}\n"
            f"- Reason: {reason}\n"
            f"- Timing: {timing}\n"
            f"- Channel: {channel}\n"
            f"- Sensitive: {'yes' if booking.get('sensitive') else 'no'}\n"
            f"- Record: {record_path}\n"
            "- Follow-up plan created: yes\n"
            "- External message sent: no\n"
            "- External API called: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "record_path": str(record_path)},
        )


def _get_booking_or_fail(booking_id: str) -> dict[str, Any] | None:
    records = _load_json_records("appointments")
    return next((r for r in records if str(r.get("booking_id") or "") == booking_id), None)


@ToolRegistry.register("serena_bookings_calendar_handoff")
class SerenaBookingsCalendarHandoffTool(_BookingsBaseTool):
    tool_id = "serena_bookings_calendar_handoff"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Calendar handoff record for a booking. Does not write to Calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "operation": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["booking_id"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        operation = str(params.get("operation") or "create").strip().lower()
        approved = bool(params.get("approved") or False)
        notes = str(params.get("notes") or "").strip()

        booking = _get_booking_or_fail(booking_id)
        if not booking:
            return self._result(
                "Serena Calendar handoff failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Calendar write performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        event_title = f"{booking.get('appointment_type', 'Appointment')} - {booking.get('patient_or_client', 'Client')}"
        safe_event_title = f"{booking.get('appointment_type', 'Appointment')}"
        event_description = (
            "Created from Serena Bookings handoff. "
            "Avoid sensitive patient/client details in public calendar fields."
        )

        payload = {
            "record_type": "calendar_handoff",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "operation": operation,
            "approved": approved,
            "business": booking.get("business"),
            "patient_or_client": booking.get("patient_or_client"),
            "appointment_type": booking.get("appointment_type"),
            "date": booking.get("date"),
            "time": booking.get("time"),
            "duration_minutes": booking.get("duration_minutes"),
            "location": booking.get("location"),
            "calendar_event_id": booking.get("calendar_event_id"),
            "sensitive": bool(booking.get("sensitive")),
            "recommended_calendar_title": safe_event_title if booking.get("sensitive") else event_title,
            "calendar_description": event_description,
            "notes": notes,
            "handoff_created": True,
            "external_api_called": False,
            "calendar_write_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("handoff", f"calendar-handoff-{booking_id}-{operation}", payload)

        return self._result(
            "Serena Calendar handoff created\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Operation: {operation}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Appointment: {booking.get('appointment_type')} | {booking.get('date')} {booking.get('time')}\n"
            f"- Sensitive: {'yes' if booking.get('sensitive') else 'no'}\n"
            f"- Recommended Calendar title: {payload['recommended_calendar_title']}\n"
            f"- Calendar event ID: {booking.get('calendar_event_id') or 'not linked'}\n"
            f"- Record: {record_path}\n"
            "- Handoff created: yes\n"
            "- External API called: no\n"
            "- Calendar write performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Next safe step:\n"
            "- Use the completed Calendar operator with explicit approval if a live Calendar write is required.",
            metadata={**payload, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_bookings_calendar_create_plan")
class SerenaBookingsCalendarCreatePlanTool(_BookingsBaseTool):
    tool_id = "serena_bookings_calendar_create_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Calendar event creation plan for a booking. Does not write to Calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "add_meet": {"type": "boolean"},
                    "approved": {"type": "boolean"},
                },
                "required": ["booking_id"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        add_meet = bool(params.get("add_meet") or False)
        approved = bool(params.get("approved") or False)

        booking = _get_booking_or_fail(booking_id)
        if not booking:
            return self._result(
                "Serena Calendar create plan failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Calendar write performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Confirm booking details and Calendar target.",
            "Use minimal Calendar title if sensitive patient/client data is involved.",
            "Create event only with explicit approval.",
            "Attach Google Meet link only when useful and approved.",
            "Report event title, date, time, calendar, attendees, Meet link, and event ID.",
            "Store Calendar event ID back into booking record in a future approved update workflow.",
        ]

        payload = {
            "report_type": "serena_bookings_calendar_create_plan",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "business": booking.get("business"),
            "patient_or_client": booking.get("patient_or_client"),
            "appointment_type": booking.get("appointment_type"),
            "date": booking.get("date"),
            "time": booking.get("time"),
            "duration_minutes": booking.get("duration_minutes"),
            "location": booking.get("location"),
            "sensitive": bool(booking.get("sensitive")),
            "add_google_meet": add_meet,
            "approved": approved,
            "steps": steps,
            "external_api_called": False,
            "calendar_write_performed": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"calendar-create-plan-{booking_id}", payload)

        return self._result(
            "Serena Calendar create plan\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Appointment: {booking.get('appointment_type')} | {booking.get('date')} {booking.get('time')}\n"
            f"- Add Google Meet: {'yes' if add_meet else 'no'}\n"
            f"- Approved: {'yes' if approved else 'no'}\n"
            f"- Sensitive: {'yes' if booking.get('sensitive') else 'no'}\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Calendar write performed: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_bookings_calendar_update_plan")
class SerenaBookingsCalendarUpdatePlanTool(_BookingsBaseTool):
    tool_id = "serena_bookings_calendar_update_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Calendar event update/reschedule plan for a booking. Does not write to Calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "new_date": {"type": "string"},
                    "new_time": {"type": "string"},
                    "reason": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["booking_id"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        new_date = str(params.get("new_date") or "").strip()
        new_time = str(params.get("new_time") or "").strip()
        reason = str(params.get("reason") or "Calendar update requested.").strip()
        approved = bool(params.get("approved") or False)

        booking = _get_booking_or_fail(booking_id)
        if not booking:
            return self._result(
                "Serena Calendar update plan failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Calendar write performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if not approved:
            return self._result(
                "Serena Calendar update plan blocked\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Reason: Calendar update/reschedule requires explicit approval.\n"
                "- Calendar write performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Confirm exact Calendar event ID before update.",
            "Confirm new date/time and duration.",
            "Avoid sensitive details in public Calendar fields.",
            "Update only one exact event.",
            "Report old and new time and event ID.",
            "Create reminder/follow-up adjustment plan after update.",
        ]

        payload = {
            "report_type": "serena_bookings_calendar_update_plan",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "calendar_event_id": booking.get("calendar_event_id"),
            "old_date": booking.get("date"),
            "old_time": booking.get("time"),
            "new_date": new_date,
            "new_time": new_time,
            "reason": reason,
            "approved": approved,
            "steps": steps,
            "external_api_called": False,
            "calendar_write_performed": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"calendar-update-plan-{booking_id}", payload)

        return self._result(
            "Serena Calendar update plan\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Calendar event ID: {booking.get('calendar_event_id') or 'not linked'}\n"
            f"- Old time: {booking.get('date')} {booking.get('time')}\n"
            f"- New time: {new_date or 'not specified'} {new_time or 'not specified'}\n"
            f"- Reason: {reason}\n"
            f"- Approved: yes\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Calendar write performed: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_bookings_calendar_cancel_plan")
class SerenaBookingsCalendarCancelPlanTool(_BookingsBaseTool):
    tool_id = "serena_bookings_calendar_cancel_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Calendar event cancellation plan for a booking. Does not cancel Calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["booking_id"],
            },
            category="serena_bookings",
        )

    def execute(self, **params: Any) -> ToolResult:
        booking_id = str(params.get("booking_id") or "").strip()
        reason = str(params.get("reason") or "Calendar cancellation requested.").strip()
        approved = bool(params.get("approved") or False)

        booking = _get_booking_or_fail(booking_id)
        if not booking:
            return self._result(
                "Serena Calendar cancel plan failed\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Error: booking not found\n"
                "- Calendar write performed: no\n"
                "- Delete performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        if not approved:
            return self._result(
                "Serena Calendar cancel plan blocked\n\n"
                f"- Booking ID: {booking_id}\n"
                "- Reason: Calendar cancellation requires explicit approval.\n"
                "- Calendar write performed: no\n"
                "- Delete performed: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        steps = [
            "Confirm exact Calendar event ID before cancellation.",
            "Cancel only one exact event.",
            "Do not bulk-cancel appointments.",
            "Do not delete local booking evidence.",
            "Report cancellation reason and event ID.",
            "Create follow-up plan if needed.",
        ]

        payload = {
            "report_type": "serena_bookings_calendar_cancel_plan",
            "created_at": _timestamp(),
            "booking_id": booking_id,
            "calendar_event_id": booking.get("calendar_event_id"),
            "reason": reason,
            "approved": approved,
            "steps": steps,
            "external_api_called": False,
            "calendar_write_performed": False,
            "calendar_cancelled": False,
            "appointment_deleted": False,
            "delete_performed": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"calendar-cancel-plan-{booking_id}", payload)

        return self._result(
            "Serena Calendar cancel plan\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Calendar event ID: {booking.get('calendar_event_id') or 'not linked'}\n"
            f"- Reason: {reason}\n"
            f"- Approved: yes\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Calendar write performed: no\n"
            "- Calendar cancelled: no\n"
            "- Appointment deleted: no\n"
            "- Delete performed: no\n"
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
    "SerenaBookingsBookingListTool",
    "SerenaBookingsNoShowPolicyTool",
    "SerenaBookingsFollowUpPlanTool",
    "SerenaBookingsCalendarCancelPlanTool",
    "SerenaBookingsCalendarUpdatePlanTool",
    "SerenaBookingsCalendarCreatePlanTool",
    "SerenaBookingsCalendarHandoffTool",
    "SerenaBookingsNoShowRiskTool",
    "SerenaBookingsReminderStatusTool",
    "SerenaBookingsReminderScheduleTool",
    "SerenaBookingsReminderPlanTool",
    "SerenaBookingsCancellationPolicyTool",
    "SerenaBookingsCancelBookingTool",
    "SerenaBookingsRescheduleBookingTool",
    "SerenaBookingsBookingInfoTool",
    "SerenaBookingsCreateBookingTool",
    "SerenaBookingsBookingRequestTool",
    "SerenaBookingsAvailabilityPlanTool",
]
