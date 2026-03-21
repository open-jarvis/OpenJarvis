"""``jarvis tool`` — tool management commands."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table


@click.group()
def tool() -> None:
    """Manage tools — list, inspect."""


@tool.command("list")
def list_tools() -> None:
    """List all registered tools with their descriptions."""
    console = Console(stderr=True)
    try:
        # Trigger tool registration by importing the tools module
        import openjarvis.tools  # noqa: F401
        from openjarvis.core.registry import ToolRegistry

        keys = sorted(ToolRegistry.keys())
        if not keys:
            console.print("[dim]No tools registered.[/dim]")
            return

        table = Table(title="Registered Tools")
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="green", max_width=60)
        table.add_column("Category", style="yellow")

        for key in keys:
            tool_cls = ToolRegistry.get(key)
            description = ""
            category = ""

            # Try to get spec from the class or an instance
            try:
                # Some tools may require initialization, so try with default init
                tool_instance = tool_cls() if callable(tool_cls) else tool_cls
                if hasattr(tool_instance, "spec"):
                    spec = tool_instance.spec
                    description = getattr(spec, "description", "")[:60]
                    category = getattr(spec, "category", "")
            except Exception:
                # If instantiation fails, just show the key
                description = "N/A (instantiation error)"

            table.add_row(key, description, category)

        console.print(table)
        console.print(f"\n[dim]Total: {len(keys)} tool(s)[/dim]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@tool.command()
@click.argument("tool_name")
def inspect(tool_name: str) -> None:
    """Show detailed information about a specific tool."""
    console = Console(stderr=True)
    try:
        # Trigger tool registration by importing the tools module
        import openjarvis.tools  # noqa: F401
        from openjarvis.core.registry import ToolRegistry

        if not ToolRegistry.contains(tool_name):
            console.print(f"[red]Tool not found: {tool_name}[/red]")
            console.print("[dim]Run 'jarvis tool list' to see available tools.[/dim]")
            return

        tool_cls = ToolRegistry.get(tool_name)
        console.print(f"[bold]{tool_name}[/bold]")

        try:
            tool_instance = tool_cls() if callable(tool_cls) else tool_cls
            if hasattr(tool_instance, "spec"):
                spec = tool_instance.spec
                console.print(f"  [cyan]Name:[/cyan] {getattr(spec, 'name', 'N/A')}")
                console.print(
                    f"  [cyan]Description:[/cyan] {getattr(spec, 'description', 'N/A')}"
                )
                category = getattr(spec, "category", "N/A") or "none"
                console.print(f"  [cyan]Category:[/cyan] {category}")

                params = getattr(spec, "parameters", {})
                if params:
                    console.print("  [cyan]Parameters:[/cyan]")
                    if isinstance(params, dict) and "properties" in params:
                        for param_name, param_info in params["properties"].items():
                            param_type = param_info.get("type", "any")
                            param_desc = param_info.get("description", "")
                            console.print(
                                f"    • {param_name}: {param_type} — {param_desc}"
                            )
                    else:
                        console.print(f"    {params}")
        except Exception as e:
            console.print(f"[yellow]Note: Could not instantiate tool: {e}[/yellow]")

    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


__all__ = ["tool"]
