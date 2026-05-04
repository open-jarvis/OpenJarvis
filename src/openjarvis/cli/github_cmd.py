
"""Serena GitHub/Git operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_github import (
    SerenaGitHubBranchesTool,
    SerenaGitHubChangesTool,
    SerenaGitHubRecentCommitsTool,
    SerenaGitHubRemotesTool,
    SerenaGitHubRepoInfoTool,
    SerenaGitHubSafetyCheckTool,
    SerenaGitHubStatusTool,
)


@click.group()
def github() -> None:
    """Native Serena GitHub/Git operator tools."""


@github.command("status")
def status() -> None:
    """Show Serena GitHub operator status."""
    console = Console()
    result = SerenaGitHubStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("repo-info")
@click.option("--root", required=True, help="Approved root alias.")
def repo_info(root: str) -> None:
    """Inspect repository information."""
    console = Console()
    result = SerenaGitHubRepoInfoTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("branches")
@click.option("--root", required=True, help="Approved root alias.")
def branches(root: str) -> None:
    """List local and remote branches."""
    console = Console()
    result = SerenaGitHubBranchesTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("remotes")
@click.option("--root", required=True, help="Approved root alias.")
def remotes(root: str) -> None:
    """List Git remotes."""
    console = Console()
    result = SerenaGitHubRemotesTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("recent-commits")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--limit", default=10, type=int, help="Maximum commits to show.")
def recent_commits(root: str, limit: int) -> None:
    """Show recent commits."""
    console = Console()
    result = SerenaGitHubRecentCommitsTool().execute(root=root, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("changes")
@click.option("--root", required=True, help="Approved root alias.")
def changes(root: str) -> None:
    """Inspect local Git changes."""
    console = Console()
    result = SerenaGitHubChangesTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("safety-check")
@click.option("--root", required=True, help="Approved root alias.")
def safety_check(root: str) -> None:
    """Run Serena GitHub safety check."""
    console = Console()
    result = SerenaGitHubSafetyCheckTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["github"]
