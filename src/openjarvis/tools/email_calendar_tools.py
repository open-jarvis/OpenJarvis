"""Email and calendar agent tools backed by the Gmail / Calendar connectors.

Read tools (`email_list`, `calendar_list_events`) are unrestricted. Write tools
(`email_send`, `calendar_create_event`) set ``requires_confirmation=True`` so the
ToolExecutor gates them behind the interactive confirmation callback — the agent
cannot silently send mail or create events.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, List, Optional

from openjarvis.core.registry import ConnectorRegistry, ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


def _get_connector(connector_id: str):
    """Return a connected connector instance, or (None, error_message)."""
    import openjarvis.connectors  # noqa: F401  (triggers registration)

    if not ConnectorRegistry.contains(connector_id):
        return None, f"Connector '{connector_id}' is not available."
    connector = ConnectorRegistry.get(connector_id)()
    if not connector.is_connected():
        return (
            None,
            f"Connector '{connector_id}' is not connected. "
            f"Run `jarvis connect {connector_id}` first.",
        )
    return connector, ""


def _as_list(value: Any) -> List[str]:
    """Normalize a string or list of strings into a clean list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


# ---------------------------------------------------------------------------
# email_send
# ---------------------------------------------------------------------------


@ToolRegistry.register("email_send")
class EmailSendTool(BaseTool):
    """Send an email via the connected Gmail account (gated by confirmation)."""

    tool_id = "email_send"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="email_send",
            description=(
                "Send an email from the user's connected Gmail account."
                " Requires confirmation before sending."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient address(es), comma-separated.",
                    },
                    "subject": {"type": "string", "description": "Email subject."},
                    "body": {"type": "string", "description": "Email body text."},
                    "cc": {
                        "type": "string",
                        "description": "CC address(es), comma-separated.",
                    },
                    "bcc": {
                        "type": "string",
                        "description": "BCC address(es), comma-separated.",
                    },
                    "html": {
                        "type": "boolean",
                        "description": "Treat body as HTML. Default false.",
                    },
                },
                "required": ["to", "subject", "body"],
            },
            category="communication",
            requires_confirmation=True,
            required_capabilities=["channel:send"],
        )

    def execute(self, **params: Any) -> ToolResult:
        to = _as_list(params.get("to"))
        subject = str(params.get("subject", "")).strip()
        body = params.get("body")
        if not to:
            return ToolResult(
                tool_name="email_send", content="No recipient provided.", success=False
            )
        if body is None:
            return ToolResult(
                tool_name="email_send", content="No body provided.", success=False
            )

        connector, err = _get_connector("gmail")
        if connector is None:
            return ToolResult(tool_name="email_send", content=err, success=False)

        try:
            msg_id = connector.send_message(
                to=to,
                subject=subject,
                body=str(body),
                cc=_as_list(params.get("cc")) or None,
                bcc=_as_list(params.get("bcc")) or None,
                html=bool(params.get("html", False)),
            )
        except Exception as exc:
            logger.debug("email send failed: %s", exc)
            return ToolResult(
                tool_name="email_send",
                content=f"Failed to send email: {exc}",
                success=False,
            )

        return ToolResult(
            tool_name="email_send",
            content=f"Email sent to {', '.join(to)} (id: {msg_id}).",
            success=True,
            metadata={"message_id": msg_id, "to": to, "subject": subject},
        )


# ---------------------------------------------------------------------------
# email_list
# ---------------------------------------------------------------------------


@ToolRegistry.register("email_list")
class EmailListTool(BaseTool):
    """List recent emails from the connected Gmail account."""

    tool_id = "email_list"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="email_list",
            description=(
                "List recent emails from the user's Gmail. Optionally filter"
                " with a Gmail search query (e.g. 'is:unread from:alice')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query. Default: inbox.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum emails to return (default 10).",
                    },
                },
                "required": [],
            },
            category="communication",
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query", "") or "").strip()
        try:
            max_results = int(params.get("max_results", 10) or 10)
        except (TypeError, ValueError):
            max_results = 10
        max_results = max(1, min(max_results, 50))

        connector, err = _get_connector("gmail")
        if connector is None:
            return ToolResult(tool_name="email_list", content=err, success=False)

        try:
            docs = []
            for doc in connector.sync(query_extra=query):
                docs.append(doc)
                if len(docs) >= max_results:
                    break
        except Exception as exc:
            logger.debug("email list failed: %s", exc)
            return ToolResult(
                tool_name="email_list",
                content=f"Failed to list emails: {exc}",
                success=False,
            )

        if not docs:
            return ToolResult(
                tool_name="email_list",
                content="No emails found.",
                success=True,
                metadata={"count": 0},
            )

        lines = []
        for d in docs:
            when = d.timestamp.strftime("%Y-%m-%d %H:%M") if d.timestamp else ""
            snippet = (d.metadata or {}).get("snippet", "")
            lines.append(
                f"- {d.title or '(no subject)'}\n  From: {d.author}"
                f"{('  ' + when) if when else ''}"
                f"{('  — ' + snippet) if snippet else ''}"
            )
        return ToolResult(
            tool_name="email_list",
            content="\n".join(lines),
            success=True,
            metadata={"count": len(docs)},
        )


