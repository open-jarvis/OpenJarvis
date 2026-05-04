
"""Serena Google Docs operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_google_docs import (
    SerenaGoogleDocsConnectCheckTool,
    SerenaGoogleDocsEnvCheckTool,
    SerenaGoogleDocsPlanTool,
    SerenaGoogleDocsStatusTool,
    SerenaGoogleDocsBlockedDeleteTool,
    SerenaGoogleDocsAuditTool,
    SerenaGoogleDocsSaveOutputTool,
    SerenaGoogleDocsCreateReportTool,
    SerenaGoogleDocsCreateNoteTool,
    SerenaGoogleDocsExportTool,
    SerenaGoogleDocsCopyTool,
    SerenaGoogleDocsLinkTool,
    SerenaGoogleDocsUpdateTitleTool,
    SerenaGoogleDocsAppendTool,
    SerenaGoogleDocsReadTool,
    SerenaGoogleDocsCreateTool,
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


@google_docs.command("create")
@click.option("--title", required=True, help="Document title.")
@click.option("--content", required=True, help="Document content.")
@click.option("--drive-folder", default="", help="Drive folder path under configured root.")
@click.option("--doc-type", default="document", help="document, note, or report.")
def create(title: str, content: str, drive_folder: str, doc_type: str) -> None:
    """Create a professional Google Doc."""
    console = Console()
    result = SerenaGoogleDocsCreateTool().execute(
        title=title,
        content=content,
        drive_folder=drive_folder,
        doc_type=doc_type,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("read")
@click.option("--document-id", required=True, help="Google Doc document ID.")
@click.option("--preview-chars", default=2000, type=int, help="Maximum preview chars.")
def read(document_id: str, preview_chars: int) -> None:
    """Read Google Doc text."""
    console = Console()
    result = SerenaGoogleDocsReadTool().execute(
        document_id=document_id,
        preview_chars=preview_chars,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("append")
@click.option("--document-id", required=True, help="Google Doc document ID.")
@click.option("--content", required=True, help="Content to append.")
@click.option("--heading", default="", help="Optional heading.")
def append(document_id: str, content: str, heading: str) -> None:
    """Append content to a Google Doc."""
    console = Console()
    result = SerenaGoogleDocsAppendTool().execute(
        document_id=document_id,
        content=content,
        heading=heading,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("update-title")
@click.option("--document-id", required=True, help="Google Doc document ID.")
@click.option("--title", required=True, help="New document title.")
def update_title(document_id: str, title: str) -> None:
    """Update Google Doc title."""
    console = Console()
    result = SerenaGoogleDocsUpdateTitleTool().execute(
        document_id=document_id,
        title=title,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("link")
@click.option("--document-id", required=True, help="Google Doc document ID.")
def link(document_id: str) -> None:
    """Return existing Google Doc link without changing permissions."""
    console = Console()
    result = SerenaGoogleDocsLinkTool().execute(document_id=document_id)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("copy")
@click.option("--document-id", required=True, help="Source Google Doc document ID.")
@click.option("--title", required=True, help="Copy title.")
@click.option("--drive-folder", default="", help="Drive folder path under configured root.")
def copy(document_id: str, title: str, drive_folder: str) -> None:
    """Copy a Google Doc."""
    console = Console()
    result = SerenaGoogleDocsCopyTool().execute(
        document_id=document_id,
        title=title,
        drive_folder=drive_folder,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("export")
@click.option("--document-id", required=True, help="Google Doc document ID.")
@click.option("--format", default="pdf", help="pdf, docx, txt, or html.")
@click.option("--name", default="", help="Optional local export filename.")
def export(document_id: str, format: str, name: str) -> None:
    """Export a Google Doc to local file."""
    console = Console()
    result = SerenaGoogleDocsExportTool().execute(
        document_id=document_id,
        format=format,
        name=name,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("create-note")
@click.option("--title", required=True, help="Note title.")
@click.option("--content", required=True, help="Note content.")
@click.option("--drive-folder", default="", help="Drive folder path under configured root.")
def create_note(title: str, content: str, drive_folder: str) -> None:
    """Create a professional Google Docs note."""
    console = Console()
    result = SerenaGoogleDocsCreateNoteTool().execute(
        title=title,
        content=content,
        drive_folder=drive_folder,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("create-report")
@click.option("--title", required=True, help="Report title.")
@click.option("--content", required=True, help="Report content.")
@click.option("--drive-folder", default="", help="Drive folder path under configured root.")
def create_report(title: str, content: str, drive_folder: str) -> None:
    """Create a professional Google Docs report."""
    console = Console()
    result = SerenaGoogleDocsCreateReportTool().execute(
        title=title,
        content=content,
        drive_folder=drive_folder,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("save-output")
@click.option("--local-path", required=True, help="Serena output/report text file path.")
@click.option("--title", default="", help="Optional Google Doc title.")
@click.option("--drive-folder", default="Serena/Google Docs Outputs", help="Drive folder path under configured root.")
@click.option("--doc-type", default="report", help="document, note, or report.")
def save_output(local_path: str, title: str, drive_folder: str, doc_type: str) -> None:
    """Create a Google Doc from a Serena output/report text file."""
    console = Console()
    result = SerenaGoogleDocsSaveOutputTool().execute(
        local_path=local_path,
        title=title,
        drive_folder=drive_folder,
        doc_type=doc_type,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("audit")
@click.option("--query", default="", help="Optional search query.")
@click.option("--limit", default=50, type=int, help="Maximum Docs to audit.")
def audit(query: str, limit: int) -> None:
    """Audit Google Docs visible to Serena."""
    console = Console()
    result = SerenaGoogleDocsAuditTool().execute(query=query, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@google_docs.command("blocked-delete")
@click.option("--document-id", required=True, help="Google Doc document ID.")
@click.option("--reason", default="Delete requested.", help="Reason for attempted delete.")
def blocked_delete(document_id: str, reason: str) -> None:
    """Deliberately blocked Google Docs delete command for v1."""
    console = Console()
    result = SerenaGoogleDocsBlockedDeleteTool().execute(
        document_id=document_id,
        reason=reason,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["google_docs"]
