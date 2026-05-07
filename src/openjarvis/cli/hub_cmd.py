"""Serena Hub / Command Center Full Operator CLI.

Hub v1 is local-first and read-only for external/live systems.
It indexes local artifacts, creates local rollups/state, records blocked
actions, and generates a static local web command center.
"""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_hub import (
    hub_action_routing_plan,
    hub_approved_execution_gate,
    hub_approval_list,
    hub_approval_decision,
    hub_activity_event,
    hub_artifact_index,
    hub_orb_state,
    hub_open_web,
    hub_dashboard_sections,
    hub_artifact_summary,
    hub_blocked_unapproved_action,
    hub_chat_request,
    hub_live_tick,
    hub_command_intake,
    hub_crm_rollup,
    hub_document_rollup,
    hub_env_check,
    hub_finance_rollup,
    hub_operator_rollup,
    hub_safety_rollup,
    hub_schedule_rollup,
    hub_self_upgrade_plan,
    hub_secret_scan_status,
    hub_source_list,
    hub_status,
    hub_serve_web,
    hub_web_sync_data,
    hub_web_build,
    hub_widget_registry,
)


@click.group()
def hub() -> None:
    """Serena Hub / Command Center local-first operator tools."""


def _print(payload) -> None:
    console = Console()
    console.print_json(data=payload)


@hub.command("status")
def status():
    """Show Serena Hub local operator status."""
    _print(hub_status())


@hub.command("env-check")
def env_check():
    """Check local Hub readiness."""
    _print(hub_env_check())


@hub.command("source-list")
def source_list():
    """List known upstream local output sources."""
    _print(hub_source_list())


@hub.command("artifact-index")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def artifact_index(root, limit):
    """Index local artifacts for Hub consumption."""
    _print(hub_artifact_index(root=root, limit=limit))


@hub.command("operator-rollup")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def operator_rollup(root, limit):
    """Create local operator rollup."""
    _print(hub_operator_rollup(root=root, limit=limit))


@hub.command("crm-rollup")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def crm_rollup(root, limit):
    """Create CRM/contact/customer/member local rollup."""
    _print(hub_crm_rollup(root=root, limit=limit))


@hub.command("finance-rollup")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def finance_rollup(root, limit):
    """Create finance/accounting/revenue local rollup."""
    _print(hub_finance_rollup(root=root, limit=limit))


@hub.command("schedule-rollup")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def schedule_rollup(root, limit):
    """Create schedule/calendar/bookings local rollup."""
    _print(hub_schedule_rollup(root=root, limit=limit))


@hub.command("document-rollup")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def document_rollup(root, limit):
    """Create documents/files/Drive local rollup."""
    _print(hub_document_rollup(root=root, limit=limit))


@hub.command("safety-rollup")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def safety_rollup(root, limit):
    """Create safety/approval/blocked-action local rollup."""
    _print(hub_safety_rollup(root=root, limit=limit))


@hub.command("widget-registry")
def widget_registry():
    """Create local Hub widget registry."""
    _print(hub_widget_registry())


@hub.command("artifact-summary")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def artifact_summary(root, limit):
    """Create safer compact local artifact summary."""
    _print(hub_artifact_summary(root=root, limit=limit))


@hub.command("dashboard-sections")
def dashboard_sections():
    """Create local Hub dashboard section registry."""
    _print(hub_dashboard_sections())


@hub.command("orb-state")
@click.option("--state", "orb_state", required=True)
@click.option("--active-operator", default="hub")
@click.option("--active-task", default=None)
@click.option("--active-section", default="overview")
def orb_state(orb_state, active_operator, active_task, active_section):
    """Set local Hub orb state for visual/demo testing."""
    _print(
        hub_orb_state(
            orb_state=orb_state,
            active_operator=active_operator,
            active_task=active_task,
            active_section=active_section,
        )
    )


@hub.command("open")
def open_web():
    """Open local Serena Hub web shell."""
    _print(hub_open_web())


@hub.command("web-sync-data")
def web_sync_data():
    """Copy Hub JSON state/rollups into web/data for dynamic browser fetch."""
    _print(hub_web_sync_data())


