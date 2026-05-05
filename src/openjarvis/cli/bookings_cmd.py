
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
    SerenaBookingsNoShowPolicyTool,
    SerenaBookingsCancellationPolicyTool,
    SerenaBookingsCancelBookingTool,
    SerenaBookingsRescheduleBookingTool,
    SerenaBookingsBookingListTool,
    SerenaBookingsBookingInfoTool,
    SerenaBookingsCreateBookingTool,
    SerenaBookingsBookingRequestTool,
    SerenaBookingsAvailabilityPlanTool,
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


@bookings.command("availability-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date", default="today", help="Start date.")
@click.option("--days", default=1, type=int, help="Number of days.")
@click.option("--duration-minutes", default=60, type=int, help="Appointment duration.")
@click.option("--work-start", default="08:00", help="Workday start.")
@click.option("--work-end", default="17:00", help="Workday end.")
@click.option("--appointment-type", default="appointment", help="Appointment type.")
def availability_plan(business: str, date: str, days: int, duration_minutes: int, work_start: str, work_end: str, appointment_type: str) -> None:
    """Create an availability checking plan."""
    console = Console()
    result = SerenaBookingsAvailabilityPlanTool().execute(
        business=business,
        date=date,
        days=days,
        duration_minutes=duration_minutes,
        work_start=work_start,
        work_end=work_end,
        appointment_type=appointment_type,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("booking-request")
@click.option("--request-id", default="", help="Request ID.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--patient-or-client", required=True, help="Patient/client label.")
@click.option("--appointment-type", default="appointment", help="Appointment type.")
@click.option("--date", default="not specified", help="Requested date.")
@click.option("--time", default="not specified", help="Requested time.")
@click.option("--duration-minutes", default=60, type=int, help="Duration.")
@click.option("--contact", default="", help="Contact detail.")
@click.option("--notes", default="", help="Notes.")
@click.option("--sensitive", is_flag=True, help="Mark as sensitive patient/client data.")
def booking_request(request_id: str, business: str, patient_or_client: str, appointment_type: str, date: str, time: str, duration_minutes: int, contact: str, notes: str, sensitive: bool) -> None:
    """Create a local booking request."""
    console = Console()
    result = SerenaBookingsBookingRequestTool().execute(
        request_id=request_id,
        business=business,
        patient_or_client=patient_or_client,
        appointment_type=appointment_type,
        date=date,
        time=time,
        duration_minutes=duration_minutes,
        contact=contact,
        notes=notes,
        sensitive=sensitive,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("create-booking")
@click.option("--booking-id", default="", help="Booking ID.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--patient-or-client", required=True, help="Patient/client label.")
@click.option("--appointment-type", default="appointment", help="Appointment type.")
@click.option("--date", required=True, help="Appointment date.")
@click.option("--time", required=True, help="Appointment time.")
@click.option("--duration-minutes", default=60, type=int, help="Duration.")
@click.option("--location", default="", help="Appointment location.")
@click.option("--contact", default="", help="Contact detail.")
@click.option("--calendar-event-id", default="", help="Linked Calendar event ID.")
@click.option("--status", default="scheduled_local", help="Booking status.")
@click.option("--notes", default="", help="Notes.")
@click.option("--sensitive", is_flag=True, help="Mark as sensitive patient/client data.")
def create_booking(booking_id: str, business: str, patient_or_client: str, appointment_type: str, date: str, time: str, duration_minutes: int, location: str, contact: str, calendar_event_id: str, status: str, notes: str, sensitive: bool) -> None:
    """Create a local booking record."""
    console = Console()
    result = SerenaBookingsCreateBookingTool().execute(
        booking_id=booking_id,
        business=business,
        patient_or_client=patient_or_client,
        appointment_type=appointment_type,
        date=date,
        time=time,
        duration_minutes=duration_minutes,
        location=location,
        contact=contact,
        calendar_event_id=calendar_event_id,
        status=status,
        notes=notes,
        sensitive=sensitive,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("booking-info")
@click.option("--booking-id", required=True, help="Booking ID.")
def booking_info(booking_id: str) -> None:
    """Show local booking details."""
    console = Console()
    result = SerenaBookingsBookingInfoTool().execute(booking_id=booking_id)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("booking-list")
@click.option("--business", default="", help="Optional business filter.")
@click.option("--status", default="", help="Optional status filter.")
@click.option("--limit", default=20, type=int, help="Maximum rows.")
def booking_list(business: str, status: str, limit: int) -> None:
    """List local booking records."""
    console = Console()
    result = SerenaBookingsBookingListTool().execute(business=business, status=status, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("reschedule-booking")
@click.option("--booking-id", required=True, help="Booking ID.")
@click.option("--new-date", required=True, help="New appointment date.")
@click.option("--new-time", required=True, help="New appointment time.")
@click.option("--reason", default="Reschedule requested.", help="Reason.")
@click.option("--approved", is_flag=True, help="Mark reschedule as approved/planned.")
def reschedule_booking(booking_id: str, new_date: str, new_time: str, reason: str, approved: bool) -> None:
    """Create a local booking reschedule plan."""
    console = Console()
    result = SerenaBookingsRescheduleBookingTool().execute(
        booking_id=booking_id,
        new_date=new_date,
        new_time=new_time,
        reason=reason,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("cancel-booking")
@click.option("--booking-id", required=True, help="Booking ID.")
@click.option("--reason", default="Cancellation requested.", help="Reason.")
@click.option("--approved", is_flag=True, help="Required for cancellation planning.")
def cancel_booking(booking_id: str, reason: str, approved: bool) -> None:
    """Create a local booking cancellation plan."""
    console = Console()
    result = SerenaBookingsCancelBookingTool().execute(
        booking_id=booking_id,
        reason=reason,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("cancellation-policy")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--notice-hours", default=24, type=int, help="Preferred notice hours.")
@click.option("--notes", default="", help="Notes.")
def cancellation_policy(business: str, notice_hours: int, notes: str) -> None:
    """Create/display appointment cancellation policy."""
    console = Console()
    result = SerenaBookingsCancellationPolicyTool().execute(
        business=business,
        notice_hours=notice_hours,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("no-show-policy")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--notes", default="", help="Notes.")
def no_show_policy(business: str, notes: str) -> None:
    """Create/display no-show policy and prevention workflow."""
    console = Console()
    result = SerenaBookingsNoShowPolicyTool().execute(business=business, notes=notes)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["bookings"]
