"""Native Serena Google Calendar operator tools.

Serena Google Calendar Full Operator v1 foundation:
- status
- env-check
- connect-check
- plan
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


GCAL_OUTPUT_ROOT = Path("outputs/google-calendar")

GCAL_REQUIRED_ENV = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
]


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "calendar"


def _calendar_root() -> Path:
    GCAL_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "plans", "snapshots"]:
        (GCAL_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return GCAL_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _calendar_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _env_report() -> dict[str, Any]:
    required = []
    missing = []

    for name in GCAL_REQUIRED_ENV:
        value = os.getenv(name, "")
        present = bool(value.strip())
        if not present:
            missing.append(name)
        required.append({
            "name": name,
            "present": present,
            "length": len(value) if value else 0,
        })

    optional_names = [
        "GOOGLE_CALENDAR_ID",
        "GCAL_CALENDAR_ID",
        "CALENDAR_ID",
        "TZ",
    ]

    optional = []
    for name in optional_names:
        value = os.getenv(name, "")
        optional.append({
            "name": name,
            "present": bool(value.strip()),
            "length": len(value) if value else 0,
        })

    return {
        "configured": len(missing) == 0,
        "missing_required": missing,
        "required": required,
        "optional": optional,
        "secret_values_exposed": False,
    }


def _calendar_id() -> str:
    return (
        os.getenv("GOOGLE_CALENDAR_ID", "").strip()
        or os.getenv("GCAL_CALENDAR_ID", "").strip()
        or os.getenv("CALENDAR_ID", "").strip()
        or "primary"
    )


def _get_calendar_service() -> Any:
    env = _env_report()
    if not env["configured"]:
        raise RuntimeError("Google Calendar is not configured. Missing required env vars: " + ", ".join(env["missing_required"]))

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except Exception as exc:
        raise RuntimeError("Google API Python dependencies are not available. Install google-api-python-client and google-auth if missing.") from exc

    creds = Credentials(
        token=None,
        refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
        ],
    )

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _iso_now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_timezone() -> str:
    return os.getenv("TZ", "").strip() or "Africa/Johannesburg"


def _safety_policy() -> dict[str, Any]:
    return {
        "allowed": [
            "Read calendar events.",
            "Search calendar events.",
            "Check availability.",
            "Create appointments and reminders.",
            "Create Google Meet events.",
            "Update and reschedule specific events.",
            "Add attendees with reporting.",
            "Cancel only specific targeted events with reporting.",
            "Produce daily and weekly briefs.",
        ],
        "guarded": [
            "Cancellation must target a specific event.",
            "Event creation must report title, time, calendar, attendees, and link.",
            "Attendee changes must be reported.",
            "Timezone should be explicit or defaulted consistently.",
        ],
        "blocked": [
            "Silent deletion.",
            "Bulk calendar deletion.",
            "Destructive calendar cleanup.",
            "Deleting without exact event targeting.",
            "Exposing credentials.",
            "Committing credentials.",
        ],
    }


class _GoogleCalendarBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_google_calendar_status")
class SerenaGoogleCalendarStatusTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Google Calendar operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _calendar_root()
        env = _env_report()

        return self._result(
            "Serena Google Calendar status\n\n"
            "- Status: active\n"
            "- Role: professional calendar, scheduling, reminders, availability, and event operator\n"
            f"- Configured: {'yes' if env['configured'] else 'no'}\n"
            f"- Calendar ID: {_calendar_id()}\n"
            f"- Default timezone: {_default_timezone()}\n"
            "- Secret values exposed: no\n"
            "- Silent deletion: blocked\n"
            "- Bulk deletion: blocked\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Plans: {root / 'plans'}\n"
            f"- Snapshots: {root / 'snapshots'}",
            metadata={
                "configured": env["configured"],
                "calendar_id": _calendar_id(),
                "timezone": _default_timezone(),
                "output_root": str(root),
            },
        )


@ToolRegistry.register("serena_google_calendar_env_check")
class SerenaGoogleCalendarEnvCheckTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Google Calendar env configuration without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _env_report()

        payload = {
            "report_type": "serena_google_calendar_env_check",
            "created_at": _timestamp(),
            "env": env,
            "calendar_id": _calendar_id(),
            "timezone": _default_timezone(),
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", "env-check", payload)

        lines = [
            "Serena Google Calendar env check",
            "",
            f"- Configured: {'yes' if env['configured'] else 'no'}",
            f"- Missing required: {len(env['missing_required'])}",
            f"- Calendar ID: {_calendar_id()}",
            f"- Default timezone: {_default_timezone()}",
            "- Secret values exposed: no",
            f"- Report: {report_path}",
            "",
            "Required variables:",
        ]

        for item in env["required"]:
            lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")

        lines.extend(["", "Optional variables:"])
        for item in env["optional"]:
            lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")

        lines.extend(["", "Missing required:"])
        lines.extend(f"- {item}" for item in env["missing_required"]) if env["missing_required"] else lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_google_calendar_connect_check")
class SerenaGoogleCalendarConnectCheckTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_connect_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Connect to Google Calendar API and verify calendar access.",
            parameters={"type": "object", "properties": {}},
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            service = _get_calendar_service()
            calendar_id = _calendar_id()
            calendar = service.calendars().get(calendarId=calendar_id).execute()

            payload = {
                "report_type": "serena_google_calendar_connect_check",
                "created_at": _timestamp(),
                "connected": True,
                "calendar_id": calendar_id,
                "calendar_summary": calendar.get("summary"),
                "calendar_time_zone": calendar.get("timeZone"),
                "calendar_access_role": calendar.get("accessRole"),
                "changes_made": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", "connect-check", payload)

            return self._result(
                "Serena Google Calendar connection check\n\n"
                "- Connected: yes\n"
                f"- Calendar ID: {calendar_id}\n"
                f"- Calendar summary: {calendar.get('summary', 'unknown')}\n"
                f"- Calendar timezone: {calendar.get('timeZone', 'unknown')}\n"
                f"- Access role: {calendar.get('accessRole', 'unknown')}\n"
                "- Secret values exposed: no\n"
                "- Changes made: no\n"
                f"- Report: {report_path}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Google Calendar connection check failed\n\n"
                "- Connected: no\n"
                f"- Error: {exc}\n"
                "- Secret values exposed: no\n"
                "- Changes made: no",
                success=False,
            )


@ToolRegistry.register("serena_google_calendar_plan")
class SerenaGoogleCalendarPlanTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Calendar operation plan without API writes.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "operation": {"type": "string"},
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "attendees": {"type": "string"},
                },
                "required": ["goal"],
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "").strip()
        operation = str(params.get("operation") or "schedule").strip()
        date = str(params.get("date") or "").strip()
        time_value = str(params.get("time") or "").strip()
        attendees = str(params.get("attendees") or "").strip()
        env = _env_report()

        plan = {
            "report_type": "serena_google_calendar_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "operation": operation,
            "date": date,
            "time": time_value,
            "attendees": attendees,
            "configured": env["configured"],
            "calendar_id": _calendar_id(),
            "timezone": _default_timezone(),
            "steps": [
                "Check Google Calendar env configuration.",
                "Verify Google Calendar API connection.",
                "Read relevant schedule context.",
                "Check conflicts and availability when scheduling.",
                "Create/update/cancel only through command-specific validation.",
                "Report exact event title, time, calendar, attendees, links, and changed fields.",
                "Block silent or bulk deletion.",
            ],
            "calendar_api_called": False,
            "write_performed": False,
            "delete_performed": False,
            "changes_made": False,
        }
        plan_path = _save_json("plans", goal or operation or "calendar-plan", plan)

        return self._result(
            "Serena Google Calendar operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Operation: {operation}\n"
            f"- Date: {date or 'not specified'}\n"
            f"- Time: {time_value or 'not specified'}\n"
            f"- Attendees: {attendees or 'none specified'}\n"
            f"- Configured: {'yes' if env['configured'] else 'no'}\n"
            f"- Calendar ID: {_calendar_id()}\n"
            f"- Timezone: {_default_timezone()}\n"
            f"- Plan: {plan_path}\n"
            "- Calendar API called: no\n"
            "- Write performed: no\n"
            "- Delete performed: no\n"
            "- Changes made: no\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in plan["steps"]),
            metadata={**plan, "plan_path": str(plan_path)},
        )


__all__ = [
    "SerenaGoogleCalendarStatusTool",
    "SerenaGoogleCalendarEnvCheckTool",
    "SerenaGoogleCalendarConnectCheckTool",
    "SerenaGoogleCalendarPlanTool",
]
