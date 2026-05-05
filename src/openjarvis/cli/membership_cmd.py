
"""Serena Membership / Subscriptions / Patient Programmes Full Operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_membership import (
    SerenaMembershipEnvCheckTool,
    SerenaMembershipPlanTool,
    SerenaMembershipSourceInfoTool,
    SerenaMembershipSourceListTool,
    SerenaMembershipStatusTool,
    SerenaMembershipBookingHandoffTool,
    SerenaMembershipAccountingHandoffTool,
    SerenaMembershipPaymentHandoffTool,
    SerenaMembershipSubscriptionRecordTool,
    SerenaMembershipSubscriptionPlanTool,
    SerenaMembershipRenewalPlanTool,
    SerenaMembershipPauseMembershipPlanTool,
    SerenaMembershipCancelMembershipPlanTool,
    SerenaMembershipEnrollMemberTool,
    SerenaMembershipEnrollmentPlanTool,
    SerenaMembershipUpdateMemberStatusTool,
    SerenaMembershipMemberListTool,
    SerenaMembershipMemberInfoTool,
    SerenaMembershipCreateMemberProfileTool,
    SerenaMembershipPlanInfoTool,
    SerenaMembershipPlanListTool,
)


@click.group()
def membership() -> None:
    """Native Serena Membership / Subscriptions / Patient Programmes operator tools."""


@membership.command("status")
def status() -> None:
    """Show Membership operator status."""
    console = Console()
    result = SerenaMembershipStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("env-check")
def env_check() -> None:
    """Check membership environment without exposing secrets."""
    console = Console()
    result = SerenaMembershipEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("source-list")
def source_list() -> None:
    """List registered membership/subscription/programme sources."""
    console = Console()
    result = SerenaMembershipSourceListTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("source-info")
@click.option("--source", required=True, help="Source ID, e.g. accounting-payments, bookings, local-membership.")
def source_info(source: str) -> None:
    """Show details for one membership/subscription/programme source."""
    console = Console()
    result = SerenaMembershipSourceInfoTool().execute(source=source)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("plan")
@click.option("--goal", required=True, help="Membership/subscription/programme goal.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--member", default="not specified", help="Member/patient/client label.")
@click.option("--membership-plan", default="not specified", help="Membership plan.")
@click.option("--programme", default="not specified", help="Programme.")
@click.option("--payment-context", default="not specified", help="Payment context.")
def plan(goal: str, business: str, member: str, membership_plan: str, programme: str, payment_context: str) -> None:
    """Create a membership/subscription/programme operation plan."""
    console = Console()
    result = SerenaMembershipPlanTool().execute(
        goal=goal,
        business=business,
        member=member,
        membership_plan=membership_plan,
        programme=programme,
        payment_context=payment_context,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("plan-list")
def plan_list() -> None:
    """List local membership/programme plan templates."""
    console = Console()
    result = SerenaMembershipPlanListTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("plan-info")
@click.option("--plan-id", required=True, help="Plan ID, e.g. twelve-week-care.")
def plan_info(plan_id: str) -> None:
    """Show details for one membership/programme plan template."""
    console = Console()
    result = SerenaMembershipPlanInfoTool().execute(plan_id=plan_id)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("create-member-profile")
@click.option("--member-id", default="", help="Member ID.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--member-name", required=True, help="Member/patient/client name.")
@click.option("--contact", default="", help="Contact detail.")
@click.option("--membership-plan", default="not assigned", help="Membership plan.")
@click.option("--programme", default="not assigned", help="Programme.")
@click.option("--payment-status", default="not started", help="Payment status.")
@click.option("--status", default="profile_created", help="Member status.")
@click.option("--notes", default="", help="Notes.")
@click.option("--sensitive", is_flag=True, help="Mark as sensitive patient/client data.")
def create_member_profile(member_id: str, business: str, member_name: str, contact: str, membership_plan: str, programme: str, payment_status: str, status: str, notes: str, sensitive: bool) -> None:
    """Create local member profile."""
    console = Console()
    result = SerenaMembershipCreateMemberProfileTool().execute(
        member_id=member_id,
        business=business,
        member_name=member_name,
        contact=contact,
        membership_plan=membership_plan,
        programme=programme,
        payment_status=payment_status,
        status=status,
        notes=notes,
        sensitive=sensitive,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("member-info")
@click.option("--member-id", required=True, help="Member ID.")
def member_info(member_id: str) -> None:
    """Show local member profile details."""
    console = Console()
    result = SerenaMembershipMemberInfoTool().execute(member_id=member_id)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("member-list")
@click.option("--business", default="", help="Optional business filter.")
@click.option("--status", default="", help="Optional status filter.")
@click.option("--limit", default=20, type=int, help="Maximum rows.")
def member_list(business: str, status: str, limit: int) -> None:
    """List local member profiles."""
    console = Console()
    result = SerenaMembershipMemberListTool().execute(business=business, status=status, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("update-member-status")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--new-status", required=True, help="New status.")
@click.option("--reason", default="Status update requested.", help="Reason.")
@click.option("--approved", is_flag=True, help="Approval flag for guarded changes.")
def update_member_status(member_id: str, new_status: str, reason: str, approved: bool) -> None:
    """Create local member status update record."""
    console = Console()
    result = SerenaMembershipUpdateMemberStatusTool().execute(
        member_id=member_id,
        new_status=new_status,
        reason=reason,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("enrollment-plan")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--plan-id", default="not specified", help="Membership plan ID.")
@click.option("--programme", default="not specified", help="Programme.")
@click.option("--payment-model", default="not specified", help="Payment model.")
@click.option("--notes", default="", help="Notes.")
def enrollment_plan(member_id: str, plan_id: str, programme: str, payment_model: str, notes: str) -> None:
    """Create local enrollment plan."""
    console = Console()
    result = SerenaMembershipEnrollmentPlanTool().execute(
        member_id=member_id,
        plan_id=plan_id,
        programme=programme,
        payment_model=payment_model,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("enroll-member")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--plan-id", required=True, help="Membership plan ID.")
@click.option("--programme", default="not specified", help="Programme.")
@click.option("--start-date", default="not specified", help="Start date.")
@click.option("--end-date", default="not specified", help="End date.")
@click.option("--payment-model", default="not specified", help="Payment model.")
@click.option("--payment-status", default="pending", help="Payment status.")
@click.option("--approved", is_flag=True, help="Approval flag for sensitive enrollment.")
@click.option("--notes", default="", help="Notes.")
def enroll_member(member_id: str, plan_id: str, programme: str, start_date: str, end_date: str, payment_model: str, payment_status: str, approved: bool, notes: str) -> None:
    """Create local member enrollment record."""
    console = Console()
    result = SerenaMembershipEnrollMemberTool().execute(
        member_id=member_id,
        plan_id=plan_id,
        programme=programme,
        start_date=start_date,
        end_date=end_date,
        payment_model=payment_model,
        payment_status=payment_status,
        approved=approved,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("cancel-membership-plan")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--reason", default="Cancellation requested.", help="Reason.")
@click.option("--effective-date", default="not specified", help="Effective date.")
@click.option("--approved", is_flag=True, help="Required approval flag.")
def cancel_membership_plan(member_id: str, reason: str, effective_date: str, approved: bool) -> None:
    """Create local membership cancellation plan."""
    console = Console()
    result = SerenaMembershipCancelMembershipPlanTool().execute(
        member_id=member_id,
        reason=reason,
        effective_date=effective_date,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("pause-membership-plan")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--reason", default="Pause requested.", help="Reason.")
@click.option("--pause-start", default="not specified", help="Pause start.")
@click.option("--pause-end", default="not specified", help="Pause end.")
@click.option("--approved", is_flag=True, help="Required approval flag.")
def pause_membership_plan(member_id: str, reason: str, pause_start: str, pause_end: str, approved: bool) -> None:
    """Create local membership pause plan."""
    console = Console()
    result = SerenaMembershipPauseMembershipPlanTool().execute(
        member_id=member_id,
        reason=reason,
        pause_start=pause_start,
        pause_end=pause_end,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("renewal-plan")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--renewal-date", default="not specified", help="Renewal date.")
@click.option("--next-plan-id", default="same/current plan", help="Next plan ID.")
@click.option("--notes", default="", help="Notes.")
def renewal_plan(member_id: str, renewal_date: str, next_plan_id: str, notes: str) -> None:
    """Create local membership/programme renewal plan."""
    console = Console()
    result = SerenaMembershipRenewalPlanTool().execute(
        member_id=member_id,
        renewal_date=renewal_date,
        next_plan_id=next_plan_id,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("subscription-plan")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--billing-model", default="monthly subscription", help="Billing model.")
@click.option("--amount", default=0.0, type=float, help="Amount.")
@click.option("--currency", default="ZAR", help="Currency.")
@click.option("--interval", default="monthly", help="Billing interval.")
@click.option("--start-date", default="not specified", help="Start date.")
@click.option("--notes", default="", help="Notes.")
def subscription_plan(member_id: str, billing_model: str, amount: float, currency: str, interval: str, start_date: str, notes: str) -> None:
    """Create local subscription/payment plan."""
    console = Console()
    result = SerenaMembershipSubscriptionPlanTool().execute(
        member_id=member_id,
        billing_model=billing_model,
        amount=amount,
        currency=currency,
        interval=interval,
        start_date=start_date,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("subscription-record")
@click.option("--subscription-id", default="", help="Subscription ID.")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--billing-model", default="monthly subscription", help="Billing model.")
@click.option("--amount", default=0.0, type=float, help="Amount.")
@click.option("--currency", default="ZAR", help="Currency.")
@click.option("--interval", default="monthly", help="Billing interval.")
@click.option("--status", default="local_pending", help="Status.")
@click.option("--payment-reference", default="", help="Payment reference.")
@click.option("--approved", is_flag=True, help="Approval flag for amount/payment record.")
@click.option("--notes", default="", help="Notes.")
def subscription_record(subscription_id: str, member_id: str, billing_model: str, amount: float, currency: str, interval: str, status: str, payment_reference: str, approved: bool, notes: str) -> None:
    """Create local subscription record."""
    console = Console()
    result = SerenaMembershipSubscriptionRecordTool().execute(
        subscription_id=subscription_id,
        member_id=member_id,
        billing_model=billing_model,
        amount=amount,
        currency=currency,
        interval=interval,
        status=status,
        payment_reference=payment_reference,
        approved=approved,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("payment-handoff")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--amount", default=0.0, type=float, help="Amount.")
@click.option("--currency", default="ZAR", help="Currency.")
@click.option("--payment-reason", default="membership/subscription payment", help="Payment reason.")
@click.option("--approved", is_flag=True, help="Approval flag for payment amount.")
@click.option("--notes", default="", help="Notes.")
def payment_handoff(member_id: str, amount: float, currency: str, payment_reason: str, approved: bool, notes: str) -> None:
    """Create Accounting/PayFast payment handoff."""
    console = Console()
    result = SerenaMembershipPaymentHandoffTool().execute(
        member_id=member_id,
        amount=amount,
        currency=currency,
        payment_reason=payment_reason,
        approved=approved,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("accounting-handoff")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--handoff-type", default="invoice/payment/subscription handoff", help="Accounting handoff type.")
@click.option("--amount", default=0.0, type=float, help="Amount.")
@click.option("--approved", is_flag=True, help="Approval flag for amount.")
@click.option("--notes", default="", help="Notes.")
def accounting_handoff(member_id: str, handoff_type: str, amount: float, approved: bool, notes: str) -> None:
    """Create Accounting handoff."""
    console = Console()
    result = SerenaMembershipAccountingHandoffTool().execute(
        member_id=member_id,
        handoff_type=handoff_type,
        amount=amount,
        approved=approved,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@membership.command("booking-handoff")
@click.option("--member-id", required=True, help="Member ID.")
@click.option("--appointment-type", default="programme appointment", help="Appointment type.")
@click.option("--preferred-date", default="not specified", help="Preferred date.")
@click.option("--preferred-time", default="not specified", help="Preferred time.")
@click.option("--notes", default="", help="Notes.")
def booking_handoff(member_id: str, appointment_type: str, preferred_date: str, preferred_time: str, notes: str) -> None:
    """Create Bookings handoff."""
    console = Console()
    result = SerenaMembershipBookingHandoffTool().execute(
        member_id=member_id,
        appointment_type=appointment_type,
        preferred_date=preferred_date,
        preferred_time=preferred_time,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["membership"]
