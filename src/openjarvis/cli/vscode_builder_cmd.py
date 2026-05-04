
"""Serena VS Code Builder CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_vscode_builder import (
    SerenaVSCodeBuilderFinalCheckTool,
    SerenaVSCodeBuilderStatusTool,
    SerenaVSCodeBuilderTemplatesTool,
    SerenaVSCodeBuilderScaffoldTool,
    SerenaVSCodeBuilderPlanTool,
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


@vscode_builder.command("plan")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--name", required=True, help="Build name.")
@click.option("--goal", required=True, help="Build goal.")
@click.option("--kind", default="feature-scaffold", help="Build kind/template.")
@click.option("--target-path", default="", help="Relative target path.")
def plan(root: str, name: str, goal: str, kind: str, target_path: str) -> None:
    """Create a build plan without writing project files."""
    console = Console()
    result = SerenaVSCodeBuilderPlanTool().execute(
        root=root,
        name=name,
        goal=goal,
        kind=kind,
        target_path=target_path,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode_builder.command("scaffold")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--name", required=True, help="Feature name.")
@click.option("--target-path", required=True, help="Relative target folder.")
@click.option("--kind", default="python", help="Feature kind.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing files.")
def scaffold(root: str, name: str, target_path: str, kind: str, overwrite: bool) -> None:
    """Scaffold a feature folder with source, test, and docs."""
    console = Console()
    result = SerenaVSCodeBuilderScaffoldTool().execute(
        root=root,
        name=name,
        target_path=target_path,
        kind=kind,
        overwrite=overwrite,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["vscode_builder"]
