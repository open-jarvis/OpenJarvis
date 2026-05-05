
"""Serena Bookings / Appointments / Reminders Full Operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_bookings import (
    SerenaBookingsEnvCheckTool,
    SerenaBookingsPlanTool,
    SerenaBookingsSourceInfoTool,
    SerenaBookingsSourceListTool,
    SerenaBookingsStatusTool,
)


@click.group()
def bookings() -> None:
    """Native Serena Bookings / Appointments / Reminders operator tools."""


@bookings.command("status")
def status() -> None:
    """Show Bookings operator status."""
    console = Console()
    result = SerenaBookingsStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("env-check")
def env_check() -> None:
    """Check bookings/calendar environment without exposing secrets."""
    console = Console()
    result = SerenaBookingsEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("source-list")
def source_list() -> None:
    """List registered bookings/appointment/reminder sources."""
    console = Console()
    result = SerenaBookingsSourceListTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("source-info")
@click.option("--source", required=True, help="Source ID, e.g. google-calendar, local-bookings.")
def source_info(source: str) -> None:
    """Show details for one bookings/appointment/reminder source."""
    console = Console()
    result = SerenaBookingsSourceInfoTool().execute(source=source)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("plan")
@click.option("--goal", required=True, help="Bookings/appointment/reminder goal.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--patient-or-client", default="not specified", help="Patient/client label.")
@click.option("--appointment-type", default="appointment", help="Appointment type.")
@click.option("--date", default="not specified", help="Requested date.")
@click.option("--time", default="not specified", help="Requested time.")
def plan(goal: str, business: str, patient_or_client: str, appointment_type: str, date: str, time: str) -> None:
    """Create a bookings/appointment/reminder operation plan."""
    console = Console()
    result = SerenaBookingsPlanTool().execute(
        goal=goal,
        business=business,
        patient_or_client=patient_or_client,
        appointment_type=appointment_type,
        date=date,
        time=time,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["bookings"]
