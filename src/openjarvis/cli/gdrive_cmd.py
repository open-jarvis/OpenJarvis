
"""Serena Google Drive operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_gdrive import (
    SerenaGDriveEnvCheckTool,
    SerenaGDrivePlanTool,
    SerenaGDriveRootInfoTool,
    SerenaGDriveStatusTool,
    SerenaGDriveSaveTextTool,
    SerenaGDriveBlockedDeleteTool,
    SerenaGDriveAuditTool,
    SerenaGDriveSaveOutputTool,
    SerenaGDriveDownloadTool,
    SerenaGDriveUploadTool,
    SerenaGDriveShareLinkTool,
    SerenaGDriveFileInfoTool,
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


@gdrive.command("file-info")
@click.option("--file-id", required=True, help="Google Drive file/folder ID.")
def file_info(file_id: str) -> None:
    """Inspect Google Drive file/folder metadata."""
    console = Console()
    result = SerenaGDriveFileInfoTool().execute(file_id=file_id)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("share-link")
@click.option("--file-id", required=True, help="Google Drive file/folder ID.")
def share_link(file_id: str) -> None:
    """Return the existing Google Drive web link without changing permissions."""
    console = Console()
    result = SerenaGDriveShareLinkTool().execute(file_id=file_id)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("upload")
@click.option("--local-path", required=True, help="Local file path to upload.")
@click.option("--drive-folder", default="", help="Drive folder path under configured root.")
@click.option("--name", default="", help="Optional Drive filename.")
def upload(local_path: str, drive_folder: str, name: str) -> None:
    """Upload a local file to Google Drive."""
    console = Console()
    result = SerenaGDriveUploadTool().execute(
        local_path=local_path,
        drive_folder=drive_folder,
        name=name,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("download")
@click.option("--file-id", required=True, help="Google Drive file ID.")
@click.option("--name", default="", help="Optional local filename.")
def download(file_id: str, name: str) -> None:
    """Download a Google Drive file to local outputs/gdrive/downloads."""
    console = Console()
    result = SerenaGDriveDownloadTool().execute(file_id=file_id, name=name)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("save-text")
@click.option("--name", required=True, help="Drive file name.")
@click.option("--content", required=True, help="Text content to save.")
@click.option("--drive-folder", default="", help="Drive folder path under configured root.")
def save_text(name: str, content: str, drive_folder: str) -> None:
    """Save text content as a file in Google Drive."""
    console = Console()
    result = SerenaGDriveSaveTextTool().execute(
        name=name,
        content=content,
        drive_folder=drive_folder,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("save-output")
@click.option("--local-path", required=True, help="Serena output/report file path to save.")
@click.option("--drive-folder", default="Serena/Outputs", help="Drive folder path under configured root.")
@click.option("--name", default="", help="Optional Drive filename.")
def save_output(local_path: str, drive_folder: str, name: str) -> None:
    """Save a Serena output/report file to Google Drive."""
    console = Console()
    result = SerenaGDriveSaveOutputTool().execute(
        local_path=local_path,
        drive_folder=drive_folder,
        name=name,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("audit")
@click.option("--folder-id", default="", help="Optional Drive folder ID. Defaults to configured root.")
@click.option("--limit", default=100, type=int, help="Maximum items to audit.")
def audit(folder_id: str, limit: int) -> None:
    """Audit a Google Drive folder."""
    console = Console()
    result = SerenaGDriveAuditTool().execute(folder_id=folder_id, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@gdrive.command("blocked-delete")
@click.option("--file-id", required=True, help="Google Drive file ID.")
@click.option("--reason", default="Delete requested.", help="Reason for attempted delete.")
def blocked_delete(file_id: str, reason: str) -> None:
    """Deliberately blocked Google Drive delete command for v1."""
    console = Console()
    result = SerenaGDriveBlockedDeleteTool().execute(file_id=file_id, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["gdrive"]
