
"""Serena Compliance / Policy Guard operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_compliance import (
    SerenaCompliancePlanTool,
    SerenaCompliancePolicyInfoTool,
    SerenaCompliancePolicyListTool,
    SerenaComplianceSourceListTool,
    SerenaComplianceStatusTool,
    SerenaComplianceDocumentCheckTool,
    SerenaComplianceMarketingCheckTool,
    SerenaCompliancePatientDataCheckTool,
    SerenaComplianceHpcsaCheckTool,
    SerenaCompliancePopiaCheckTool,
    SerenaComplianceFullCheckTool,
    SerenaComplianceQuickCheckTool,
)


@click.group()
def compliance() -> None:
    """Native Serena Compliance / Policy Guard operator tools."""


@compliance.command("status")
def status() -> None:
    """Show Compliance operator status."""
    console = Console()
    result = SerenaComplianceStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("policy-list")
def policy_list() -> None:
    """List local compliance policies."""
    console = Console()
    result = SerenaCompliancePolicyListTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("policy-info")
@click.option("--policy", required=True, help="Policy ID/name, e.g. popia.")
@click.option("--preview-chars", default=3000, type=int, help="Preview length.")
def policy_info(policy: str, preview_chars: int) -> None:
    """Read a local compliance policy summary."""
    console = Console()
    result = SerenaCompliancePolicyInfoTool().execute(policy=policy, preview_chars=preview_chars)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("source-list")
def source_list() -> None:
    """List compliance source registry entries."""
    console = Console()
    result = SerenaComplianceSourceListTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("plan")
@click.option("--goal", required=True, help="Compliance goal.")
@click.option("--operation", default="compliance-check", help="Operation type.")
@click.option("--context", default="", help="Context for the compliance plan.")
def plan(goal: str, operation: str, context: str) -> None:
    """Create a compliance operation plan."""
    console = Console()
    result = SerenaCompliancePlanTool().execute(goal=goal, operation=operation, context=context)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("quick-check")
@click.option("--text", required=True, help="Text/action/content to check.")
@click.option("--context", default="", help="Compliance context.")
def quick_check(text: str, context: str) -> None:
    """Run a quick compliance check."""
    console = Console()
    result = SerenaComplianceQuickCheckTool().execute(text=text, context=context)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("full-check")
@click.option("--text", required=True, help="Text/action/content to check.")
@click.option("--context", default="", help="Compliance context.")
def full_check(text: str, context: str) -> None:
    """Run a full compliance check."""
    console = Console()
    result = SerenaComplianceFullCheckTool().execute(text=text, context=context)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("popia-check")
@click.option("--text", required=True, help="Text/action/content to check.")
@click.option("--context", default="", help="Compliance context.")
def popia_check(text: str, context: str) -> None:
    """Run a POPIA/privacy compliance check."""
    console = Console()
    result = SerenaCompliancePopiaCheckTool().execute(text=text, context=context)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("hpcsa-check")
@click.option("--text", required=True, help="Text/action/content to check.")
@click.option("--context", default="", help="Compliance context.")
def hpcsa_check(text: str, context: str) -> None:
    """Run an HPCSA/clinical/marketing compliance check."""
    console = Console()
    result = SerenaComplianceHpcsaCheckTool().execute(text=text, context=context)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("patient-data-check")
@click.option("--text", required=True, help="Text/action/content to check.")
@click.option("--context", default="", help="Compliance context.")
def patient_data_check(text: str, context: str) -> None:
    """Check patient/client/health data risk."""
    console = Console()
    result = SerenaCompliancePatientDataCheckTool().execute(text=text, context=context)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("marketing-check")
@click.option("--text", required=True, help="Marketing/social/content text to check.")
@click.option("--context", default="", help="Compliance context.")
def marketing_check(text: str, context: str) -> None:
    """Check marketing content risk."""
    console = Console()
    result = SerenaComplianceMarketingCheckTool().execute(text=text, context=context)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("document-check")
@click.option("--text", required=True, help="Document text to check.")
@click.option("--context", default="", help="Compliance context.")
def document_check(text: str, context: str) -> None:
    """Check document text risk."""
    console = Console()
    result = SerenaComplianceDocumentCheckTool().execute(text=text, context=context)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["compliance"]
