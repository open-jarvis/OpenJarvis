"""``jarvis learning`` — distillation learning CLI subcommands.

See spec §12.
"""

from __future__ import annotations

import click
from rich.console import Console

console = Console()


@click.group("learning")
def learning_group() -> None:
    """Frontier-driven harness learning (distillation)."""


@learning_group.command("init")
def learning_init() -> None:
    """Initialize the distillation checkpoint repo and directory layout."""
    from openjarvis.learning.distillation.checkpoint.store import CheckpointStore
    from openjarvis.learning.distillation.storage.paths import (
        ensure_distillation_dirs,
        resolve_distillation_root,
    )

    root = resolve_distillation_root()
    ensure_distillation_dirs()
    home = root.parent  # ~/.openjarvis
    store = CheckpointStore(home)
    store.init()
    console.print(f"[green]Initialized distillation at {root}[/green]")


@learning_group.command("run")
@click.option(
    "--autonomy",
    type=click.Choice(["auto", "tiered", "manual"]),
    default="tiered",
)
def learning_run(autonomy: str) -> None:
    """Run an on-demand learning session."""
    console.print("[yellow]On-demand session started.[/yellow]")
    console.print("[dim]Use 'jarvis learning history' to check results.[/dim]")
    console.print(f"[dim]Autonomy mode: {autonomy}[/dim]")
    # Full wiring deferred to integration — this registers the CLI surface.
    console.print("[dim]Full orchestration requires configured teacher engine.[/dim]")


@learning_group.command("history")
@click.option("--limit", type=int, default=10, help="Max sessions to show.")
def learning_history(limit: int) -> None:
    """List past learning sessions."""
    console.print(f"[dim]Showing last {limit} sessions (requires learning.db).[/dim]")


@learning_group.command("show")
@click.argument("session_id")
def learning_show(session_id: str) -> None:
    """Show details of a learning session."""
    console.print(f"[dim]Session: {session_id}[/dim]")


@learning_group.command("review")
def learning_review() -> None:
    """Review pending edits awaiting approval."""
    console.print("[dim]Pending review queue.[/dim]")


@learning_group.command("approve")
@click.argument("edit_id")
def learning_approve(edit_id: str) -> None:
    """Approve a pending edit."""
    console.print(f"[dim]Approving edit: {edit_id}[/dim]")


@learning_group.command("reject")
@click.argument("edit_id")
@click.option("--reason", type=str, default="", help="Rejection reason.")
def learning_reject(edit_id: str, reason: str) -> None:
    """Reject a pending edit."""
    console.print(f"[dim]Rejecting edit: {edit_id}[/dim]")


@learning_group.command("rollback")
@click.argument("session_id", required=False)
@click.option("--last", is_flag=True, help="Rollback the most recent session.")
def learning_rollback(session_id: str | None, last: bool) -> None:
    """Rollback a learning session's commits."""
    target = session_id or ("last session" if last else "none")
    console.print(f"[dim]Rolling back: {target}[/dim]")


@learning_group.group("benchmark")
def benchmark_group() -> None:
    """Personal benchmark management."""


@benchmark_group.command("refresh")
def benchmark_refresh() -> None:
    """Manually refresh the personal benchmark."""
    console.print("[dim]Refreshing personal benchmark.[/dim]")


@benchmark_group.command("show")
def benchmark_show() -> None:
    """Show current benchmark statistics."""
    console.print("[dim]Benchmark stats.[/dim]")


@learning_group.group("daemon")
def daemon_group() -> None:
    """Background learning daemon."""


@daemon_group.command("start")
def daemon_start() -> None:
    """Start the learning daemon."""
    console.print("[dim]Starting daemon.[/dim]")


@daemon_group.command("stop")
def daemon_stop() -> None:
    """Stop the learning daemon."""
    console.print("[dim]Stopping daemon.[/dim]")


@daemon_group.command("status")
def daemon_status() -> None:
    """Check daemon status."""
    console.print("[dim]Daemon status.[/dim]")
