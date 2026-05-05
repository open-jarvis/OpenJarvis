
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


__all__ = ["membership"]
