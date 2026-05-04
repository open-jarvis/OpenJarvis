
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


__all__ = ["ocr"]
