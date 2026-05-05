
"""Serena Reporting Full Operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_reporting import (
    SerenaReportingPlanTool,
    SerenaReportingStatusTool,
    SerenaReportingTemplateInfoTool,
    SerenaReportingTemplatesTool,
    SerenaReportingFromFolderTool,
    SerenaReportingFromFileTool,
    SerenaReportingFromJsonTool,
    SerenaReportingFromTextTool,
)


@click.group()
def reporting() -> None:
    """Native Serena Reporting operator tools."""


@reporting.command("status")
def status() -> None:
    """Show Reporting operator status."""
    console = Console()
    result = SerenaReportingStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@reporting.command("plan")
@click.option("--goal", required=True, help="Reporting goal.")
@click.option("--report-type", default="activity-summary", help="Report type/template.")
@click.option("--source", default="local Serena outputs", help="Source material.")
@click.option("--target", default="local markdown report", help="Target output.")
def plan(goal: str, report_type: str, source: str, target: str) -> None:
    """Create a reporting operation plan."""
    console = Console()
    result = SerenaReportingPlanTool().execute(goal=goal, report_type=report_type, source=source, target=target)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@reporting.command("templates")
def templates() -> None:
    """List report templates."""
    console = Console()
    result = SerenaReportingTemplatesTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@reporting.command("template-info")
@click.option("--template", required=True, help="Template ID.")
def template_info(template: str) -> None:
    """Show report template details."""
    console = Console()
    result = SerenaReportingTemplateInfoTool().execute(template=template)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@reporting.command("from-text")
@click.option("--text", required=True, help="Text to report on.")
@click.option("--title", default="Serena Text Report", help="Report title.")
@click.option("--report-type", default="activity-summary", help="Report type/template.")
def from_text(text: str, title: str, report_type: str) -> None:
    """Create a report from provided text."""
    console = Console()
    result = SerenaReportingFromTextTool().execute(text=text, title=title, report_type=report_type)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@reporting.command("from-json")
@click.option("--json-text", required=True, help="JSON text to report on.")
@click.option("--title", default="Serena JSON Report", help="Report title.")
@click.option("--report-type", default="activity-summary", help="Report type/template.")
def from_json(json_text: str, title: str, report_type: str) -> None:
    """Create a report from JSON text."""
    console = Console()
    result = SerenaReportingFromJsonTool().execute(json_text=json_text, title=title, report_type=report_type)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@reporting.command("from-file")
@click.option("--path", required=True, help="Source file path.")
@click.option("--title", default="Serena File Report", help="Report title.")
@click.option("--report-type", default="activity-summary", help="Report type/template.")
@click.option("--max-chars", default=20000, type=int, help="Maximum source characters.")
def from_file(path: str, title: str, report_type: str, max_chars: int) -> None:
    """Create a report from a local file."""
    console = Console()
    result = SerenaReportingFromFileTool().execute(path=path, title=title, report_type=report_type, max_chars=max_chars)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@reporting.command("from-folder")
@click.option("--folder", required=True, help="Source folder path.")
@click.option("--title", default="Serena Folder Report", help="Report title.")
@click.option("--report-type", default="activity-summary", help="Report type/template.")
@click.option("--limit", default=10, type=int, help="Maximum files.")
@click.option("--max-chars-per-file", default=4000, type=int, help="Maximum chars per file.")
def from_folder(folder: str, title: str, report_type: str, limit: int, max_chars_per_file: int) -> None:
    """Create a report from a local folder."""
    console = Console()
    result = SerenaReportingFromFolderTool().execute(
        folder=folder,
        title=title,
        report_type=report_type,
        limit=limit,
        max_chars_per_file=max_chars_per_file,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["reporting"]