@hub.command("serve")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8765, type=int)
@click.option("--no-build", is_flag=True)
def serve(host, port, no_build):
    """Serve local Serena Hub over HTTP for dynamic JSON loading."""
    _print(hub_serve_web(host=host, port=port, build=not no_build))


@hub.command("web-build")
def web_build():
    """Generate local static Serena Hub web shell."""
    _print(hub_web_build())


@hub.command("approval-list")
@click.option("--status", "approval_status", default="all")
def approval_list(approval_status):
    """List local Hub approvals."""
    _print(hub_approval_list(status=approval_status))


@hub.command("approval-decision")
@click.option("--approval-id", required=True)
@click.option("--decision", required=True)
@click.option("--reason", default="")
@click.option("--decided-by", default="Kyle")
def approval_decision(approval_id, decision, reason, decided_by):
    """Mark a local approval approved or denied. No execution occurs."""
    _print(
        hub_approval_decision(
            approval_id=approval_id,
            decision=decision,
            reason=reason,
            decided_by=decided_by,
        )
    )


@hub.command("approved-execution-gate")
@click.option("--approval-id", required=True)
@click.option("--file-list", required=True)
@click.option("--patch-plan", required=True)
@click.option("--smoke-test", required=True)
@click.option("--rollback-note", required=True)
def approved_execution_gate(approval_id, file_list, patch_plan, smoke_test, rollback_note):
    """Create a local execution gate record for an approved request. No execution occurs."""
    _print(
        hub_approved_execution_gate(
            approval_id=approval_id,
            file_list=file_list,
            patch_plan=patch_plan,
            smoke_test=smoke_test,
            rollback_note=rollback_note,
        )
    )


@hub.command("self-upgrade-plan")
@click.argument("request")
@click.option("--operator", default="hub")
@click.option("--target-area", default="unknown")
@click.option("--risk-level", default="review_required")
def self_upgrade_plan(request, operator, target_area, risk_level):
    """Create a local plan-only self-upgrade request pending approval."""
    _print(
        hub_self_upgrade_plan(
            request=request,
            operator=operator,
            target_area=target_area,
            risk_level=risk_level,
        )
    )


@hub.command("secret-scan-status")
def secret_scan_status():
    """Record Hub secret-scan policy gate status."""
    _print(hub_secret_scan_status())


@hub.command("command-intake")
@click.argument("command")
@click.option("--operator", default="hub")
@click.option("--target-section", default="overview")
@click.option("--priority", default="normal")
def command_intake(command, operator, target_section, priority):
    """Record a local Hub command intake item and update live dashboard state."""
    _print(
        hub_command_intake(
            command=command,
            operator=operator,
            target_section=target_section,
            priority=priority,
        )
    )


@hub.command("live-tick")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def live_tick(root, limit):
    """Refresh live Hub dashboard JSON mirrors."""
    _print(hub_live_tick(root=root, limit=limit))


@hub.command("chat-request")
@click.argument("message")
@click.option("--operator", default="hub")
def chat_request(message, operator):
    """Create local Hub chat request artifact only."""
    _print(hub_chat_request(message=message, operator=operator))


@hub.command("activity-event")
@click.option("--operator", required=True)
@click.option("--event-type", required=True)
@click.option("--message", required=True)
@click.option("--status", default="created")
@click.option("--artifact-path", default=None)
def activity_event(operator, event_type, message, status, artifact_path):
    """Record a local Hub activity event."""
    _print(
        hub_activity_event(
            operator=operator,
            event_type=event_type,
            message=message,
            status=status,
            artifact_path=artifact_path,
        )
    )


@hub.command("action-routing-plan")
@click.option("--scope", required=True)
@click.option("--include-sensitive", is_flag=True)
def action_routing_plan(scope, include_sensitive):
    """Create a local future routing plan. No live routing occurs."""
    _print(hub_action_routing_plan(scope=scope, include_sensitive=include_sensitive))


@hub.command("blocked-unapproved-action")
@click.option("--action", required=True)
@click.option("--operator", default="hub")
@click.option("--reason", default="Unapproved live action blocked by Hub v1.")
def blocked_unapproved_action(action, operator, reason):
    """Create local blocked-action record for unapproved live action."""
    _print(hub_blocked_unapproved_action(action=action, operator=operator, reason=reason))
