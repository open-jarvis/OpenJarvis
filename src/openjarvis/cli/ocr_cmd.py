
"""Serena OCR / Live Vision operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_ocr import (
    SerenaOCRCameraStatusTool,
    SerenaOCREnginesTool,
    SerenaOCRPlanTool,
    SerenaOCRSafetyPolicyTool,
    SerenaOCRStatusTool,
    SerenaOCRBlockedDeleteTool,
    SerenaOCRBlockedHiddenWatchTool,
    SerenaOCRAuditTool,
    SerenaOCRArtifactsTool,
    SerenaOCRDocumentFlowTool,
    SerenaOCRToDocumentTool,
    SerenaOCRToDriveTool,
    SerenaOCRToGoogleDocTool,
    SerenaOCRExtractLiveTextTool,
    SerenaOCRBestFrameTool,
    SerenaOCRLiveWatchTextTool,
    SerenaOCRLiveWatchDocTool,
    SerenaOCRLiveReportTool,
    SerenaOCRLiveSnapshotTool,
    SerenaOCRLiveStopTool,
    SerenaOCRLiveStatusTool,
    SerenaOCRLiveStartTool,
    SerenaOCRDescribeCaptureTool,
    SerenaOCRCaptureDocTool,
    SerenaOCRCaptureTool,
    SerenaOCRCamerasTool,
    SerenaOCRExtractPDFTool,
    SerenaOCRExtractImageTool,
    SerenaOCRReadabilityTool,
    SerenaOCRInspectImageTool,
)


@click.group()
def ocr() -> None:
    """Native Serena OCR / Live Vision operator tools."""


@ocr.command("status")
def status() -> None:
    """Show OCR / Live Vision operator status."""
    console = Console()
    result = SerenaOCRStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("engines")
def engines() -> None:
    """Inspect OCR/image/camera engine availability."""
    console = Console()
    result = SerenaOCREnginesTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("camera-status")
@click.option("--max-indexes", default=5, type=int, help="Maximum camera indexes to probe.")
def camera_status(max_indexes: int) -> None:
    """Probe local cameras without leaving camera open."""
    console = Console()
    result = SerenaOCRCameraStatusTool().execute(max_indexes=max_indexes)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("plan")
@click.option("--goal", required=True, help="OCR/live vision goal.")
@click.option("--mode", default="document", help="document, text, scene, object, assist.")
@click.option("--source", default="", help="Optional source path or camera.")
def plan(goal: str, mode: str, source: str) -> None:
    """Create OCR/live vision operation plan without capture/OCR."""
    console = Console()
    result = SerenaOCRPlanTool().execute(goal=goal, mode=mode, source=source)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("safety-policy")
def safety_policy() -> None:
    """Show OCR/live vision safety policy."""
    console = Console()
    result = SerenaOCRSafetyPolicyTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("inspect-image")
@click.option("--path", required=True, help="Image or PDF path.")
def inspect_image(path: str) -> None:
    """Inspect an image/PDF input for OCR suitability."""
    console = Console()
    result = SerenaOCRInspectImageTool().execute(path=path)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("readability")
@click.option("--path", required=True, help="Image path.")
def readability(path: str) -> None:
    """Assess image readability for OCR."""
    console = Console()
    result = SerenaOCRReadabilityTool().execute(path=path)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("extract-image")
@click.option("--path", required=True, help="Image path.")
def extract_image(path: str) -> None:
    """Extract visible text from an image."""
    console = Console()
    result = SerenaOCRExtractImageTool().execute(path=path)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("extract-pdf")
@click.option("--path", required=True, help="PDF path.")
@click.option("--max-pages", default=10, type=int, help="Maximum pages to process.")
def extract_pdf(path: str, max_pages: int) -> None:
    """Extract embedded text from a PDF."""
    console = Console()
    result = SerenaOCRExtractPDFTool().execute(path=path, max_pages=max_pages)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("cameras")
@click.option("--max-indexes", default=8, type=int, help="Maximum camera indexes to probe.")
def cameras(max_indexes: int) -> None:
    """List usable OCR/live vision cameras."""
    console = Console()
    result = SerenaOCRCamerasTool().execute(max_indexes=max_indexes)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("capture")
@click.option("--camera-index", default=0, type=int, help="Camera index.")
@click.option("--name", default="webcam-capture", help="Capture name.")
def capture(camera_index: int, name: str) -> None:
    """Capture one explicit webcam frame."""
    console = Console()
    result = SerenaOCRCaptureTool().execute(camera_index=camera_index, name=name)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("capture-doc")
@click.option("--camera-index", default=0, type=int, help="Camera index.")
@click.option("--name", default="webcam-document", help="Capture name.")
def capture_doc(camera_index: int, name: str) -> None:
    """Capture one webcam document frame and OCR it."""
    console = Console()
    result = SerenaOCRCaptureDocTool().execute(camera_index=camera_index, name=name)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("describe-capture")
@click.option("--path", required=True, help="Capture/image path.")
def describe_capture(path: str) -> None:
    """Describe a saved capture/image for OCR suitability."""
    console = Console()
    result = SerenaOCRDescribeCaptureTool().execute(path=path)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("live-start")
@click.option("--mode", default="assist", help="document, text, scene, object, assist.")
@click.option("--camera-index", default=0, type=int, help="Camera index.")
@click.option("--interval-seconds", default=5, type=int, help="Frame interval seconds.")
@click.option("--max-minutes", default=10, type=int, help="Maximum session duration.")
@click.option("--approved", is_flag=True, help="Required explicit approval to start live vision.")
def live_start(mode: str, camera_index: int, interval_seconds: int, max_minutes: int, approved: bool) -> None:
    """Start a controlled OCR/live vision session."""
    console = Console()
    result = SerenaOCRLiveStartTool().execute(
        mode=mode,
        camera_index=camera_index,
        interval_seconds=interval_seconds,
        max_minutes=max_minutes,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("live-status")
def live_status() -> None:
    """Show OCR/live vision session status."""
    console = Console()
    result = SerenaOCRLiveStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("live-stop")
@click.option("--reason", default="Stopped by explicit command.", help="Stop reason.")
def live_stop(reason: str) -> None:
    """Stop a controlled OCR/live vision session."""
    console = Console()
    result = SerenaOCRLiveStopTool().execute(reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("live-snapshot")
@click.option("--name", default="live-snapshot", help="Snapshot name.")
@click.option("--extract-text", is_flag=True, help="Also run OCR extraction on the snapshot.")
def live_snapshot(name: str, extract_text: bool) -> None:
    """Capture one frame during an active OCR/live vision session."""
    console = Console()
    result = SerenaOCRLiveSnapshotTool().execute(name=name, extract_text=extract_text)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("live-report")
def live_report() -> None:
    """Create a report for the current/recent OCR live vision session."""
    console = Console()
    result = SerenaOCRLiveReportTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("live-watch-doc")
@click.option("--frames", default=1, type=int, help="Frames to capture, capped at 5.")
@click.option("--name", default="live-watch-doc", help="Capture name prefix.")
def live_watch_doc(frames: int, name: str) -> None:
    """Capture document frames during an active live vision session."""
    console = Console()
    result = SerenaOCRLiveWatchDocTool().execute(frames=frames, name=name)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("live-watch-text")
@click.option("--frames", default=1, type=int, help="Frames to capture, capped at 5.")
@click.option("--name", default="live-watch-text", help="Capture name prefix.")
def live_watch_text(frames: int, name: str) -> None:
    """Capture text frames during an active live vision session."""
    console = Console()
    result = SerenaOCRLiveWatchTextTool().execute(frames=frames, name=name)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("best-frame")
def best_frame() -> None:
    """Select the best readable frame from the live vision session."""
    console = Console()
    result = SerenaOCRBestFrameTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("extract-live-text")
def extract_live_text() -> None:
    """Extract text from the best live frame."""
    console = Console()
    result = SerenaOCRExtractLiveTextTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("to-google-doc")
@click.option("--text-path", default="", help="OCR extracted text path. Defaults to latest extracted text.")
@click.option("--title", default="OCR Extracted Document", help="Google Doc title.")
@click.option("--drive-folder", default="Serena/OCR Documents", help="Google Drive folder path.")
@click.option("--doc-type", default="report", help="document, note, or report.")
def to_google_doc(text_path: str, title: str, drive_folder: str, doc_type: str) -> None:
    """Create a Google Doc from OCR extracted text."""
    console = Console()
    result = SerenaOCRToGoogleDocTool().execute(
        text_path=text_path,
        title=title,
        drive_folder=drive_folder,
        doc_type=doc_type,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("to-drive")
@click.option("--text-path", default="", help="OCR extracted text or handoff path. Defaults to latest extracted text.")
@click.option("--drive-folder", default="Serena/OCR Extracted Text", help="Google Drive folder path.")
@click.option("--name", default="", help="Optional Drive filename.")
def to_drive(text_path: str, drive_folder: str, name: str) -> None:
    """Upload OCR output to Google Drive."""
    console = Console()
    result = SerenaOCRToDriveTool().execute(
        text_path=text_path,
        drive_folder=drive_folder,
        name=name,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("to-document")
@click.option("--text-path", default="", help="OCR extracted text path. Defaults to latest extracted text.")
@click.option("--title", default="OCR Handoff Document", help="Local handoff document title.")
def to_document(text_path: str, title: str) -> None:
    """Create local structured OCR handoff document."""
    console = Console()
    result = SerenaOCRToDocumentTool().execute(
        text_path=text_path,
        title=title,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("document-flow")
@click.option("--text-path", default="", help="OCR extracted text path. Defaults to latest extracted text.")
@click.option("--title", default="OCR Document Flow", help="Document title.")
@click.option("--drive-folder", default="Serena/OCR Document Flow", help="Google Drive folder path.")
def document_flow(text_path: str, title: str, drive_folder: str) -> None:
    """Run OCR local handoff + Drive upload + Google Doc creation."""
    console = Console()
    result = SerenaOCRDocumentFlowTool().execute(
        text_path=text_path,
        title=title,
        drive_folder=drive_folder,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("artifacts")
@click.option("--limit", default=20, type=int, help="Maximum recent artifact files to show.")
def artifacts(limit: int) -> None:
    """List OCR artifacts."""
    console = Console()
    result = SerenaOCRArtifactsTool().execute(limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("audit")
def audit() -> None:
    """Audit OCR/live vision engines, state, artifacts, and safety."""
    console = Console()
    result = SerenaOCRAuditTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("blocked-hidden-watch")
@click.option("--reason", default="Hidden/background watch requested.", help="Reason for attempted hidden watch.")
def blocked_hidden_watch(reason: str) -> None:
    """Deliberately blocked hidden/background watch command."""
    console = Console()
    result = SerenaOCRBlockedHiddenWatchTool().execute(reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@ocr.command("blocked-delete")
@click.option("--path", default="", help="OCR artifact path.")
@click.option("--reason", default="Delete requested.", help="Reason for attempted delete.")
def blocked_delete(path: str, reason: str) -> None:
    """Deliberately blocked OCR artifact delete command."""
    console = Console()
    result = SerenaOCRBlockedDeleteTool().execute(path=path, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["ocr"]
