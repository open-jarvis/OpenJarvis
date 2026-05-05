
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


__all__ = ["analytics"]
