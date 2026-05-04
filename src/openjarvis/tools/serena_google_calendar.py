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


def _parse_date_start(date_text: str | None = None) -> datetime:
    value = str(date_text or "").strip().lower()
    now = datetime.now(timezone.utc)

    if not value or value == "today":
        local = datetime.now()
        return datetime(local.year, local.month, local.day, tzinfo=timezone.utc)

    if value == "tomorrow":
        local = datetime.now() + timedelta(days=1)
        return datetime(local.year, local.month, local.day, tzinfo=timezone.utc)

    if value in {"week", "this-week", "this week"}:
        local = datetime.now()
        start = local - timedelta(days=local.weekday())
        return datetime(start.year, start.month, start.day, tzinfo=timezone.utc)

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        raise RuntimeError(f"Could not parse date: {date_text}")


def _date_range(date_text: str | None = None, days: int = 1) -> tuple[str, str]:
    start = _parse_date_start(date_text)
    end = start + timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _format_event_line(event: dict[str, Any]) -> str:
    start = event.get("start", {})
    end = event.get("end", {})
    start_value = start.get("dateTime") or start.get("date") or "unknown"
    end_value = end.get("dateTime") or end.get("date") or "unknown"
    title = event.get("summary") or "(no title)"
    event_id = event.get("id") or ""
    link = event.get("htmlLink") or ""
    location = event.get("location") or ""
    return f"- {start_value} -> {end_value} | {title} | id={event_id} | location={location} | link={link}"


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "description": event.get("description"),
        "location": event.get("location"),
        "start": event.get("start"),
        "end": event.get("end"),
        "htmlLink": event.get("htmlLink"),
        "hangoutLink": event.get("hangoutLink"),
        "attendees": event.get("attendees", []),
        "status": event.get("status"),
        "creator": event.get("creator"),
        "organizer": event.get("organizer"),
    }


