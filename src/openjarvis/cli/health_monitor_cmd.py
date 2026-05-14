
"""Serena Health Monitor CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_health_monitor import (
    SerenaHealthMonitorFinalReportTool,
    SerenaHealthMonitorDeviceReportTool,
    SerenaHealthMonitorSoftwareTool,
    SerenaHealthMonitorHardwareTool,
    SerenaHealthMonitorGitTool,
    SerenaHealthMonitorOutputsTool,
    SerenaHealthMonitorProjectTool,
    SerenaHealthMonitorRegistryTool,
    SerenaHealthMonitorSkillsTool,
    SerenaHealthMonitorStatusTool,
    SerenaHealthMonitorSystemTool,
)


@click.group("health-monitor")
def health_monitor() -> None:
    """Native Serena local health monitor tools."""


@health_monitor.command("status")
def status() -> None:
    """Show Health Monitor status."""
    console = Console()
    result = SerenaHealthMonitorStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@health_monitor.command("system")
def system() -> None:
    """Inspect system health."""
    console = Console()
    result = SerenaHealthMonitorSystemTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@health_monitor.command("project")
def project() -> None:
    """Inspect Serena project health."""
    console = Console()
    result = SerenaHealthMonitorProjectTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@health_monitor.command("outputs")
def outputs() -> None:
    """Inspect Serena output folders."""
    console = Console()
    result = SerenaHealthMonitorOutputsTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@health_monitor.command("registry")
def registry() -> None:
    """Inspect conversion registry health."""
    console = Console()
    result = SerenaHealthMonitorRegistryTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@health_monitor.command("skills")
def skills() -> None:
    """Inspect skill docs and tool imports."""
    console = Console()
    result = SerenaHealthMonitorSkillsTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@health_monitor.command("git")
def git() -> None:
    """Inspect Git health."""
    console = Console()
    result = SerenaHealthMonitorGitTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@health_monitor.command("final-report")
def final_report() -> None:
    """Create a full Serena operator health report."""
    console = Console()
    result = SerenaHealthMonitorFinalReportTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@health_monitor.command("hardware")
def hardware() -> None:
    """Inspect PC hardware health."""
    console = Console()
    result = SerenaHealthMonitorHardwareTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@health_monitor.command("software")
def software() -> None:
    """Inspect software/developer tool health."""
    console = Console()
    result = SerenaHealthMonitorSoftwareTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@health_monitor.command("device-report")
def device_report() -> None:
    """Create combined PC/device and Serena health report."""
    console = Console()
    result = SerenaHealthMonitorDeviceReportTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["health_monitor"]
