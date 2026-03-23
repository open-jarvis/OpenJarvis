"""``jarvis registry`` — registry inspection commands."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table


def _load_registry_map() -> tuple[dict[str, object], dict[str, object]]:
    """Import all registries and return (by_name, aliases) lookup dicts."""
    from openjarvis.core.registry import (
        AgentRegistry,
        BenchmarkRegistry,
        ChannelRegistry,
        CompressionRegistry,
        EngineRegistry,
        LearningRegistry,
        MemoryRegistry,
        ModelRegistry,
        RouterPolicyRegistry,
        SkillRegistry,
        SpeechRegistry,
        ToolRegistry,
    )

    by_name = {
        "ToolRegistry": ToolRegistry,
        "AgentRegistry": AgentRegistry,
        "EngineRegistry": EngineRegistry,
        "MemoryRegistry": MemoryRegistry,
        "ModelRegistry": ModelRegistry,
        "ChannelRegistry": ChannelRegistry,
        "LearningRegistry": LearningRegistry,
        "SkillRegistry": SkillRegistry,
        "BenchmarkRegistry": BenchmarkRegistry,
        "RouterPolicyRegistry": RouterPolicyRegistry,
        "SpeechRegistry": SpeechRegistry,
        "CompressionRegistry": CompressionRegistry,
    }

    aliases: dict[str, object] = {}
    _alias_map = {
        "ToolRegistry": ("tool", "tools"),
        "AgentRegistry": ("agent", "agents"),
        "EngineRegistry": ("engine", "engines"),
        "MemoryRegistry": ("memory", "memories"),
        "ModelRegistry": ("model", "models"),
        "ChannelRegistry": ("channel", "channels"),
        "LearningRegistry": ("learning", "learnings"),
        "SkillRegistry": ("skill", "skills"),
        "BenchmarkRegistry": ("benchmark", "benchmarks"),
        "RouterPolicyRegistry": ("router", "routers"),
        "SpeechRegistry": ("speech", "speeches"),
        "CompressionRegistry": ("compression", "compressions"),
    }
    for class_name, cls in by_name.items():
        aliases[class_name] = cls
        for alias in _alias_map[class_name]:
            aliases[alias] = cls

    return by_name, aliases


@click.group()
def registry() -> None:
    """Inspect registered components — list registries, show entries."""


@registry.command("list")
def list_registries() -> None:
    """List all available registries."""
    console = Console(stderr=True)

    table = Table(title="Available Registries")
    table.add_column("Registry", style="cyan")
    table.add_column("Module", style="green")
    table.add_column("Entry Count", style="yellow")

    try:
        by_name, _ = _load_registry_map()
    except Exception as exc:
        console.print(f"[red]Error loading registries: {exc}[/red]")
        return

    module_path = "openjarvis.core.registry"
    for reg_name, registry_cls in by_name.items():
        try:
            count = len(registry_cls.keys())
            table.add_row(reg_name, module_path, str(count))
        except Exception as exc:
            table.add_row(reg_name, module_path, f"[red]Error: {exc}[/red]")

    console.print(table)


@registry.command()
@click.argument("registry_name")
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Show full entry details"
)
def show(registry_name: str, verbose: bool) -> None:
    """Show entries in a specific registry."""
    console = Console(stderr=True)

    try:
        _, aliases = _load_registry_map()

        registry_cls = aliases.get(registry_name)
        if registry_cls is None:
            console.print(f"[red]Unknown registry: {registry_name}[/red]")
            console.print(
                "[dim]Run 'jarvis registry list' to see available registries.[/dim]"
            )
            return

        keys = registry_cls.keys()
        if not keys:
            console.print(f"[dim]{registry_name} is empty.[/dim]")
            return

        console.print(f"[bold]{registry_name}[/bold] — {len(keys)} entry/entries")

        if verbose:
            for key in keys:
                entry = registry_cls.get(key)
                console.print(f"\n  [cyan]{key}[/cyan]")
                console.print(f"    Type: {type(entry).__name__}")
                console.print(f"    Value: {entry}")
        else:
            table = Table()
            table.add_column("Key", style="cyan")
            table.add_column("Type", style="green")
            table.add_column("Value", style="white", max_width=80)
            for key in keys:
                entry = registry_cls.get(key)
                entry_type = type(entry).__name__
                entry_value = str(entry)
                table.add_row(key, entry_type, entry_value)
            console.print(table)

    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


__all__ = ["registry"]
