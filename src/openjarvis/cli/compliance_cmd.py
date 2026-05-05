
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
    SerenaComplianceBlockedPolicyUpdateTool,
    SerenaCompliancePolicyDiffTool,
    SerenaComplianceRefreshPlanTool,
    SerenaComplianceUpdateCheckTool,
    SerenaComplianceCrmCheckTool,
    SerenaComplianceCalendarCheckTool,
    SerenaComplianceDocsCheckTool,
    SerenaComplianceDriveSharingCheckTool,
    SerenaComplianceOcrCheckTool,
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


@compliance.command("ocr-check")
@click.option("--text", required=True, help="OCR/capture text to check.")
@click.option("--context", default="", help="Workflow context.")
@click.option("--target", default="local report", help="Target handoff, e.g. Google Docs, Drive.")
def ocr_check(text: str, context: str, target: str) -> None:
    """Check OCR/camera/screen/video workflow risk."""
    console = Console()
    result = SerenaComplianceOcrCheckTool().execute(text=text, context=context, target=target)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("drive-sharing-check")
@click.option("--text", required=True, help="Content/file summary to check.")
@click.option("--context", default="", help="Workflow context.")
@click.option("--drive-action", default="upload/link", help="Drive action.")
def drive_sharing_check(text: str, context: str, drive_action: str) -> None:
    """Check Google Drive upload/link/share risk."""
    console = Console()
    result = SerenaComplianceDriveSharingCheckTool().execute(text=text, context=context, drive_action=drive_action)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("docs-check")
@click.option("--text", required=True, help="Document text to check.")
@click.option("--context", default="", help="Workflow context.")
@click.option("--doc-action", default="create/edit/export", help="Google Docs action.")
def docs_check(text: str, context: str, doc_action: str) -> None:
    """Check Google Docs workflow risk."""
    console = Console()
    result = SerenaComplianceDocsCheckTool().execute(text=text, context=context, doc_action=doc_action)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("calendar-check")
@click.option("--text", required=True, help="Calendar event text/details to check.")
@click.option("--context", default="", help="Workflow context.")
@click.option("--calendar-action", default="appointment/reminder/event", help="Calendar action.")
def calendar_check(text: str, context: str, calendar_action: str) -> None:
    """Check Calendar workflow risk."""
    console = Console()
    result = SerenaComplianceCalendarCheckTool().execute(text=text, context=context, calendar_action=calendar_action)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("crm-check")
@click.option("--text", required=True, help="CRM record/action text to check.")
@click.option("--context", default="", help="Workflow context.")
@click.option("--crm-action", default="create/update/search/export", help="CRM action.")
def crm_check(text: str, context: str, crm_action: str) -> None:
    """Check CRM/business record workflow risk."""
    console = Console()
    result = SerenaComplianceCrmCheckTool().execute(text=text, context=context, crm_action=crm_action)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("update-check")
def update_check() -> None:
    """Check policy update posture without changing rules."""
    console = Console()
    result = SerenaComplianceUpdateCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("refresh-plan")
@click.option("--policy", default="all", help="Policy to refresh, or all.")
@click.option("--reason", default="Routine policy refresh review.", help="Refresh reason.")
@click.option("--source-id", default="", help="Optional source registry ID.")
def refresh_plan(policy: str, reason: str, source_id: str) -> None:
    """Create policy refresh plan without changing active rules."""
    console = Console()
    result = SerenaComplianceRefreshPlanTool().execute(policy=policy, reason=reason, source_id=source_id)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("policy-diff")
@click.option("--policy", required=True, help="Policy ID/name.")
@click.option("--proposed-text", required=True, help="Proposed replacement text.")
def policy_diff(policy: str, proposed_text: str) -> None:
    """Compare local policy to proposed text without applying changes."""
    console = Console()
    result = SerenaCompliancePolicyDiffTool().execute(policy=policy, proposed_text=proposed_text)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@compliance.command("blocked-policy-update")
@click.option("--policy", default="unknown", help="Policy ID/name.")
@click.option("--reason", default="Silent policy update requested.", help="Reason.")
def blocked_policy_update(policy: str, reason: str) -> None:
    """Deliberately blocked silent policy update command."""
    console = Console()
    result = SerenaComplianceBlockedPolicyUpdateTool().execute(policy=policy, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["compliance"]
