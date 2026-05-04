
"""Serena Google Calendar operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_google_calendar import (
    SerenaGoogleCalendarConnectCheckTool,
    SerenaGoogleCalendarEnvCheckTool,
    SerenaGoogleCalendarPlanTool,
    SerenaGoogleCalendarStatusTool,
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


__all__ = ["calendar"]
