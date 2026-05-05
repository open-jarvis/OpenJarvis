
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
    SerenaBookingsCalendarCancelPlanTool,
    SerenaBookingsCalendarUpdatePlanTool,
    SerenaBookingsCalendarCreatePlanTool,
    SerenaBookingsCalendarHandoffTool,
    SerenaBookingsFollowUpPlanTool,
    SerenaBookingsNoShowRiskTool,
    SerenaBookingsReminderStatusTool,
    SerenaBookingsReminderScheduleTool,
    SerenaBookingsReminderPlanTool,
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


@bookings.command("reminder-plan")
@click.option("--booking-id", required=True, help="Booking ID.")
@click.option("--channels", default="email/sms/whatsapp planned", help="Reminder channels.")
@click.option("--timing", default="24 hours before appointment", help="Reminder timing.")
@click.option("--message-type", default="minimal appointment reminder", help="Message type.")
@click.option("--notes", default="", help="Notes.")
def reminder_plan(booking_id: str, channels: str, timing: str, message_type: str, notes: str) -> None:
    """Create an appointment reminder plan."""
    console = Console()
    result = SerenaBookingsReminderPlanTool().execute(
        booking_id=booking_id,
        channels=channels,
        timing=timing,
        message_type=message_type,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("reminder-schedule")
@click.option("--booking-id", required=True, help="Booking ID.")
@click.option("--reminder-time", required=True, help="Reminder time.")
@click.option("--channel", default="manual/local", help="Reminder channel.")
@click.option("--approved", is_flag=True, help="Approval flag for sensitive reminder messages.")
@click.option("--message", default="", help="Reminder message preview.")
def reminder_schedule(booking_id: str, reminder_time: str, channel: str, approved: bool, message: str) -> None:
    """Create a local reminder schedule record."""
    console = Console()
    result = SerenaBookingsReminderScheduleTool().execute(
        booking_id=booking_id,
        reminder_time=reminder_time,
        channel=channel,
        approved=approved,
        message=message,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("reminder-status")
@click.option("--booking-id", required=True, help="Booking ID.")
def reminder_status(booking_id: str) -> None:
    """Show local reminder status for a booking."""
    console = Console()
    result = SerenaBookingsReminderStatusTool().execute(booking_id=booking_id)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("no-show-risk")
@click.option("--booking-id", required=True, help="Booking ID.")
def no_show_risk(booking_id: str) -> None:
    """Estimate no-show risk from local booking/reminder data."""
    console = Console()
    result = SerenaBookingsNoShowRiskTool().execute(booking_id=booking_id)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("follow-up-plan")
@click.option("--booking-id", required=True, help="Booking ID.")
@click.option("--reason", default="Follow-up after appointment.", help="Follow-up reason.")
@click.option("--timing", default="after appointment", help="Follow-up timing.")
@click.option("--channel", default="manual/local", help="Follow-up channel.")
@click.option("--notes", default="", help="Notes.")
def follow_up_plan(booking_id: str, reason: str, timing: str, channel: str, notes: str) -> None:
    """Create a follow-up plan."""
    console = Console()
    result = SerenaBookingsFollowUpPlanTool().execute(
        booking_id=booking_id,
        reason=reason,
        timing=timing,
        channel=channel,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("calendar-handoff")
@click.option("--booking-id", required=True, help="Booking ID.")
@click.option("--operation", default="create", help="Calendar operation: create/update/cancel.")
@click.option("--approved", is_flag=True, help="Approval flag.")
@click.option("--notes", default="", help="Notes.")
def calendar_handoff(booking_id: str, operation: str, approved: bool, notes: str) -> None:
    """Create Calendar handoff record for a booking."""
    console = Console()
    result = SerenaBookingsCalendarHandoffTool().execute(
        booking_id=booking_id,
        operation=operation,
        approved=approved,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("calendar-create-plan")
@click.option("--booking-id", required=True, help="Booking ID.")
@click.option("--add-meet", is_flag=True, help="Plan a Google Meet link.")
@click.option("--approved", is_flag=True, help="Approval flag.")
def calendar_create_plan(booking_id: str, add_meet: bool, approved: bool) -> None:
    """Create Calendar event creation plan."""
    console = Console()
    result = SerenaBookingsCalendarCreatePlanTool().execute(
        booking_id=booking_id,
        add_meet=add_meet,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("calendar-update-plan")
@click.option("--booking-id", required=True, help="Booking ID.")
@click.option("--new-date", default="", help="New date.")
@click.option("--new-time", default="", help="New time.")
@click.option("--reason", default="Calendar update requested.", help="Reason.")
@click.option("--approved", is_flag=True, help="Required approval flag.")
def calendar_update_plan(booking_id: str, new_date: str, new_time: str, reason: str, approved: bool) -> None:
    """Create Calendar event update/reschedule plan."""
    console = Console()
    result = SerenaBookingsCalendarUpdatePlanTool().execute(
        booking_id=booking_id,
        new_date=new_date,
        new_time=new_time,
        reason=reason,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@bookings.command("calendar-cancel-plan")
@click.option("--booking-id", required=True, help="Booking ID.")
@click.option("--reason", default="Calendar cancellation requested.", help="Reason.")
@click.option("--approved", is_flag=True, help="Required approval flag.")
def calendar_cancel_plan(booking_id: str, reason: str, approved: bool) -> None:
    """Create Calendar event cancellation plan."""
    console = Console()
    result = SerenaBookingsCalendarCancelPlanTool().execute(
        booking_id=booking_id,
        reason=reason,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["bookings"]
