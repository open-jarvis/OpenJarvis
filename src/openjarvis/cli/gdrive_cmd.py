
"""Serena Google Drive operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_gdrive import (
    SerenaGDriveEnvCheckTool,
    SerenaGDrivePlanTool,
    SerenaGDriveRootInfoTool,
    SerenaGDriveStatusTool,
    SerenaGDriveMkdirTool,
    SerenaGDriveSearchTool,
    SerenaGDriveListTool,
    SerenaGDriveConnectCheckTool,
)


@click.group()
def gdrive() -> None:
    """Native Serena Google Drive operator tools."""


@gdrive.command("status")
def status() -> None:
    """Show Google Drive operator status."""
    console = Console()
    result = SerenaGDriveStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("env-check")
def env_check() -> None:
    """Check Google Drive env configuration without exposing secrets."""
    console = Console()
    result = SerenaGDriveEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("root-info")
def root_info() -> None:
    """Show configured Google Drive root info without exposing secrets."""
    console = Console()
    result = SerenaGDriveRootInfoTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("plan")
@click.option("--goal", required=True, help="Drive operation goal.")
@click.option("--operation", default="general", help="Planned operation.")
@click.option("--local-path", default="", help="Optional local source path.")
@click.option("--drive-folder", default="", help="Optional Drive folder path/name.")
def plan(goal: str, operation: str, local_path: str, drive_folder: str) -> None:
    """Create a Google Drive operation plan without API calls."""
    console = Console()
    result = SerenaGDrivePlanTool().execute(
        goal=goal,
        operation=operation,
        local_path=local_path,
        drive_folder=drive_folder,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("connect-check")
def connect_check() -> None:
    """Connect to Google Drive and verify configured root."""
    console = Console()
    result = SerenaGDriveConnectCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("list")
@click.option("--folder-id", default="", help="Optional Drive folder ID. Defaults to configured root.")
@click.option("--limit", default=25, type=int, help="Maximum items.")
def list_drive(folder_id: str, limit: int) -> None:
    """List Google Drive files/folders."""
    console = Console()
    result = SerenaGDriveListTool().execute(folder_id=folder_id, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("search")
@click.option("--query", required=True, help="Search text.")
@click.option("--limit", default=25, type=int, help="Maximum matches.")
def search(query: str, limit: int) -> None:
    """Search Google Drive."""
    console = Console()
    result = SerenaGDriveSearchTool().execute(query=query, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("mkdir")
@click.option("--folder-path", required=True, help="Folder path under configured Drive root.")
def mkdir(folder_path: str) -> None:
    """Create/find a Google Drive folder path."""
    console = Console()
    result = SerenaGDriveMkdirTool().execute(folder_path=folder_path)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["gdrive"]
