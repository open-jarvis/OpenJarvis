
"""Serena Google Calendar operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_google_calendar import (
    SerenaGoogleCalendarConnectCheckTool,
    SerenaGoogleCalendarEnvCheckTool,
    SerenaGoogleCalendarPlanTool,
    SerenaGoogleCalendarStatusTool,
    SerenaGoogleCalendarAuditTool,
    SerenaGoogleCalendarWeeklyBriefTool,
    SerenaGoogleCalendarDailyBriefTool,
    SerenaGoogleCalendarBlockedBulkDeleteTool,
    SerenaGoogleCalendarCancelTool,
    SerenaGoogleCalendarAddAttendeeTool,
    SerenaGoogleCalendarUpdateTool,
    SerenaGoogleCalendarRescheduleTool,
    SerenaGoogleCalendarRecurringTool,
    SerenaGoogleCalendarMeetTool,
    SerenaGoogleCalendarReminderTool,
    SerenaGoogleCalendarAppointmentTool,
    SerenaGoogleCalendarCreateTool,
    SerenaGoogleCalendarAvailabilityTool,
    SerenaGoogleCalendarEventInfoTool,
    SerenaGoogleCalendarSearchTool,
    SerenaGoogleCalendarUpcomingTool,
    SerenaGoogleCalendarTodayTool,
)


@click.group()
def calendar() -> None:
    """Native Serena Google Calendar operator tools."""


@calendar.command("status")
def status() -> None:
    """Show Google Calendar operator status."""
    console = Console()
    result = SerenaGoogleCalendarStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("env-check")
def env_check() -> None:
    """Check Google Calendar env configuration without exposing secrets."""
    console = Console()
    result = SerenaGoogleCalendarEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("connect-check")
def connect_check() -> None:
    """Connect to Google Calendar and verify access."""
    console = Console()
    result = SerenaGoogleCalendarConnectCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("plan")
@click.option("--goal", required=True, help="Calendar operation goal.")
@click.option("--operation", default="schedule", help="schedule, read, search, update, cancel, reminder, meet.")
@click.option("--date", default="", help="Target date if known.")
@click.option("--time", "time_value", default="", help="Target time if known.")
@click.option("--attendees", default="", help="Comma-separated attendees if known.")
def plan(goal: str, operation: str, date: str, time_value: str, attendees: str) -> None:
    """Create a Google Calendar operation plan without API writes."""
    console = Console()
    result = SerenaGoogleCalendarPlanTool().execute(
        goal=goal,
        operation=operation,
        date=date,
        time=time_value,
        attendees=attendees,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("today")
@click.option("--limit", default=20, type=int, help="Maximum events to return.")
def today(limit: int) -> None:
    """Read today's calendar schedule."""
    console = Console()
    result = SerenaGoogleCalendarTodayTool().execute(limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("upcoming")
@click.option("--days", default=7, type=int, help="Days ahead to read.")
@click.option("--limit", default=30, type=int, help="Maximum events to return.")
def upcoming(days: int, limit: int) -> None:
    """Read upcoming calendar events."""
    console = Console()
    result = SerenaGoogleCalendarUpcomingTool().execute(days=days, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("search")
@click.option("--query", required=True, help="Search query.")
@click.option("--days", default=90, type=int, help="Days ahead to search.")
@click.option("--limit", default=20, type=int, help="Maximum events to return.")
def search(query: str, days: int, limit: int) -> None:
    """Search calendar events."""
    console = Console()
    result = SerenaGoogleCalendarSearchTool().execute(query=query, days=days, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("event-info")
@click.option("--event-id", required=True, help="Google Calendar event ID.")
def event_info(event_id: str) -> None:
    """Read details for one calendar event."""
    console = Console()
    result = SerenaGoogleCalendarEventInfoTool().execute(event_id=event_id)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("availability")
@click.option("--date", default="today", help="Date: today, tomorrow, or YYYY-MM-DD.")
@click.option("--days", default=1, type=int, help="Number of days to inspect.")
@click.option("--work-start-hour", default=8, type=int, help="Workday start hour.")
@click.option("--work-end-hour", default=17, type=int, help="Workday end hour.")
@click.option("--slot-minutes", default=30, type=int, help="Slot size in minutes.")
def availability(date: str, days: int, work_start_hour: int, work_end_hour: int, slot_minutes: int) -> None:
    """Check calendar availability."""
    console = Console()
    result = SerenaGoogleCalendarAvailabilityTool().execute(
        date=date,
        days=days,
        work_start_hour=work_start_hour,
        work_end_hour=work_end_hour,
        slot_minutes=slot_minutes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("create")
@click.option("--title", required=True, help="Event title.")
@click.option("--start", required=True, help="Start datetime, e.g. 2026-05-05T10:00.")
@click.option("--end", required=True, help="End datetime, e.g. 2026-05-05T10:30.")
@click.option("--description", default="", help="Event description.")
@click.option("--location", default="", help="Event location.")
@click.option("--attendees", default="", help="Comma-separated attendee emails.")
def create(title: str, start: str, end: str, description: str, location: str, attendees: str) -> None:
    """Create a Google Calendar event."""
    console = Console()
    result = SerenaGoogleCalendarCreateTool().execute(
        title=title,
        start=start,
        end=end,
        description=description,
        location=location,
        attendees=attendees,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("appointment")
@click.option("--patient", required=True, help="Patient/client name.")
@click.option("--start", required=True, help="Start datetime.")
@click.option("--end", required=True, help="End datetime.")
@click.option("--reason", default="Consultation appointment", help="Appointment reason.")
@click.option("--location", default="", help="Appointment location.")
@click.option("--attendees", default="", help="Comma-separated attendee emails.")
@click.option("--add-meet", is_flag=True, help="Add Google Meet link.")
def appointment(patient: str, start: str, end: str, reason: str, location: str, attendees: str, add_meet: bool) -> None:
    """Create a structured appointment."""
    console = Console()
    result = SerenaGoogleCalendarAppointmentTool().execute(
        patient=patient,
        start=start,
        end=end,
        reason=reason,
        location=location,
        attendees=attendees,
        add_meet=add_meet,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("reminder")
@click.option("--title", required=True, help="Reminder title.")
@click.option("--start", required=True, help="Reminder start datetime.")
@click.option("--minutes", default=15, type=int, help="Reminder event duration.")
@click.option("--description", default="Reminder created by Serena.", help="Reminder description.")
def reminder(title: str, start: str, minutes: int, description: str) -> None:
    """Create a calendar reminder/follow-up."""
    console = Console()
    result = SerenaGoogleCalendarReminderTool().execute(
        title=title,
        start=start,
        minutes=minutes,
        description=description,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("meet")
@click.option("--title", required=True, help="Event title.")
@click.option("--start", required=True, help="Start datetime.")
@click.option("--end", required=True, help="End datetime.")
@click.option("--description", default="Google Meet event created by Serena.", help="Event description.")
@click.option("--attendees", default="", help="Comma-separated attendee emails.")
def meet(title: str, start: str, end: str, description: str, attendees: str) -> None:
    """Create a Google Meet calendar event."""
    console = Console()
    result = SerenaGoogleCalendarMeetTool().execute(
        title=title,
        start=start,
        end=end,
        description=description,
        attendees=attendees,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("recurring")
@click.option("--title", required=True, help="Event title.")
@click.option("--start", required=True, help="Start datetime.")
@click.option("--end", required=True, help="End datetime.")
@click.option("--rrule", required=True, help="Recurrence rule, e.g. FREQ=WEEKLY;COUNT=4.")
@click.option("--description", default="Recurring event created by Serena.", help="Event description.")
@click.option("--location", default="", help="Event location.")
@click.option("--attendees", default="", help="Comma-separated attendee emails.")
def recurring(title: str, start: str, end: str, rrule: str, description: str, location: str, attendees: str) -> None:
    """Create a recurring calendar event."""
    console = Console()
    result = SerenaGoogleCalendarRecurringTool().execute(
        title=title,
        start=start,
        end=end,
        rrule=rrule,
        description=description,
        location=location,
        attendees=attendees,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("reschedule")
@click.option("--event-id", required=True, help="Google Calendar event ID.")
@click.option("--start", required=True, help="New start datetime.")
@click.option("--end", required=True, help="New end datetime.")
@click.option("--reason", default="Rescheduled by Serena.", help="Reason for reschedule.")
def reschedule(event_id: str, start: str, end: str, reason: str) -> None:
    """Reschedule a specific event."""
    console = Console()
    result = SerenaGoogleCalendarRescheduleTool().execute(event_id=event_id, start=start, end=end, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("update")
@click.option("--event-id", required=True, help="Google Calendar event ID.")
@click.option("--title", default="", help="New title.")
@click.option("--description", default="", help="New description.")
@click.option("--location", default="", help="New location.")
def update(event_id: str, title: str, description: str, location: str) -> None:
    """Update specific event fields."""
    console = Console()
    result = SerenaGoogleCalendarUpdateTool().execute(event_id=event_id, title=title, description=description, location=location)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("add-attendee")
@click.option("--event-id", required=True, help="Google Calendar event ID.")
@click.option("--attendees", required=True, help="Comma-separated attendee emails.")
def add_attendee(event_id: str, attendees: str) -> None:
    """Add attendees to a specific event."""
    console = Console()
    result = SerenaGoogleCalendarAddAttendeeTool().execute(event_id=event_id, attendees=attendees)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("cancel")
@click.option("--event-id", required=True, help="Google Calendar event ID.")
@click.option("--reason", default="Cancelled by explicit Serena command.", help="Cancel reason.")
@click.option("--approved", is_flag=True, help="Required explicit approval.")
def cancel(event_id: str, reason: str, approved: bool) -> None:
    """Cancel a specific event with explicit approval."""
    console = Console()
    result = SerenaGoogleCalendarCancelTool().execute(event_id=event_id, reason=reason, approved=approved)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("blocked-bulk-delete")
@click.option("--reason", default="Bulk calendar delete requested.", help="Reason for attempted bulk delete.")
def blocked_bulk_delete(reason: str) -> None:
    """Deliberately blocked bulk calendar delete command."""
    console = Console()
    result = SerenaGoogleCalendarBlockedBulkDeleteTool().execute(reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("daily-brief")
@click.option("--date", default="today", help="Date: today, tomorrow, or YYYY-MM-DD.")
@click.option("--limit", default=50, type=int, help="Maximum events.")
def daily_brief(date: str, limit: int) -> None:
    """Create a daily calendar brief."""
    console = Console()
    result = SerenaGoogleCalendarDailyBriefTool().execute(date=date, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("weekly-brief")
@click.option("--date", default="this week", help="Week start reference: this week or YYYY-MM-DD.")
@click.option("--limit", default=100, type=int, help="Maximum events.")
def weekly_brief(date: str, limit: int) -> None:
    """Create a weekly calendar brief."""
    console = Console()
    result = SerenaGoogleCalendarWeeklyBriefTool().execute(date=date, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@calendar.command("audit")
def audit() -> None:
    """Audit Google Calendar operator status and safety."""
    console = Console()
    result = SerenaGoogleCalendarAuditTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["calendar"]
