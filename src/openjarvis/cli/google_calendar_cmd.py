
"""Serena Google Calendar operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_google_calendar import (
    SerenaGoogleCalendarConnectCheckTool,
    SerenaGoogleCalendarEnvCheckTool,
    SerenaGoogleCalendarPlanTool,
    SerenaGoogleCalendarStatusTool,
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


__all__ = ["calendar"]
