
"""Serena Google Docs operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_google_docs import (
    SerenaGoogleDocsConnectCheckTool,
    SerenaGoogleDocsEnvCheckTool,
    SerenaGoogleDocsPlanTool,
    SerenaGoogleDocsStatusTool,
)


@click.group("google-docs")
def google_docs() -> None:
    """Native Serena Google Docs operator tools."""


@google_docs.command("status")
def status() -> None:
    """Show Google Docs operator status."""
    console = Console()
    result = SerenaGoogleDocsStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("env-check")
def env_check() -> None:
    """Check Google Docs env configuration without exposing secrets."""
    console = Console()
    result = SerenaGoogleDocsEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("connect-check")
def connect_check() -> None:
    """Connect to Google Docs and Drive APIs."""
    console = Console()
    result = SerenaGoogleDocsConnectCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("plan")
@click.option("--goal", required=True, help="Google Docs operation goal.")
@click.option("--operation", default="general", help="Planned operation.")
@click.option("--title", default="", help="Optional document title.")
@click.option("--drive-folder", default="", help="Optional Drive folder path/name.")
def plan(goal: str, operation: str, title: str, drive_folder: str) -> None:
    """Create a Google Docs operation plan without changing Docs."""
    console = Console()
    result = SerenaGoogleDocsPlanTool().execute(
        goal=goal,
        operation=operation,
        title=title,
        drive_folder=drive_folder,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["google_docs"]
