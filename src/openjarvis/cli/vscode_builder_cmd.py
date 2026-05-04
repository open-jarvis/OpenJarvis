
"""Serena VS Code Builder CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_vscode_builder import (
    SerenaVSCodeBuilderFinalCheckTool,
    SerenaVSCodeBuilderStatusTool,
    SerenaVSCodeBuilderTemplatesTool,
)


@click.group("vscode-builder")
def vscode_builder() -> None:
    """Native Serena VS Code Builder tools."""


@vscode_builder.command("status")
def status() -> None:
    """Show Serena VS Code Builder status."""
    console = Console()
    result = SerenaVSCodeBuilderStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode_builder.command("templates")
def templates() -> None:
    """List available builder templates."""
    console = Console()
    result = SerenaVSCodeBuilderTemplatesTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode_builder.command("final-check")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--module", default="openjarvis.tools.serena_vscode_builder", help="Module import to check.")
def final_check(root: str, module: str) -> None:
    """Run builder final local check."""
    console = Console()
    result = SerenaVSCodeBuilderFinalCheckTool().execute(root=root, module=module)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["vscode_builder"]
