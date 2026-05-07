"""Serena CRM / Contacts / Customer Relationship Full Operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_crm import CRM_TOOL_CLASSES


@click.group()
def crm() -> None:
    """Native Serena CRM / Contacts / Customer Relationship operator tools."""


def _run(tool_id: str, **kwargs):
    console = Console()
    result = CRM_TOOL_CLASSES[tool_id]().execute(**kwargs)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@crm.command("status")
def status():
    """Show CRM operator status."""
    _run("serena_crm_status")


@crm.command("env-check")
def env_check():
    """Check CRM environment without exposing secrets."""
    _run("serena_crm_env_check")


@crm.command("source-list")
def source_list():
    """List CRM sources."""
    _run("serena_crm_source_list")


@crm.command("source-info")
@click.option("--source", required=True)
def source_info(source):
    """Show CRM source details."""
    _run("serena_crm_source_info", source=source)


@crm.command("plan")
@click.option("--goal", required=True)
@click.option("--source-scope", default="membership,ecommerce,bookings,wordpress,accounting,reporting")
def plan(goal, source_scope):
    """Create a CRM operation plan."""
    _run("serena_crm_plan", goal=goal, source_scope=source_scope)


@crm.command("contact-profile")
@click.option("--contact-name", required=True)
@click.option("--notes", default="")
@click.option("--approved", is_flag=True)
def contact_profile(contact_name, notes, approved):
    """Create a local contact profile draft."""
    _run("serena_crm_contact_profile", contact_name=contact_name, notes=notes, approved=approved)


@crm.command("contact-list")
@click.option("--root", default="outputs/crm")
@click.option("--limit", default=100, type=int)
def contact_list(root, limit):
    """List local contact artifacts."""
    _run("serena_crm_contact_list", root=root, limit=limit)


@crm.command("contact-info")
@click.option("--reference", required=True)
def contact_info(reference):
    """Create/read local contact info summary."""
    _run("serena_crm_contact_info", reference=reference)


@crm.command("contact-summary")
@click.option("--root", default="outputs")
@click.option("--limit", default=100, type=int)
def contact_summary(root, limit):
    """Create local contact/customer summary."""
    _run("serena_crm_contact_summary", root=root, limit=limit)


@crm.command("lead-capture")
@click.option("--lead-name", required=True)
@click.option("--source", default="manual")
@click.option("--notes", default="")
def lead_capture(lead_name, source, notes):
    """Create local lead capture record."""
    _run("serena_crm_lead_capture", lead_name=lead_name, source=source, notes=notes)


@crm.command("lead-qualification-plan")
@click.option("--lead-name", required=True)
@click.option("--source", default="manual")
@click.option("--approved", is_flag=True)
@click.option("--include-sensitive", is_flag=True)
def lead_qualification_plan(lead_name, source, approved, include_sensitive):
    """Create local lead qualification plan."""
    _run("serena_crm_lead_qualification_plan", lead_name=lead_name, source=source, approved=approved, include_sensitive=include_sensitive)


@crm.command("follow-up-plan")
@click.option("--contact-name", required=True)
@click.option("--reason", default="follow-up")
@click.option("--approved", is_flag=True)
@click.option("--include-sensitive", is_flag=True)
def follow_up_plan(contact_name, reason, approved, include_sensitive):
    """Create local follow-up plan."""
    _run("serena_crm_follow_up_plan", contact_name=contact_name, reason=reason, approved=approved, include_sensitive=include_sensitive)


@crm.command("relationship-summary")
@click.option("--reference", required=True)
@click.option("--notes", default="")
@click.option("--include-sensitive", is_flag=True)
def relationship_summary(reference, notes, include_sensitive):
    """Create local relationship summary."""
    _run("serena_crm_relationship_summary", reference=reference, notes=notes, include_sensitive=include_sensitive)


@crm.command("customer-lifecycle-plan")
@click.option("--programme", default="customer lifecycle")
@click.option("--focus", default="lead,prospect,customer,member,retention")
@click.option("--approved", is_flag=True)
@click.option("--include-sensitive", is_flag=True)
def customer_lifecycle_plan(programme, focus, approved, include_sensitive):
    """Create customer lifecycle plan."""
    _run("serena_crm_customer_lifecycle_plan", programme=programme, focus=focus, approved=approved, include_sensitive=include_sensitive)


def _handoff_command(tool_id: str):
    @click.option("--reference", default="")
    @click.option("--notes", default="")
    def command(reference, notes):
        _run(tool_id, reference=reference or tool_id, notes=notes)
    return command


crm.command("membership-handoff")(_handoff_command("serena_crm_membership_handoff"))
crm.command("ecommerce-handoff")(_handoff_command("serena_crm_ecommerce_handoff"))
crm.command("bookings-handoff")(_handoff_command("serena_crm_bookings_handoff"))
crm.command("wordpress-handoff")(_handoff_command("serena_crm_wordpress_handoff"))
crm.command("accounting-handoff")(_handoff_command("serena_crm_accounting_handoff"))
crm.command("reporting-handoff")(_handoff_command("serena_crm_reporting_handoff"))


@crm.command("audit")
@click.option("--root", default="outputs/crm")
@click.option("--limit", default=200, type=int)
def audit(root, limit):
    """Audit local CRM artifacts."""
    _run("serena_crm_audit", root=root, limit=limit)


@crm.command("blocked-bulk-contact-export")
@click.option("--reference", default="bulk-contact-export")
@click.option("--reason", default="Bulk contact export is blocked without explicit approval and redaction.")
def blocked_bulk_contact_export(reference, reason):
    """Record blocked bulk contact export."""
    _run("serena_crm_blocked_bulk_contact_export", reference=reference, reason=reason)


@crm.command("blocked-patient-data-exposure")
@click.option("--reference", default="patient-data-exposure")
@click.option("--reason", default="Sensitive patient/contact data exposure is blocked.")
def blocked_patient_data_exposure(reference, reason):
    """Record blocked patient/contact data exposure."""
    _run("serena_crm_blocked_patient_data_exposure", reference=reference, reason=reason)


@crm.command("blocked-silent-contact-change")
@click.option("--reference", default="silent-contact-change")
@click.option("--reason", default="Silent contact/customer changes are blocked without explicit approval.")
def blocked_silent_contact_change(reference, reason):
    """Record blocked silent contact change."""
    _run("serena_crm_blocked_silent_contact_change", reference=reference, reason=reason)


@crm.command("blocked-unapproved-message-send")
@click.option("--reference", default="unapproved-message-send")
@click.option("--reason", default="Outbound message/campaign send is blocked without explicit approval.")
def blocked_unapproved_message_send(reference, reason):
    """Record blocked unapproved message send."""
    _run("serena_crm_blocked_unapproved_message_send", reference=reference, reason=reason)


@crm.command("blocked-unapproved-crm-write")
@click.option("--action", required=True)
@click.option("--reference", default="")
@click.option("--reason", default="CRM/Hub/contact write is blocked without explicit approval.")
def blocked_unapproved_crm_write(action, reference, reason):
    """Record blocked unapproved CRM write."""
    _run("serena_crm_blocked_unapproved_crm_write", action=action, reference=reference or action, reason=reason)
