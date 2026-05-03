
"""Serena document operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_documents import (
    SerenaDocumentsClassifyTool,
    SerenaDocumentsExtractTool,
    SerenaDocumentsIndexTool,
    SerenaDocumentsInspectTool,
    SerenaDocumentsReadTool,
    SerenaDocumentsReportTool,
    SerenaDocumentsStatusTool,
    SerenaDocumentsSummarizeTool,
    SerenaDocumentsSnapshotsTool,
    SerenaDocumentsAuditTool,
    SerenaDocumentsSnapshotTool,
    SerenaDocumentsLibraryTool,
    SerenaDocumentsImportTool,
)


@click.group()
def documents() -> None:
    """Native Serena document operator tools."""


@documents.command("status")
def status() -> None:
    """Show Serena document operator status."""
    console = Console()
    result = SerenaDocumentsStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("index")
@click.option("--folder", required=True, help="Folder to scan.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=100, type=int, help="Maximum files to list.")
def index(folder: str, recursive: bool, limit: int) -> None:
    """Index supported documents in a folder."""
    console = Console()
    result = SerenaDocumentsIndexTool().execute(folder=folder, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("read")
@click.option("--path", "file_path", required=True, help="Document path.")
@click.option("--preview-chars", default=2000, type=int, help="Preview character count.")
def read(file_path: str, preview_chars: int) -> None:
    """Read/extract a supported document."""
    console = Console()
    result = SerenaDocumentsReadTool().execute(path=file_path, preview_chars=preview_chars)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("extract")
@click.option("--path", "file_path", required=True, help="Document path.")
def extract(file_path: str) -> None:
    """Extract text from a supported document."""
    console = Console()
    result = SerenaDocumentsExtractTool().execute(path=file_path)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("summarize")
@click.option("--path", "file_path", required=True, help="Document path.")
@click.option("--max-sentences", default=6, type=int, help="Maximum summary sentences.")
def summarize(file_path: str, max_sentences: int) -> None:
    """Summarize a supported document."""
    console = Console()
    result = SerenaDocumentsSummarizeTool().execute(path=file_path, max_sentences=max_sentences)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("classify")
@click.option("--path", "file_path", required=True, help="Document path.")
def classify(file_path: str) -> None:
    """Classify a supported document."""
    console = Console()
    result = SerenaDocumentsClassifyTool().execute(path=file_path)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("inspect")
@click.option("--path", "file_path", required=True, help="Document path.")
def inspect(file_path: str) -> None:
    """Inspect a supported document."""
    console = Console()
    result = SerenaDocumentsInspectTool().execute(path=file_path)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("report")
@click.option("--path", "file_path", required=True, help="Document path.")
def report(file_path: str) -> None:
    """Create a full document operator report."""
    console = Console()
    result = SerenaDocumentsReportTool().execute(path=file_path)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("import")
@click.option("--path", "file_path", required=True, help="Source document path.")
@click.option("--category", default="general", help="Library category/folder.")
def import_document(file_path: str, category: str) -> None:
    """Import a document into Serena's controlled document library."""
    console = Console()
    result = SerenaDocumentsImportTool().execute(path=file_path, category=category)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("library")
@click.option("--category", default="", help="Optional library category/folder.")
@click.option("--limit", default=50, type=int, help="Maximum files to show.")
def library(category: str, limit: int) -> None:
    """List Serena's controlled document library."""
    console = Console()
    result = SerenaDocumentsLibraryTool().execute(category=category, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("snapshot")
@click.option("--path", "file_path", required=True, help="Document path.")
@click.option("--reason", default="manual-snapshot", help="Snapshot reason.")
def snapshot(file_path: str, reason: str) -> None:
    """Create a document safety snapshot."""
    console = Console()
    result = SerenaDocumentsSnapshotTool().execute(path=file_path, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("snapshots")
@click.option("--limit", default=50, type=int, help="Maximum snapshots to show.")
def snapshots(limit: int) -> None:
    """List Serena document snapshots."""
    console = Console()
    result = SerenaDocumentsSnapshotsTool().execute(limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@documents.command("audit")
@click.option("--folder", default="", help="Optional folder to audit. Defaults to Serena's document library.")
@click.option("--recursive/--no-recursive", default=True, help="Scan recursively.")
@click.option("--limit", default=200, type=int, help="Maximum files to audit.")
def audit(folder: str, recursive: bool, limit: int) -> None:
    """Run Serena's document library audit dashboard."""
    console = Console()
    result = SerenaDocumentsAuditTool().execute(folder=folder, recursive=recursive, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["documents"]
