"""``jarvis profile`` -- manage your personal context profile.

Commands::

    jarvis profile show                              # display current profile
    jarvis profile import                            # interactive first-run wizard
    jarvis profile edit                              # open in $EDITOR / notepad
    jarvis profile set <field> <value>               # set an Identity field
    jarvis profile contact add "Alice" --role boss   # add / update a contact
    jarvis profile contact remove "Alice"            # remove a contact
    jarvis profile contact list                      # list all contacts
    jarvis profile project add "OpenJarvis" --status active --desc "..."
    jarvis profile project update "OpenJarvis" --status completed
    jarvis profile project list
    jarvis profile prefer "always schedule after 10am"  # add a preference
    jarvis profile note "add a free-form note"
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()


def _get_store():
    """Return a ProfileStore pointed at the configured USER.md."""
    from openjarvis.core.config import load_config
    from openjarvis.profile.store import ProfileStore

    try:
        config = load_config()
        path = config.memory_files.user_path
    except Exception:
        path = "~/.openjarvis/USER.md"

    return ProfileStore(path)


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


@click.group("profile")
def profile() -> None:
    """Manage your personal context profile (USER.md)."""


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@profile.command("show")
def show() -> None:
    """Display your current profile."""
    store = _get_store()
    text = store.render_full()
    if not text.strip():
        console.print(
            "[dim]Profile is empty. Run [bold]jarvis profile import[/bold] to fill it in.[/dim]"
        )
        return
    console.print(Panel(Markdown(text), title="Your Profile", border_style="cyan"))


# ---------------------------------------------------------------------------
# import (interactive wizard)
# ---------------------------------------------------------------------------


@profile.command("import")
def import_wizard() -> None:
    """Interactive wizard to populate your profile from scratch."""
    store = _get_store()
    store.ensure_template()

    console.print()
    console.print(Panel(
        "[bold cyan]Welcome to Jarvis.[/bold cyan]\n"
        "I'll learn a little about you so I can serve you better.\n"
        "[dim]Press Enter to skip any field.[/dim]",
        border_style="blue",
    ))
    console.print()

    # Identity fields
    name = click.prompt("  Your full name", default="", show_default=False).strip()
    if name:
        store.set_field("Identity", "Name", name)

    honorific = click.prompt(
        "  How should I address you? (e.g. sir / ma'am / by first name)",
        default="",
        show_default=False,
    ).strip()
    if honorific:
        store.set_field("Identity", "Preferred address", honorific)
        # Also update SOUL.md honorific reference if it exists
        _patch_soul_honorific(honorific)

    timezone = click.prompt(
        "  Your timezone (e.g. Asia/Kolkata, America/New_York)",
        default="",
        show_default=False,
    ).strip()
    if timezone:
        store.set_field("Identity", "Timezone", timezone)

    role = click.prompt(
        "  Your role or occupation (e.g. Software Engineer, Student)",
        default="",
        show_default=False,
    ).strip()
    if role:
        store.set_field("Identity", "Role", role)

    console.print()

    # Optional: a quick preference
    pref = click.prompt(
        "  Any communication preference Jarvis should know? (press Enter to skip)",
        default="",
        show_default=False,
    ).strip()
    if pref:
        store.add_item("Preferences", pref)

    # Optional: an active project
    project = click.prompt(
        "  What is one active project you're working on? (press Enter to skip)",
        default="",
        show_default=False,
    ).strip()
    if project:
        store.add_item("Active Projects", f"{project} [active]")

    console.print()
    console.print(f"[green]Profile saved to {store.path}[/green]")
    console.print(
        "[dim]Update anytime with [bold]jarvis profile set[/bold], "
        "[bold]jarvis profile contact add[/bold], etc.[/dim]"
    )
    console.print()
    console.print(Panel(Markdown(store.render_full()), title="Your Profile", border_style="cyan"))


def _patch_soul_honorific(honorific: str) -> None:
    """Update the honorific placeholder in SOUL.md if present."""
    from openjarvis.core.config import load_config

    try:
        config = load_config()
        soul_path = Path(config.memory_files.soul_path).expanduser()
    except Exception:
        soul_path = Path("~/.openjarvis/SOUL.md").expanduser()

    if not soul_path.exists():
        return

    text = soul_path.read_text(encoding="utf-8")
    if "{honorific}" in text:
        soul_path.write_text(text.replace("{honorific}", honorific), encoding="utf-8")


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------


@profile.command("set")
@click.argument("field")
@click.argument("value")
def profile_set(field: str, value: str) -> None:
    """Set an Identity field. Example: jarvis profile set timezone Asia/Kolkata"""
    store = _get_store()
    store.ensure_template()
    store.set_field("Identity", field.replace("-", " ").title(), value)
    console.print(f"[green]Set Identity.{field} = {value}[/green]")


# ---------------------------------------------------------------------------
# prefer
# ---------------------------------------------------------------------------


@profile.command("prefer")
@click.argument("rule")
def prefer(rule: str) -> None:
    """Add a preference rule. Example: jarvis profile prefer \"never send email without confirmation\""""
    store = _get_store()
    store.ensure_template()
    store.add_item("Preferences", rule)
    console.print(f"[green]Preference added:[/green] {rule}")


# ---------------------------------------------------------------------------
# note
# ---------------------------------------------------------------------------


