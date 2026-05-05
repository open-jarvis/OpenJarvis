
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


__all__ = ["membership"]
