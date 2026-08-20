"""``jarvis profile`` — inspect and rebuild the user profile."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from openjarvis.core.config import load_config
from openjarvis.personalization.consolidator import (
    consolidate_from_config,
)
from openjarvis.personalization.profile import (
    DEFAULT_PROFILE_PATH,
    UserProfile,
)
from openjarvis.personalization.tool_affinity import ToolAffinityTracker


@click.group(help="Manage the user profile (USER.md) and tool preferences.")
def profile() -> None:
    """Profile management commands."""


@profile.command("show")
@click.option(
    "--path",
    "profile_path",
    default=str(DEFAULT_PROFILE_PATH),
    show_default=True,
    help="Path to USER.md.",
)
def show_cmd(profile_path: str) -> None:
    """Show the current USER.md contents."""
    console = Console()
    path = Path(profile_path).expanduser()
    if not path.exists():
        console.print(f"[yellow]Profile not found:[/yellow] {path}")
        console.print("Run [bold]jarvis profile rebuild[/bold] to create it.")
        return
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        console.print(f"[yellow]Profile is empty:[/yellow] {path}")
        return
    console.print(Markdown(text))


@profile.command("rebuild")
@click.option(
    "--path",
    "profile_path",
    default=str(DEFAULT_PROFILE_PATH),
    show_default=True,
    help="Output path.",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Update without an interactive confirmation.",
)
def rebuild_cmd(profile_path: str, yes: bool) -> None:
    """Merge durable facts from memory.db into USER.md."""
    console = Console()
    target = Path(profile_path).expanduser()
    if target.exists() and not yes:
        console.print(f"[yellow]This will update:[/yellow] {target}")
        if not click.confirm("Continue?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            return

    config = load_config()
    profile, stats = consolidate_from_config(config, output_path=target)
    if stats.scanned == 0:
        console.print(
            "[yellow]memory.db contains no profile facts. Use the "
            "[bold]memory_learn[/bold] tool first, then rebuild.[/yellow]"
        )
        return

    console.print(f"[green]Profile updated:[/green] {stats.profile_path}")

    table = Table(show_header=False, border_style="cyan")
    table.add_row("Scanned", str(stats.scanned))
    table.add_row("Accepted", str(stats.accepted))
    table.add_row("Duplicates skipped", str(stats.skipped_duplicate))
    table.add_row("Missing keys skipped", str(stats.skipped_no_key))
    table.add_row("Untrusted skipped", str(stats.skipped_untrusted))
    console.print(table)


@profile.command("edit")
@click.option(
    "--path",
    "profile_path",
    default=str(DEFAULT_PROFILE_PATH),
    show_default=True,
)
def edit_cmd(profile_path: str) -> None:
    """Open USER.md in $EDITOR."""
    console = Console()
    path = Path(profile_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        UserProfile().save(path)
    import os

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    try:
        subprocess.call([*shlex.split(editor), str(path)])
    except FileNotFoundError:
        console.print(f"[red]Editor not found:[/red] {editor}")
        sys.exit(1)


@profile.command("clear")
@click.option(
    "--path",
    "profile_path",
    default=str(DEFAULT_PROFILE_PATH),
    show_default=True,
)
@click.option("--yes", is_flag=True)
def clear_cmd(profile_path: str, yes: bool) -> None:
    """Clear USER.md while keeping the file."""
    console = Console()
    path = Path(profile_path).expanduser()
    if not path.exists():
        console.print("[dim]Profile does not exist; nothing to clear.[/dim]")
        return
    if not yes and not click.confirm(f"Clear {path}?", default=False):
        return
    UserProfile().save(path)
    console.print(f"[green]Profile cleared:[/green] {path}")


@profile.command("tools")
@click.option(
    "--recent-days",
    default=None,
    type=float,
    help="Only include records from the last N days.",
)
@click.option("--limit", default=10, show_default=True)
def tools_cmd(recent_days: float | None, limit: int) -> None:
    """Show the most frequently used tools."""
    console = Console()
    tracker = ToolAffinityTracker()
    top = tracker.top_tools(limit=limit, recent_days=recent_days)
    if not top:
        console.print("[dim]No tool usage has been recorded yet.[/dim]")
        return
    table = Table(
        title="Tool preferences",
        header_style="bold bright_white",
        border_style="bright_blue",
    )
    table.add_column("Tool", style="cyan")
    table.add_column("Uses", justify="right")
    table.add_column("Success rate", justify="right")
    for name, count, rate in top:
        table.add_row(name, str(count), f"{rate:.0%}")
    console.print(table)


__all__ = ["profile"]
