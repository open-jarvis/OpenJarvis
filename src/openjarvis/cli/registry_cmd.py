"""``jarvis registry`` — registry inspection commands."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

# All registry classes to expose via CLI
_REGISTRY_CLASSES = [
    ("ToolRegistry", "openjarvis.core.registry", "ToolRegistry"),
    ("AgentRegistry", "openjarvis.core.registry", "AgentRegistry"),
    ("EngineRegistry", "openjarvis.core.registry", "EngineRegistry"),
    ("MemoryRegistry", "openjarvis.core.registry", "MemoryRegistry"),
    ("ModelRegistry", "openjarvis.core.registry", "ModelRegistry"),
    ("ChannelRegistry", "openjarvis.core.registry", "ChannelRegistry"),
    ("LearningRegistry", "openjarvis.core.registry", "LearningRegistry"),
    ("SkillRegistry", "openjarvis.core.registry", "SkillRegistry"),
    ("BenchmarkRegistry", "openjarvis.core.registry", "BenchmarkRegistry"),
    ("RouterPolicyRegistry", "openjarvis.core.registry", "RouterPolicyRegistry"),
    ("SpeechRegistry", "openjarvis.core.registry", "SpeechRegistry"),
    ("CompressionRegistry", "openjarvis.core.registry", "CompressionRegistry"),
]


def _get_registry_class(name: str) -> object | None:
    """Dynamically import and return a registry class by name."""
    try:
        mod = __import__(name, fromlist=[""])
        return mod
    except (ImportError, AttributeError):
        return None


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

    for reg_name, module_path, class_name in _REGISTRY_CLASSES:
        try:
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

            registry_map = {
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

            registry_cls = registry_map.get(reg_name)
            if registry_cls:
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

        registry_map = {
            "tool": ToolRegistry,
            "tools": ToolRegistry,
            "ToolRegistry": ToolRegistry,
            "agent": AgentRegistry,
            "agents": AgentRegistry,
            "AgentRegistry": AgentRegistry,
            "engine": EngineRegistry,
            "engines": EngineRegistry,
            "EngineRegistry": EngineRegistry,
            "memory": MemoryRegistry,
            "memories": MemoryRegistry,
            "MemoryRegistry": MemoryRegistry,
            "model": ModelRegistry,
            "models": ModelRegistry,
            "ModelRegistry": ModelRegistry,
            "channel": ChannelRegistry,
            "channels": ChannelRegistry,
            "ChannelRegistry": ChannelRegistry,
            "learning": LearningRegistry,
            "learnings": LearningRegistry,
            "LearningRegistry": LearningRegistry,
            "skill": SkillRegistry,
            "skills": SkillRegistry,
            "SkillRegistry": SkillRegistry,
            "benchmark": BenchmarkRegistry,
            "benchmarks": BenchmarkRegistry,
            "BenchmarkRegistry": BenchmarkRegistry,
            "router": RouterPolicyRegistry,
            "routers": RouterPolicyRegistry,
            "RouterPolicyRegistry": RouterPolicyRegistry,
            "speech": SpeechRegistry,
            "speeches": SpeechRegistry,
            "SpeechRegistry": SpeechRegistry,
            "compression": CompressionRegistry,
            "compressions": CompressionRegistry,
            "CompressionRegistry": CompressionRegistry,
        }

        registry_cls = registry_map.get(registry_name)
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