# ---------------------------------------------------------------------------
# calendar_create_event
# ---------------------------------------------------------------------------


@ToolRegistry.register("calendar_create_event")
class CalendarCreateEventTool(BaseTool):
    """Create a Google Calendar event (gated by confirmation)."""

    tool_id = "calendar_create_event"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calendar_create_event",
            description=(
                "Create an event on the user's Google Calendar. Times use"
                " RFC3339 (2026-06-10T15:00:00) or a bare date (2026-06-10)"
                " for all-day events. Requires confirmation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event title."},
                    "start": {
                        "type": "string",
                        "description": "Start datetime or date.",
                    },
                    "end": {
                        "type": "string",
                        "description": "End datetime or date.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description.",
                    },
                    "location": {"type": "string", "description": "Event location."},
                    "attendees": {
                        "type": "string",
                        "description": "Attendee email(s), comma-separated.",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Target calendar (default 'primary').",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA TZ name, e.g. 'America/New_York'.",
                    },
                },
                "required": ["summary", "start", "end"],
            },
            category="productivity",
            requires_confirmation=True,
            required_capabilities=["calendar:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        summary = str(params.get("summary", "")).strip()
        start = str(params.get("start", "")).strip()
        end = str(params.get("end", "")).strip()
        if not (summary and start and end):
            return ToolResult(
                tool_name="calendar_create_event",
                content="summary, start, and end are required.",
                success=False,
            )

        connector, err = _get_connector("gcalendar")
        if connector is None:
            return ToolResult(
                tool_name="calendar_create_event", content=err, success=False
            )

        try:
            event = connector.create_event(
                summary=summary,
                start=start,
                end=end,
                description=str(params.get("description", "") or ""),
                location=str(params.get("location", "") or ""),
                attendees=_as_list(params.get("attendees")) or None,
                calendar_id=str(params.get("calendar_id", "primary") or "primary"),
                timezone=(str(params["timezone"]) if params.get("timezone") else None),
            )
        except Exception as exc:
            logger.debug("calendar create failed: %s", exc)
            return ToolResult(
                tool_name="calendar_create_event",
                content=f"Failed to create event: {exc}",
                success=False,
            )

        link = event.get("htmlLink", "")
        return ToolResult(
            tool_name="calendar_create_event",
            content=f"Event '{summary}' created ({start} → {end}). {link}".strip(),
            success=True,
            metadata={"event_id": event.get("id", ""), "html_link": link},
        )


# ---------------------------------------------------------------------------
# calendar_list_events
# ---------------------------------------------------------------------------


@ToolRegistry.register("calendar_list_events")
class CalendarListEventsTool(BaseTool):
    """List upcoming Google Calendar events."""

    tool_id = "calendar_list_events"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calendar_list_events",
            description=(
                "List upcoming events from the user's Google Calendar within"
                " the next N days."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "Look-ahead window in days (default 7).",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum events to return (default 10).",
                    },
                },
                "required": [],
            },
            category="productivity",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            days_ahead = int(params.get("days_ahead", 7) or 7)
        except (TypeError, ValueError):
            days_ahead = 7
        try:
            max_results = int(params.get("max_results", 10) or 10)
        except (TypeError, ValueError):
            max_results = 10
        max_results = max(1, min(max_results, 50))

        connector, err = _get_connector("gcalendar")
        if connector is None:
            return ToolResult(
                tool_name="calendar_list_events", content=err, success=False
            )

        # sync() defaults to events starting after `since`; use now so we only
        # surface upcoming items, then filter the far end client-side.
        now = datetime.now()
        horizon = now + timedelta(days=max(1, days_ahead))
        try:
            events = []
            for doc in connector.sync(since=now):
                if doc.timestamp and doc.timestamp.replace(tzinfo=None) > horizon:
                    continue
                events.append(doc)
                if len(events) >= max_results:
                    break
        except Exception as exc:
            logger.debug("calendar list failed: %s", exc)
            return ToolResult(
                tool_name="calendar_list_events",
                content=f"Failed to list events: {exc}",
                success=False,
            )

        if not events:
            return ToolResult(
                tool_name="calendar_list_events",
                content="No upcoming events found.",
                success=True,
                metadata={"count": 0},
            )

        lines = []
        for d in events:
            when = d.timestamp.strftime("%Y-%m-%d %H:%M") if d.timestamp else "?"
            lines.append(f"- {when}  {d.title or '(no title)'}")
        return ToolResult(
            tool_name="calendar_list_events",
            content="\n".join(lines),
            success=True,
            metadata={"count": len(events)},
        )


__all__ = [
    "EmailSendTool",
    "EmailListTool",
    "CalendarCreateEventTool",
    "CalendarListEventsTool",
]