def _list_events(time_min: str, time_max: str, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
    service = _get_calendar_service()
    result = service.events().list(
        calendarId=_calendar_id(),
        timeMin=time_min,
        timeMax=time_max,
        q=query or None,
        maxResults=limit,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return result.get("items", [])


@ToolRegistry.register("serena_google_calendar_today")
class SerenaGoogleCalendarTodayTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_today"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read today's Google Calendar schedule.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            limit = int(params.get("limit") or 20)
            time_min, time_max = _date_range("today", days=1)
            events = _list_events(time_min, time_max, limit=limit)

            payload = {
                "report_type": "serena_google_calendar_today",
                "created_at": _timestamp(),
                "calendar_id": _calendar_id(),
                "time_min": time_min,
                "time_max": time_max,
                "events": [_event_summary(item) for item in events],
                "changes_made": False,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("snapshots", "today", payload)

            lines = [
                "Serena Google Calendar today",
                "",
                f"- Calendar ID: {_calendar_id()}",
                f"- Time range: {time_min} to {time_max}",
                f"- Events found: {len(events)}",
                f"- Snapshot: {report_path}",
                "- Changes made: no",
                "- Delete performed: no",
                "",
                "Events:",
            ]
            lines.extend(_format_event_line(item) for item in events) if events else lines.append("- none")

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(
                "Serena Google Calendar today failed\n\n"
                f"- Error: {exc}\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Note:\n"
                "- If this says invalid_scope, Dr Piet still needs to approve the new Calendar-scoped Google token.",
                success=False,
            )


@ToolRegistry.register("serena_google_calendar_upcoming")
class SerenaGoogleCalendarUpcomingTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_upcoming"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read upcoming Google Calendar events.",
            parameters={
                "type": "object",
                "properties": {
                    "days": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            days = int(params.get("days") or 7)
            limit = int(params.get("limit") or 30)
            time_min = datetime.now(timezone.utc).isoformat()
            time_max = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            events = _list_events(time_min, time_max, limit=limit)

            payload = {
                "report_type": "serena_google_calendar_upcoming",
                "created_at": _timestamp(),
                "calendar_id": _calendar_id(),
                "days": days,
                "time_min": time_min,
                "time_max": time_max,
                "events": [_event_summary(item) for item in events],
                "changes_made": False,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("snapshots", f"upcoming-{days}-days", payload)

            lines = [
                "Serena Google Calendar upcoming",
                "",
                f"- Calendar ID: {_calendar_id()}",
                f"- Days: {days}",
                f"- Events found: {len(events)}",
                f"- Snapshot: {report_path}",
                "- Changes made: no",
                "- Delete performed: no",
                "",
                "Events:",
            ]
            lines.extend(_format_event_line(item) for item in events) if events else lines.append("- none")

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(
                "Serena Google Calendar upcoming failed\n\n"
                f"- Error: {exc}\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Note:\n"
                "- If this says invalid_scope, Dr Piet still needs to approve the new Calendar-scoped Google token.",
                success=False,
            )


@ToolRegistry.register("serena_google_calendar_search")
class SerenaGoogleCalendarSearchTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Search Google Calendar events.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "days": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            query = str(params.get("query") or "").strip()
            days = int(params.get("days") or 90)
            limit = int(params.get("limit") or 20)

            if not query:
                return self._result("Search query is required.", success=False)

            time_min = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            time_max = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            events = _list_events(time_min, time_max, query=query, limit=limit)

            payload = {
                "report_type": "serena_google_calendar_search",
                "created_at": _timestamp(),
                "calendar_id": _calendar_id(),
                "query": query,
                "days": days,
                "events": [_event_summary(item) for item in events],
                "changes_made": False,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("snapshots", f"search-{query}", payload)

            lines = [
                "Serena Google Calendar search",
                "",
                f"- Query: {query}",
                f"- Calendar ID: {_calendar_id()}",
                f"- Events found: {len(events)}",
                f"- Snapshot: {report_path}",
                "- Changes made: no",
                "- Delete performed: no",
                "",
                "Matches:",
            ]
            lines.extend(_format_event_line(item) for item in events) if events else lines.append("- none")

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(
                "Serena Google Calendar search failed\n\n"
                f"- Error: {exc}\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Note:\n"
                "- If this says invalid_scope, Dr Piet still needs to approve the new Calendar-scoped Google token.",
                success=False,
            )


@ToolRegistry.register("serena_google_calendar_event_info")
class SerenaGoogleCalendarEventInfoTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_event_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read details for a specific Google Calendar event.",
            parameters={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                },
                "required": ["event_id"],
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            event_id = str(params.get("event_id") or "").strip()
            if not event_id:
                return self._result("event_id is required.", success=False)

            service = _get_calendar_service()
            event = service.events().get(calendarId=_calendar_id(), eventId=event_id).execute()

            payload = {
                "report_type": "serena_google_calendar_event_info",
                "created_at": _timestamp(),
                "calendar_id": _calendar_id(),
                "event": _event_summary(event),
                "changes_made": False,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"event-info-{event_id}", payload)

            attendees = event.get("attendees", []) or []

            lines = [
                "Serena Google Calendar event info",
                "",
                f"- Title: {event.get('summary') or '(no title)'}",
                f"- Event ID: {event.get('id')}",
                f"- Status: {event.get('status')}",
                f"- Start: {event.get('start')}",
                f"- End: {event.get('end')}",
                f"- Location: {event.get('location') or 'none'}",
                f"- Link: {event.get('htmlLink') or 'none'}",
                f"- Meet link: {event.get('hangoutLink') or 'none'}",
                f"- Attendees: {len(attendees)}",
                f"- Report: {report_path}",
                "- Changes made: no",
                "- Delete performed: no",
            ]

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(
                "Serena Google Calendar event-info failed\n\n"
                f"- Error: {exc}\n"
                "- Changes made: no\n"
                "- Delete performed: no",
                success=False,
            )


@ToolRegistry.register("serena_google_calendar_availability")
class SerenaGoogleCalendarAvailabilityTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_availability"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Google Calendar availability across a date/time range.",
            parameters={
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "days": {"type": "integer"},
                    "work_start_hour": {"type": "integer"},
                    "work_end_hour": {"type": "integer"},
                    "slot_minutes": {"type": "integer"},
                },
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            date_text = str(params.get("date") or "today").strip()
            days = int(params.get("days") or 1)
            work_start_hour = int(params.get("work_start_hour") or 8)
            work_end_hour = int(params.get("work_end_hour") or 17)
            slot_minutes = int(params.get("slot_minutes") or 30)

            time_min, time_max = _date_range(date_text, days=days)
            events = _list_events(time_min, time_max, limit=100)

            busy = []
            for event in events:
                start = (event.get("start") or {}).get("dateTime")
                end = (event.get("end") or {}).get("dateTime")
                if start and end:
                    busy.append({"start": start, "end": end, "summary": event.get("summary") or "(no title)"})

            payload = {
                "report_type": "serena_google_calendar_availability",
                "created_at": _timestamp(),
                "calendar_id": _calendar_id(),
                "date": date_text,
                "days": days,
                "work_start_hour": work_start_hour,
                "work_end_hour": work_end_hour,
                "slot_minutes": slot_minutes,
                "busy": busy,
                "events_seen": len(events),
                "changes_made": False,
                "delete_performed": False,
                "secret_values_exposed": False,
                "note": "v1 reports busy blocks; open-slot ranking can be refined after live Calendar token is approved.",
            }
            report_path = _save_json("reports", f"availability-{date_text}", payload)

            lines = [
                "Serena Google Calendar availability",
                "",
                f"- Calendar ID: {_calendar_id()}",
                f"- Date: {date_text}",
                f"- Days: {days}",
                f"- Work hours: {work_start_hour}:00 to {work_end_hour}:00",
                f"- Slot minutes: {slot_minutes}",
                f"- Events seen: {len(events)}",
                f"- Busy blocks: {len(busy)}",
                f"- Report: {report_path}",
                "- Changes made: no",
                "- Delete performed: no",
                "",
                "Busy blocks:",
            ]

            if busy:
                for item in busy:
                    lines.append(f"- {item['start']} -> {item['end']} | {item['summary']}")
            else:
                lines.append("- none detected in range")

            lines.extend([
                "",
                "Note:",
                "- v1 availability reports busy blocks first. Slot recommendations can be refined after live Calendar access is approved.",
            ])

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(
                "Serena Google Calendar availability failed\n\n"
                f"- Error: {exc}\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Note:\n"
                "- If this says invalid_scope, Dr Piet still needs to approve the new Calendar-scoped Google token.",
                success=False,
            )


def _parse_attendees(attendees: str | None = None) -> list[dict[str, str]]:
    raw = str(attendees or "").strip()
    if not raw:
        return []
    return [{"email": item.strip()} for item in raw.split(",") if item.strip()]


def _parse_local_datetime(value: str, timezone_name: str | None = None) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError("Datetime value is required.")

    # Accept ISO-like local values: YYYY-MM-DDTHH:MM or YYYY-MM-DD HH:MM
    raw = raw.replace(" ", "T")

    try:
        parsed = datetime.fromisoformat(raw)
    except Exception:
        raise RuntimeError(f"Could not parse datetime: {value}. Use YYYY-MM-DDTHH:MM.")

    if parsed.tzinfo is not None:
        return parsed.isoformat()

    return parsed.isoformat()


def _event_datetime(value: str, timezone_name: str | None = None) -> dict[str, str]:
    return {
        "dateTime": _parse_local_datetime(value, timezone_name),
        "timeZone": timezone_name or _default_timezone(),
    }


def _create_calendar_event(
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: str = "",
    add_meet: bool = False,
    recurrence: list[str] | None = None,
    reminders_minutes: int | None = None,
) -> dict[str, Any]:
    service = _get_calendar_service()

    body: dict[str, Any] = {
        "summary": title,
        "description": description,
        "location": location,
        "start": _event_datetime(start),
        "end": _event_datetime(end),
        "attendees": _parse_attendees(attendees),
    }

    if recurrence:
        body["recurrence"] = recurrence

    if reminders_minutes is not None:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": int(reminders_minutes)},
            ],
        }

    conference_data_version = 0
    if add_meet:
        conference_data_version = 1
        body["conferenceData"] = {
            "createRequest": {
                "requestId": f"serena-{_timestamp()}-{_safe_slug(title)}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    event = service.events().insert(
        calendarId=_calendar_id(),
        body=body,
        conferenceDataVersion=conference_data_version,
        sendUpdates="all" if attendees else "none",
    ).execute()

    return event


def _event_created_response(prefix: str, event: dict[str, Any], report_path: Path, extra_lines: list[str] | None = None) -> str:
    lines = [
        prefix,
        "",
        f"- Title: {event.get('summary') or '(no title)'}",
        f"- Event ID: {event.get('id')}",
        f"- Status: {event.get('status')}",
        f"- Start: {event.get('start')}",
        f"- End: {event.get('end')}",
        f"- Location: {event.get('location') or 'none'}",
        f"- Link: {event.get('htmlLink') or 'none'}",
        f"- Meet link: {event.get('hangoutLink') or 'none'}",
        f"- Report: {report_path}",
        "- Event created: yes",
        "- Changes made: yes",
        "- Delete performed: no",
        "- Secret values exposed: no",
    ]
    if extra_lines:
        lines.extend([""] + extra_lines)
    return "\n".join(lines)


@ToolRegistry.register("serena_google_calendar_create")
class SerenaGoogleCalendarCreateTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_create"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Calendar event.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {"type": "string"},
                },
                "required": ["title", "start", "end"],
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "").strip()
        start = str(params.get("start") or "").strip()
        end = str(params.get("end") or "").strip()
        description = str(params.get("description") or "").strip()
        location = str(params.get("location") or "").strip()
        attendees = str(params.get("attendees") or "").strip()

        try:
            event = _create_calendar_event(
                title=title,
                start=start,
                end=end,
                description=description,
                location=location,
                attendees=attendees,
            )

            payload = {
                "report_type": "serena_google_calendar_create",
                "created_at": _timestamp(),
                "calendar_id": _calendar_id(),
                "event": _event_summary(event),
                "changes_made": True,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"create-{title}", payload)

            return self._result(
                _event_created_response("Serena Google Calendar event created", event, report_path),
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Google Calendar create failed safely\n\n"
                f"- Title: {title}\n"
                f"- Start: {start}\n"
                f"- End: {end}\n"
                f"- Error: {exc}\n"
                "- Event created: no\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Note:\n"
                "- If this says invalid_scope, Dr Piet still needs to approve the Calendar-scoped Google token.",
                success=False,
            )


@ToolRegistry.register("serena_google_calendar_appointment")
class SerenaGoogleCalendarAppointmentTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_appointment"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a structured appointment event.",
            parameters={
                "type": "object",
                "properties": {
                    "patient": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "reason": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {"type": "string"},
                    "add_meet": {"type": "boolean"},
                },
                "required": ["patient", "start", "end"],
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        patient = str(params.get("patient") or "").strip()
        start = str(params.get("start") or "").strip()
        end = str(params.get("end") or "").strip()
        reason = str(params.get("reason") or "Consultation appointment").strip()
        location = str(params.get("location") or "").strip()
        attendees = str(params.get("attendees") or "").strip()
        add_meet = bool(params.get("add_meet") or False)

        title = f"Appointment: {patient}"
        description = (
            "Appointment created by Serena Google Calendar Full Operator v1.\n\n"
            f"Patient / client: {patient}\n"
            f"Reason: {reason}\n\n"
            "Preparation:\n"
            "- Review relevant notes before appointment.\n"
            "- Confirm required documents or follow-up items.\n"
        )

        try:
            event = _create_calendar_event(
                title=title,
                start=start,
                end=end,
                description=description,
                location=location,
                attendees=attendees,
                add_meet=add_meet,
            )

            payload = {
                "report_type": "serena_google_calendar_appointment",
                "created_at": _timestamp(),
                "calendar_id": _calendar_id(),
                "patient": patient,
                "reason": reason,
                "event": _event_summary(event),
                "meet_requested": add_meet,
                "changes_made": True,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"appointment-{patient}", payload)

            return self._result(
                _event_created_response("Serena Google Calendar appointment created", event, report_path),
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Google Calendar appointment failed safely\n\n"
                f"- Patient/client: {patient}\n"
                f"- Start: {start}\n"
                f"- End: {end}\n"
                f"- Error: {exc}\n"
                "- Appointment created: no\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Note:\n"
                "- If this says invalid_scope, Dr Piet still needs to approve the Calendar-scoped Google token.",
                success=False,
            )


@ToolRegistry.register("serena_google_calendar_reminder")
class SerenaGoogleCalendarReminderTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_reminder"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a calendar reminder/follow-up event.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "minutes": {"type": "integer"},
                    "description": {"type": "string"},
                },
                "required": ["title", "start"],
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "").strip()
        start = str(params.get("start") or "").strip()
        minutes = int(params.get("minutes") or 15)
        description = str(params.get("description") or "Reminder created by Serena.").strip()

        start_dt = datetime.fromisoformat(start.replace(" ", "T"))
        end_dt = start_dt + timedelta(minutes=minutes)

        try:
            event = _create_calendar_event(
                title=f"Reminder: {title}",
                start=start_dt.isoformat(),
                end=end_dt.isoformat(),
                description=description,
                reminders_minutes=10,
            )

            payload = {
                "report_type": "serena_google_calendar_reminder",
                "created_at": _timestamp(),
                "calendar_id": _calendar_id(),
                "event": _event_summary(event),
                "changes_made": True,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"reminder-{title}", payload)

            return self._result(
                _event_created_response("Serena Google Calendar reminder created", event, report_path),
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Google Calendar reminder failed safely\n\n"
                f"- Title: {title}\n"
                f"- Start: {start}\n"
                f"- Error: {exc}\n"
                "- Reminder created: no\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Note:\n"
                "- If this says invalid_scope, Dr Piet still needs to approve the Calendar-scoped Google token.",
                success=False,
            )


@ToolRegistry.register("serena_google_calendar_meet")
class SerenaGoogleCalendarMeetTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_meet"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Calendar event with Google Meet link.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "description": {"type": "string"},
                    "attendees": {"type": "string"},
                },
                "required": ["title", "start", "end"],
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "").strip()
        start = str(params.get("start") or "").strip()
        end = str(params.get("end") or "").strip()
        description = str(params.get("description") or "Google Meet event created by Serena.").strip()
        attendees = str(params.get("attendees") or "").strip()

        try:
            event = _create_calendar_event(
                title=title,
                start=start,
                end=end,
                description=description,
                attendees=attendees,
                add_meet=True,
            )

            payload = {
                "report_type": "serena_google_calendar_meet",
                "created_at": _timestamp(),
                "calendar_id": _calendar_id(),
                "event": _event_summary(event),
                "meet_requested": True,
                "changes_made": True,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"meet-{title}", payload)

            return self._result(
                _event_created_response("Serena Google Calendar Meet event created", event, report_path),
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Google Calendar Meet event failed safely\n\n"
                f"- Title: {title}\n"
                f"- Start: {start}\n"
                f"- End: {end}\n"
                f"- Error: {exc}\n"
                "- Meet event created: no\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Note:\n"
                "- If this says invalid_scope, Dr Piet still needs to approve the Calendar-scoped Google token.",
                success=False,
            )


@ToolRegistry.register("serena_google_calendar_recurring")
class SerenaGoogleCalendarRecurringTool(_GoogleCalendarBaseTool):
    tool_id = "serena_google_calendar_recurring"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a recurring Google Calendar event.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "rrule": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {"type": "string"},
                },
                "required": ["title", "start", "end", "rrule"],
            },
            category="serena_google_calendar",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "").strip()
        start = str(params.get("start") or "").strip()
        end = str(params.get("end") or "").strip()
        rrule = str(params.get("rrule") or "").strip()
        description = str(params.get("description") or "Recurring event created by Serena.").strip()
        location = str(params.get("location") or "").strip()
        attendees = str(params.get("attendees") or "").strip()

        if not rrule.startswith("RRULE:"):
            rrule = "RRULE:" + rrule

        try:
            event = _create_calendar_event(
                title=title,
                start=start,
                end=end,
                description=description,
                location=location,
                attendees=attendees,
                recurrence=[rrule],
            )

            payload = {
                "report_type": "serena_google_calendar_recurring",
                "created_at": _timestamp(),
                "calendar_id": _calendar_id(),
                "event": _event_summary(event),
                "rrule": rrule,
                "changes_made": True,
                "delete_performed": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("reports", f"recurring-{title}", payload)

            return self._result(
                _event_created_response(
                    "Serena Google Calendar recurring event created",
                    event,
                    report_path,
                    extra_lines=[f"- Recurrence: {rrule}"],
                ),
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Google Calendar recurring event failed safely\n\n"
                f"- Title: {title}\n"
                f"- Start: {start}\n"
                f"- End: {end}\n"
                f"- RRULE: {rrule}\n"
                f"- Error: {exc}\n"
                "- Recurring event created: no\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Note:\n"
                "- If this says invalid_scope, Dr Piet still needs to approve the Calendar-scoped Google token.",
                success=False,
            )


__all__ = [
    "SerenaGoogleCalendarStatusTool",
    "SerenaGoogleCalendarEnvCheckTool",
    "SerenaGoogleCalendarConnectCheckTool",
    "SerenaGoogleCalendarPlanTool",
    "SerenaGoogleCalendarAvailabilityTool",
    "SerenaGoogleCalendarRecurringTool",
    "SerenaGoogleCalendarMeetTool",
    "SerenaGoogleCalendarReminderTool",
    "SerenaGoogleCalendarAppointmentTool",
    "SerenaGoogleCalendarCreateTool",
    "SerenaGoogleCalendarEventInfoTool",
    "SerenaGoogleCalendarSearchTool",
    "SerenaGoogleCalendarUpcomingTool",
    "SerenaGoogleCalendarTodayTool",
]
