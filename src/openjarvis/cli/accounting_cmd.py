
"""Serena Accounting / Payments / Payroll / Tax Full Operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_accounting import (
    SerenaAccountingEnvCheckTool,
    SerenaAccountingPlanTool,
    SerenaAccountingSourceInfoTool,
    SerenaAccountingSourceListTool,
    SerenaAccountingStatusTool,
)


@click.group()
def accounting() -> None:
    """Native Serena Accounting / Payments / Payroll / Tax operator tools."""


@accounting.command("status")
def status() -> None:
    """Show Accounting operator status."""
    console = Console()
    result = SerenaAccountingStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("env-check")
def env_check() -> None:
    """Check accounting/payment environment without exposing secrets."""
    console = Console()
    result = SerenaAccountingEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("source-list")
def source_list() -> None:
    """List registered accounting/payment sources."""
    console = Console()
    result = SerenaAccountingSourceListTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("source-info")
@click.option("--source", required=True, help="Source ID, e.g. xero, payfast, local-ledger.")
def source_info(source: str) -> None:
    """Show details for one accounting/payment source."""
    console = Console()
    result = SerenaAccountingSourceInfoTool().execute(source=source)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("plan")
@click.option("--goal", required=True, help="Accounting/payment goal.")
@click.option("--source", default="local-ledger", help="Accounting/payment source.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--period", default="current period", help="Accounting period.")
def plan(goal: str, source: str, business: str, period: str) -> None:
    """Create an accounting/payment operation plan."""
    console = Console()
    result = SerenaAccountingPlanTool().execute(goal=goal, source=source, business=business, period=period)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["accounting"]
