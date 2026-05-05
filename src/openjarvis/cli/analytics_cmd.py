
"""Serena Analytics Full Operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_analytics import (
    SerenaAnalyticsEnvCheckTool,
    SerenaAnalyticsPlanTool,
    SerenaAnalyticsSourceInfoTool,
    SerenaAnalyticsSourceListTool,
    SerenaAnalyticsStatusTool,
)


@click.group()
def analytics() -> None:
    """Native Serena Analytics operator tools."""


@analytics.command("status")
def status() -> None:
    """Show Analytics operator status."""
    console = Console()
    result = SerenaAnalyticsStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("env-check")
def env_check() -> None:
    """Check analytics environment configuration without exposing secrets."""
    console = Console()
    result = SerenaAnalyticsEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("source-list")
def source_list() -> None:
    """List registered analytics sources."""
    console = Console()
    result = SerenaAnalyticsSourceListTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("source-info")
@click.option("--source", required=True, help="Source ID, e.g. wordpress, ga4, google-business-profile, facebook.")
def source_info(source: str) -> None:
    """Show details for one analytics source."""
    console = Console()
    result = SerenaAnalyticsSourceInfoTool().execute(source=source)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("plan")
@click.option("--goal", required=True, help="Analytics goal.")
@click.option("--source", default="serena-operator", help="Analytics source.")
@click.option("--date-range", default="last 30 days", help="Date range.")
@click.option("--business", default="General Business", help="Business/context.")
def plan(goal: str, source: str, date_range: str, business: str) -> None:
    """Create an analytics operation plan."""
    console = Console()
    result = SerenaAnalyticsPlanTool().execute(goal=goal, source=source, date_range=date_range, business=business)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["analytics"]
