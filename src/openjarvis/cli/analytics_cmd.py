
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
    SerenaAnalyticsGBPKeywordsTool,
    SerenaAnalyticsGBPSummaryTool,
    SerenaAnalyticsGBPPlanTool,
    SerenaAnalyticsGBPEnvCheckTool,
    SerenaAnalyticsWebsiteSummaryTool,
    SerenaAnalyticsGA4PlanTool,
    SerenaAnalyticsWordpressSummaryTool,
    SerenaAnalyticsWordpressPlanTool,
    SerenaAnalyticsCompareTool,
    SerenaAnalyticsSnapshotTool,
    SerenaAnalyticsFromFolderTool,
    SerenaAnalyticsFromFileTool,
    SerenaAnalyticsFromJsonTool,
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


@analytics.command("from-json")
@click.option("--json-text", required=True, help="Analytics JSON text.")
@click.option("--title", default="Serena Analytics JSON Snapshot", help="Snapshot title.")
@click.option("--source", default="provided-json", help="Analytics source.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
def from_json(json_text: str, title: str, source: str, business: str, date_range: str) -> None:
    """Create analytics snapshot from JSON text."""
    console = Console()
    result = SerenaAnalyticsFromJsonTool().execute(
        json_text=json_text,
        title=title,
        source=source,
        business=business,
        date_range=date_range,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("from-file")
@click.option("--path", required=True, help="Analytics JSON file path.")
@click.option("--title", default="Serena Analytics File Snapshot", help="Snapshot title.")
@click.option("--source", default="file", help="Analytics source.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
def from_file(path: str, title: str, source: str, business: str, date_range: str) -> None:
    """Create analytics snapshot from JSON file."""
    console = Console()
    result = SerenaAnalyticsFromFileTool().execute(
        path=path,
        title=title,
        source=source,
        business=business,
        date_range=date_range,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("from-folder")
@click.option("--folder", required=True, help="Folder containing JSON files.")
@click.option("--title", default="Serena Analytics Folder Snapshot", help="Snapshot title.")
@click.option("--source", default="folder", help="Analytics source.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--limit", default=10, type=int, help="Maximum files.")
def from_folder(folder: str, title: str, source: str, business: str, date_range: str, limit: int) -> None:
    """Create analytics snapshot from folder JSON files."""
    console = Console()
    result = SerenaAnalyticsFromFolderTool().execute(
        folder=folder,
        title=title,
        source=source,
        business=business,
        date_range=date_range,
        limit=limit,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("snapshot")
@click.option("--business", default="Serena Local Operator", help="Business/context.")
@click.option("--date-range", default="current local outputs", help="Date range.")
def snapshot(business: str, date_range: str) -> None:
    """Create Serena local operator analytics snapshot."""
    console = Console()
    result = SerenaAnalyticsSnapshotTool().execute(business=business, date_range=date_range)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("compare")
@click.option("--current-json", default="", help="Current JSON text.")
@click.option("--previous-json", default="", help="Previous JSON text.")
@click.option("--current-file", default="", help="Current JSON file.")
@click.option("--previous-file", default="", help="Previous JSON file.")
@click.option("--title", default="Serena Analytics Comparison", help="Comparison title.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--source", default="comparison", help="Analytics source.")
def compare(
    current_json: str,
    previous_json: str,
    current_file: str,
    previous_file: str,
    title: str,
    business: str,
    source: str,
) -> None:
    """Compare two analytics JSON payloads or files."""
    console = Console()
    result = SerenaAnalyticsCompareTool().execute(
        current_json=current_json,
        previous_json=previous_json,
        current_file=current_file,
        previous_file=previous_file,
        title=title,
        business=business,
        source=source,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("wordpress-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="last 30 days", help="Date range.")
@click.option("--goal", default="Analyze WordPress website performance.", help="Analytics goal.")
def wordpress_plan(business: str, date_range: str, goal: str) -> None:
    """Create a WordPress analytics plan."""
    console = Console()
    result = SerenaAnalyticsWordpressPlanTool().execute(business=business, date_range=date_range, goal=goal)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("wordpress-summary")
@click.option("--metrics", required=True, help="WordPress/WooCommerce/Jetpack metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--notes", default="", help="Optional notes.")
def wordpress_summary(metrics: str, business: str, date_range: str, notes: str) -> None:
    """Create a WordPress analytics summary from metrics."""
    console = Console()
    result = SerenaAnalyticsWordpressSummaryTool().execute(metrics=metrics, business=business, date_range=date_range, notes=notes)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("ga4-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="last 30 days", help="Date range.")
@click.option("--goal", default="Analyze GA4 website performance.", help="Analytics goal.")
def ga4_plan(business: str, date_range: str, goal: str) -> None:
    """Create a GA4 analytics plan."""
    console = Console()
    result = SerenaAnalyticsGA4PlanTool().execute(business=business, date_range=date_range, goal=goal)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("website-summary")
@click.option("--metrics", required=True, help="Website metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--source", default="website", help="Website analytics source.")
@click.option("--notes", default="", help="Optional notes.")
def website_summary(metrics: str, business: str, date_range: str, source: str, notes: str) -> None:
    """Create a website analytics summary from metrics."""
    console = Console()
    result = SerenaAnalyticsWebsiteSummaryTool().execute(
        metrics=metrics,
        business=business,
        date_range=date_range,
        source=source,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("gbp-env-check")
def gbp_env_check() -> None:
    """Check Google Business Profile analytics env configuration."""
    console = Console()
    result = SerenaAnalyticsGBPEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("gbp-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="last 30 days", help="Date range.")
@click.option("--goal", default="Analyze Google Business Profile performance.", help="Analytics goal.")
def gbp_plan(business: str, date_range: str, goal: str) -> None:
    """Create a Google Business Profile analytics plan."""
    console = Console()
    result = SerenaAnalyticsGBPPlanTool().execute(business=business, date_range=date_range, goal=goal)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("gbp-summary")
@click.option("--metrics", required=True, help="GBP metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--location", default="primary location", help="GBP location/profile.")
@click.option("--notes", default="", help="Optional notes.")
def gbp_summary(metrics: str, business: str, date_range: str, location: str, notes: str) -> None:
    """Create a Google Business Profile analytics summary."""
    console = Console()
    result = SerenaAnalyticsGBPSummaryTool().execute(
        metrics=metrics,
        business=business,
        date_range=date_range,
        location=location,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("gbp-keywords")
@click.option("--keywords", required=True, help="GBP keyword metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--location", default="primary location", help="GBP location/profile.")
def gbp_keywords(keywords: str, business: str, date_range: str, location: str) -> None:
    """Create a Google Business Profile keyword analytics summary."""
    console = Console()
    result = SerenaAnalyticsGBPKeywordsTool().execute(
        keywords=keywords,
        business=business,
        date_range=date_range,
        location=location,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["analytics"]