@profile.command("note")
@click.argument("text")
def note(text: str) -> None:
    """Add a free-form note."""
    store = _get_store()
    store.ensure_template()
    store.add_item("Notes", text)
    console.print(f"[green]Note added.[/green]")


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


@profile.command("edit")
def edit() -> None:
    """Open USER.md in your default editor."""
    store = _get_store()
    store.ensure_template()
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")

    if sys.platform == "win32" and not editor:
        # Windows: use notepad
        subprocess.call(["notepad", str(store.path)])
    elif editor:
        subprocess.call([editor, str(store.path)])
    else:
        console.print(f"[yellow]No EDITOR set. File is at:[/yellow] {store.path}")


# ---------------------------------------------------------------------------
# contact subgroup
# ---------------------------------------------------------------------------


@profile.group("contact")
def contact() -> None:
    """Manage contacts in your profile."""


@contact.command("add")
@click.argument("name")
@click.option("--role", "role", default="", help="Relationship (e.g. boss, colleague, friend)")
@click.option("--note", "note_text", default="", help="Context note about this contact")
@click.option("--email", "email", default="", help="Email address")
def contact_add(name: str, role: str, note_text: str, email: str) -> None:
    """Add or update a contact."""
    store = _get_store()
    store.ensure_template()

    parts = [name]
    if role:
        parts[0] = f"{name} ({role})"
    if note_text:
        parts.append(note_text)
    if email:
        parts.append(email)

    entry = ": ".join([parts[0], ", ".join(parts[1:])]) if len(parts) > 1 else parts[0]

    # Remove existing entry for this contact name, then add fresh
    store.remove_item("Contacts", name)
    store.add_item("Contacts", entry)
    console.print(f"[green]Contact saved:[/green] {entry}")


@contact.command("remove")
@click.argument("name")
def contact_remove(name: str) -> None:
    """Remove a contact by name."""
    store = _get_store()
    if store.remove_item("Contacts", name):
        console.print(f"[green]Removed contact:[/green] {name}")
    else:
        console.print(f"[yellow]Contact not found:[/yellow] {name}")


@contact.command("list")
def contact_list() -> None:
    """List all contacts."""
    store = _get_store()
    entries = store.get_section("Contacts")
    if not entries:
        console.print("[dim]No contacts saved.[/dim]")
        return
    table = Table(title="Contacts", border_style="cyan", show_header=False)
    table.add_column("Entry", style="white")
    for e in entries:
        table.add_row(e.lstrip("- ").strip())
    console.print(table)


# ---------------------------------------------------------------------------
# project subgroup
# ---------------------------------------------------------------------------


@profile.group("project")
def project() -> None:
    """Manage active projects in your profile."""


@project.command("add")
@click.argument("name")
@click.option("--status", "status", default="active", show_default=True,
              help="Project status (active, review, paused, completed)")
@click.option("--desc", "description", default="", help="Short description")
@click.option("--deadline", "deadline", default="", help="Deadline date (e.g. 2026-05-01)")
def project_add(name: str, status: str, description: str, deadline: str) -> None:
    """Add or update an active project."""
    store = _get_store()
    store.ensure_template()

    # Remove any existing entry for this project first
    store.remove_item("Active Projects", name)

    parts = [f"{name} [{status}]"]
    if description:
        parts.append(description)
    if deadline:
        parts.append(f"Deadline: {deadline}")

    entry = ": ".join([parts[0], " | ".join(parts[1:])]) if len(parts) > 1 else parts[0]
    store.add_item("Active Projects", entry)
    console.print(f"[green]Project saved:[/green] {entry}")


@project.command("update")
@click.argument("name")
@click.option("--status", "status", default=None, help="New status")
@click.option("--desc", "description", default=None, help="New description")
def project_update(name: str, status: Optional[str], description: Optional[str]) -> None:
    """Update status or description of an existing project."""
    store = _get_store()
    entries = store.get_section("Active Projects")
    found = next((e for e in entries if name.lower() in e.lower()), None)

    if found is None:
        console.print(f"[yellow]Project not found:[/yellow] {name}")
        console.print("[dim]Use 'jarvis profile project add' to create it first.[/dim]")
        return

    # Parse and update the found entry
    updated = found
    if status:
        import re
        updated = re.sub(r"\[.*?\]", f"[{status}]", updated)
        if "[" not in updated:
            updated = updated + f" [{status}]"
    if description:
        # Replace description portion after ": "
        if ": " in updated:
            before_colon, _, _ = updated.partition(": ")
            updated = f"{before_colon}: {description}"
        else:
            updated = f"{updated}: {description}"

    store.remove_item("Active Projects", name)
    store.add_item("Active Projects", updated.lstrip("- ").strip())
    console.print(f"[green]Project updated:[/green] {updated.lstrip('- ').strip()}")


@project.command("list")
def project_list() -> None:
    """List all active projects."""
    store = _get_store()
    entries = store.get_section("Active Projects")
    if not entries:
        console.print("[dim]No projects saved.[/dim]")
        return
    table = Table(title="Projects", border_style="cyan", show_header=False)
    table.add_column("Entry", style="white")
    for e in entries:
        table.add_row(e.lstrip("- ").strip())
    console.print(table)


@project.command("remove")
@click.argument("name")
def project_remove(name: str) -> None:
    """Remove a project by name."""
    store = _get_store()
    if store.remove_item("Active Projects", name):
        console.print(f"[green]Removed project:[/green] {name}")
    else:
        console.print(f"[yellow]Project not found:[/yellow] {name}")
