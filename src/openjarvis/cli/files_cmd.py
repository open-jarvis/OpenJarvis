
"""Serena local file operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_files import (
    SerenaFilesAuditTool,
    SerenaFilesBackupPlanTool,
    SerenaFilesBackupTool,
    SerenaFilesCleanupCandidatesTool,
    SerenaFilesCopyTool,
    SerenaFilesIndexTool,
    SerenaFilesMoveTool,
    SerenaFilesReadTool,
    SerenaFilesSearchTool,
    SerenaFilesSnapshotTool,
    SerenaFilesSnapshotsTool,
    SerenaFilesStatusTool,
    SerenaFilesRootBackupTool,
    SerenaFilesRootCleanupCandidatesTool,
    SerenaFilesRootOrganizeTool,
    SerenaFilesRootBackupPlanTool,
    SerenaFilesRootAuditTool,
    SerenaFilesRootSearchTool,
    SerenaFilesRootIndexTool,
    SerenaFilesRootInfoTool,
    SerenaFilesRootsTool,
)


@click.group()
def files() -> None:
    """Native Serena local file operator tools."""


@files.command("status")
def status() -> None:
    """Show Serena file operator status."""
    console = Console()
    result = SerenaFilesStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("index")
@click.option("--folder", required=True, help="Folder to index.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=500, type=int, help="Maximum files.")
def index(folder: str, recursive: bool, limit: int) -> None:
    """Index files in a folder."""
    console = Console()
    result = SerenaFilesIndexTool().execute(folder=folder, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("search")
@click.option("--folder", required=True, help="Folder to search.")
@click.option("--query", required=True, help="Search query.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--content/--name-only", default=False, help="Search safe text file contents too.")
@click.option("--limit", default=100, type=int, help="Maximum matches.")
def search(folder: str, query: str, recursive: bool, content: bool, limit: int) -> None:
    """Search files by name and optionally content."""
    console = Console()
    result = SerenaFilesSearchTool().execute(
        folder=folder,
        query=query,
        recursive=recursive,
        content=content,
        limit=limit,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("read")
@click.option("--path", "file_path", required=True, help="File path.")
@click.option("--preview-chars", default=4000, type=int, help="Preview character count.")
def read(file_path: str, preview_chars: int) -> None:
    """Read a safe text file preview."""
    console = Console()
    result = SerenaFilesReadTool().execute(path=file_path, preview_chars=preview_chars)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("audit")
@click.option("--folder", required=True, help="Folder to audit.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=1000, type=int, help="Maximum files.")
def audit(folder: str, recursive: bool, limit: int) -> None:
    """Audit a folder."""
    console = Console()
    result = SerenaFilesAuditTool().execute(folder=folder, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("snapshot")
@click.option("--path", "file_path", required=True, help="File path.")
@click.option("--reason", default="manual-snapshot", help="Snapshot reason.")
def snapshot(file_path: str, reason: str) -> None:
    """Create a file snapshot."""
    console = Console()
    result = SerenaFilesSnapshotTool().execute(path=file_path, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("snapshots")
@click.option("--limit", default=50, type=int, help="Maximum snapshots.")
def snapshots(limit: int) -> None:
    """List file snapshots."""
    console = Console()
    result = SerenaFilesSnapshotsTool().execute(limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("copy")
@click.option("--path", "file_path", required=True, help="Source file.")
@click.option("--target-folder", required=True, help="Target folder.")
def copy_file(file_path: str, target_folder: str) -> None:
    """Copy a file without modifying the original."""
    console = Console()
    result = SerenaFilesCopyTool().execute(path=file_path, target_folder=target_folder)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("move")
@click.option("--path", "file_path", required=True, help="Source file.")
@click.option("--target-folder", required=True, help="Target folder.")
@click.option("--approved", is_flag=True, help="Required to move original file.")
def move_file(file_path: str, target_folder: str, approved: bool) -> None:
    """Move a file only with explicit approval."""
    console = Console()
    result = SerenaFilesMoveTool().execute(path=file_path, target_folder=target_folder, approved=approved)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("cleanup-candidates")
@click.option("--folder", required=True, help="Folder to scan.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=1000, type=int, help="Maximum files.")
def cleanup_candidates(folder: str, recursive: bool, limit: int) -> None:
    """Find cleanup candidates without deleting anything."""
    console = Console()
    result = SerenaFilesCleanupCandidatesTool().execute(folder=folder, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("backup-plan")
@click.option("--folder", required=True, help="Folder to plan backup for.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=5000, type=int, help="Maximum files.")
def backup_plan(folder: str, recursive: bool, limit: int) -> None:
    """Plan a backup without creating it."""
    console = Console()
    result = SerenaFilesBackupPlanTool().execute(folder=folder, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("backup")
@click.option("--folder", required=True, help="Folder to back up.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=5000, type=int, help="Maximum files.")
def backup(folder: str, recursive: bool, limit: int) -> None:
    """Create a zip backup."""
    console = Console()
    result = SerenaFilesBackupTool().execute(folder=folder, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("roots")
def roots() -> None:
    """List approved Serena file roots."""
    console = Console()
    result = SerenaFilesRootsTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("root-info")
@click.option("--root", required=True, help="Approved root alias.")
def root_info(root: str) -> None:
    """Show details for one approved file root."""
    console = Console()
    result = SerenaFilesRootInfoTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("root-index")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=500, type=int, help="Maximum files.")
def root_index(root: str, recursive: bool, limit: int) -> None:
    """Index an approved file root."""
    console = Console()
    result = SerenaFilesRootIndexTool().execute(root=root, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("root-search")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--query", required=True, help="Search query.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--content/--name-only", default=False, help="Search safe text file contents too.")
@click.option("--limit", default=100, type=int, help="Maximum matches.")
def root_search(root: str, query: str, recursive: bool, content: bool, limit: int) -> None:
    """Search an approved file root."""
    console = Console()
    result = SerenaFilesRootSearchTool().execute(
        root=root,
        query=query,
        recursive=recursive,
        content=content,
        limit=limit,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("root-audit")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=1000, type=int, help="Maximum files.")
def root_audit(root: str, recursive: bool, limit: int) -> None:
    """Audit an approved file root."""
    console = Console()
    result = SerenaFilesRootAuditTool().execute(root=root, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("root-backup-plan")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=5000, type=int, help="Maximum files.")
def root_backup_plan(root: str, recursive: bool, limit: int) -> None:
    """Plan backup for an approved file root."""
    console = Console()
    result = SerenaFilesRootBackupPlanTool().execute(root=root, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("root-backup")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=5000, type=int, help="Maximum files.")
def root_backup(root: str, recursive: bool, limit: int) -> None:
    """Create backup for an approved file root."""
    console = Console()
    result = SerenaFilesRootBackupTool().execute(root=root, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("root-organize")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=500, type=int, help="Maximum files.")
def root_organize(root: str, recursive: bool, limit: int) -> None:
    """Organize an approved file root by copying files into categorized folders."""
    console = Console()
    result = SerenaFilesRootOrganizeTool().execute(root=root, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@files.command("root-cleanup-candidates")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=1000, type=int, help="Maximum files.")
def root_cleanup_candidates(root: str, recursive: bool, limit: int) -> None:
    """Find cleanup candidates in an approved file root without deleting anything."""
    console = Console()
    result = SerenaFilesRootCleanupCandidatesTool().execute(root=root, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["files"]
