from pathlib import Path

ROOT = Path.cwd()

cli_path = ROOT / "src" / "openjarvis" / "cli" / "hub_cmd.py"
init_path = ROOT / "src" / "openjarvis" / "cli" / "__init__.py"

cli_code = '''"""Serena Hub / Command Center Full Operator CLI.

Hub v1 is local-first and read-only for external/live systems.
It indexes local artifacts, creates local rollups/state, records blocked
actions, and generates a static local web command center.
"""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_hub import (
    hub_action_routing_plan,
    hub_activity_event,
    hub_artifact_index,
    hub_blocked_unapproved_action,
    hub_chat_request,
    hub_crm_rollup,
    hub_document_rollup,
    hub_env_check,
    hub_finance_rollup,
    hub_operator_rollup,
    hub_safety_rollup,
    hub_schedule_rollup,
    hub_source_list,
    hub_status,
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


@hub.command("web-build")
def web_build():
    """Generate local static Serena Hub web shell."""
    _print(hub_web_build())


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
'''

cli_path.write_text(cli_code, encoding="utf-8")

text = init_path.read_text(encoding="utf-8")

if "from openjarvis.cli.hub_cmd import hub" not in text:
    marker = "from openjarvis.cli.crm_cmd import crm\\n"
    if marker not in text:
        raise SystemExit("[ERROR] Could not find CRM import marker in CLI __init__.py")
    text = text.replace(marker, marker + "from openjarvis.cli.hub_cmd import hub\\n")

if 'cli.add_command(hub, "hub")' not in text:
    marker = 'cli.add_command(crm, "crm")\\n'
    if marker not in text:
        raise SystemExit("[ERROR] Could not find CRM add_command marker in CLI __init__.py")
    text = text.replace(marker, marker + 'cli.add_command(hub, "hub")\\n')

# Remove previous safe import marker if it exists.
text = text.replace(
    '\\n# Serena Hub / Command Center CLI\\ntry:\\n    from openjarvis.cli import hub_cmd  # noqa: F401\\nexcept Exception:\\n    pass\\n',
    '\\n',
)

init_path.write_text(text, encoding="utf-8")

print("[OK] Rewrote hub_cmd.py as Click CLI")
print("[OK] Registered hub in src/openjarvis/cli/__init__.py")