
"""Serena Reporting Full Operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_reporting import (
    SerenaReportingPlanTool,
    SerenaReportingStatusTool,
    SerenaReportingTemplateInfoTool,
    SerenaReportingTemplatesTool,
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


__all__ = ["reporting"]
