"""``jarvis operators`` — operator lifecycle management commands."""

from __future__ import annotations

import shutil
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table


def _builtin_operators_dir() -> Path:
    """Return the path to built-in operator manifests shipped with the package."""
    return Path(__file__).resolve().parents[1] / "operators" / "data"


@click.group()
def operators() -> None:
    """Manage operators — persistent, scheduled autonomous agents."""


@operators.command("list")
def list_operators() -> None:
    """List all discovered operators and their status."""
    console = Console(stderr=True)
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR, load_config
        from openjarvis.operators.loader import load_operator

        config = load_config()
        manifests_dir = (
            Path(config.operators.manifests_dir).expanduser()
            if hasattr(config, "operators")
            else (DEFAULT_CONFIG_DIR / "operators")
        )

        # Also check project-local operators/ directory
        project_dirs = [manifests_dir]
        local_ops = _builtin_operators_dir()
        if local_ops.is_dir():
            project_dirs.append(local_ops)

        found = []
        for d in project_dirs:
            if not d.is_dir():
                continue
            for toml_path in sorted(d.glob("*.toml")):
                try:
                    m = load_operator(toml_path)
                    found.append(m)
                except Exception:
                    pass

        if not found:
            console.print("[dim]No operators discovered.[/dim]")
            console.print(
                f"[dim]Place TOML manifests in {manifests_dir} or ./operators/[/dim]"
            )
            return

        table = Table(title="Operators")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Schedule", style="yellow")
        table.add_column("Tools", style="magenta")
        table.add_column("Version", style="dim")

        for m in found:
            sched = f"{m.schedule_type}:{m.schedule_value}"
            tools = ", ".join(m.tools[:3])
            if len(m.tools) > 3:
                tools += f" (+{len(m.tools) - 3})"
            table.add_row(m.id, m.name, sched, tools, m.version)

        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@operators.command()
@click.argument("operator_id")
def info(operator_id: str) -> None:
    """Show detailed info about an operator."""
    console = Console(stderr=True)
    try:
        manifest = _find_manifest(operator_id)
        if manifest is None:
            console.print(f"[red]Operator not found: {operator_id}[/red]")
            return

        console.print(f"[bold cyan]{manifest.name}[/bold cyan] ({manifest.id})")
        console.print(f"  Version: {manifest.version}")
        console.print(f"  Author: {manifest.author or 'unknown'}")
        console.print(f"  Description: {manifest.description}")
        sched = f"{manifest.schedule_type} = {manifest.schedule_value}"
        console.print(f"  Schedule: {sched}")
        console.print(f"  Tools: {', '.join(manifest.tools) or 'none'}")
        console.print(f"  Max turns: {manifest.max_turns}")
        console.print(f"  Temperature: {manifest.temperature}")
        if manifest.metrics:
            console.print(f"  Metrics: {', '.join(manifest.metrics)}")
        if manifest.system_prompt:
            preview = manifest.system_prompt[:200].replace("\n", " ")
            console.print(f"  System prompt: {preview}...")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@operators.command()
@click.argument("operator_id")
def activate(operator_id: str) -> None:
    """Activate an operator (creates a scheduler task)."""
    console = Console(stderr=True)
    try:
        system, manager = _build_system_with_operators()
        task_id = manager.activate(operator_id)
        msg = f"Activated operator {operator_id} (task: {task_id})"
        console.print(f"[green]{msg}[/green]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@operators.command()
@click.argument("operator_id")
def deactivate(operator_id: str) -> None:
    """Deactivate an operator (cancels its scheduler task)."""
    console = Console(stderr=True)
    try:
        system, manager = _build_system_with_operators()
        manager.deactivate(operator_id)
        console.print(f"[yellow]Deactivated operator {operator_id}[/yellow]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@operators.command()
@click.argument("operator_id")
def pause(operator_id: str) -> None:
    """Pause an active operator."""
    console = Console(stderr=True)
    try:
        system, manager = _build_system_with_operators()
        manager.pause(operator_id)
        console.print(f"[yellow]Paused operator {operator_id}[/yellow]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@operators.command()
@click.argument("operator_id")
def resume(operator_id: str) -> None:
    """Resume a paused operator."""
    console = Console(stderr=True)
    try:
        system, manager = _build_system_with_operators()
        manager.resume(operator_id)
        console.print(f"[green]Resumed operator {operator_id}[/green]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@operators.command("run")
@click.argument("operator_id")
def run_once(operator_id: str) -> None:
    """Execute a single tick of an operator immediately (for testing)."""
    console = Console(stderr=True)
    try:
        system, manager = _build_system_with_operators()
        console.print(f"[dim]Running operator {operator_id}...[/dim]")
        result = manager.run_once(operator_id)
        console.print(f"\n[bold]Result:[/bold]\n{result}")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@operators.command()
@click.argument("operator_id")
@click.option("-n", "--lines", default=10, help="Number of log entries to show.")
def logs(operator_id: str, lines: int) -> None:
    """Show execution logs for an operator."""
    console = Console(stderr=True)
    try:
        from openjarvis.core.config import load_config
        from openjarvis.scheduler.store import SchedulerStore

        config = load_config()
        db_path = config.scheduler.db_path
        if not db_path:
            from openjarvis.core.config import DEFAULT_CONFIG_DIR

            db_path = str(DEFAULT_CONFIG_DIR / "scheduler.db")

        store = SchedulerStore(db_path=db_path)
        task_id = f"operator:{operator_id}"
        runs = store.get_runs(task_id, limit=lines)

        if not runs:
            console.print(f"[dim]No logs found for operator {operator_id}[/dim]")
            return

        table = Table(title=f"Logs for {operator_id}")
        table.add_column("Started", style="dim")
        table.add_column("Finished", style="dim")
        table.add_column("Success", style="green")
        table.add_column("Result", style="cyan", max_width=60)

        for run in runs:
            success = "[green]yes[/green]" if run.get("success") else "[red]no[/red]"
            result_text = run.get("result", "")[:60]
            table.add_row(
                run.get("started_at", ""),
                run.get("finished_at", ""),
                success,
                result_text,
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@operators.command()
@click.argument("path")
def install(path: str) -> None:
    """Install an operator TOML manifest to the manifests directory."""
    console = Console(stderr=True)
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR

        src = Path(path)
        if not src.exists():
            console.print(f"[red]File not found: {path}[/red]")
            return

        dest_dir = DEFAULT_CONFIG_DIR / "operators"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        console.print(f"[green]Installed operator to {dest}[/green]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


# -- Helpers -----------------------------------------------------------------


def _find_manifest(operator_id: str):
    """Find an operator manifest by ID across known directories."""
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.operators.loader import load_operator

    dirs = [DEFAULT_CONFIG_DIR / "operators", _builtin_operators_dir()]
    for d in dirs:
        if not d.is_dir():
            continue
        for toml_path in d.glob("*.toml"):
            try:
                m = load_operator(toml_path)
                if m.id == operator_id:
                    return m
            except Exception:
                pass
    return None


def _build_system_with_operators():
    """Build a JarvisSystem with operators wired up."""
    from openjarvis.operators.manager import OperatorManager
    from openjarvis.system import SystemBuilder

    system = SystemBuilder().scheduler(True).sessions(True).build()

    manager = OperatorManager(system)
    system.operator_manager = manager

    # Discover from known directories
    from openjarvis.core.config import DEFAULT_CONFIG_DIR

    for d in [DEFAULT_CONFIG_DIR / "operators", _builtin_operators_dir()]:
        if d.is_dir():
            manager.discover(d)

    return system, manager


__all__ = ["operators"]
