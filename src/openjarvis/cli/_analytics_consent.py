"""Dedicated terminal consent for optional external usage analytics."""

from __future__ import annotations

import click
import tomlkit

from openjarvis.core.config import AnalyticsConfig


def ask_analytics_consent(host: str | None = None) -> bool:
    """Ask once per init; a deliberate Enter/Y consents, EOF/cancellation does not."""
    stream = click.get_text_stream("stdin")
    if not stream.isatty():
        return False
    click.echo(
        "\nHelp improve OpenJarvis by sharing optional usage statistics.\n"
        "Data includes feature usage, timings, token counts, error categories,\n"
        "environment metadata, and a random installation ID.\n"
        "Recipient: the OpenJarvis team's PostHog analytics endpoint.\n"
        "Privacy details: https://open-jarvis.github.io/OpenJarvis/telemetry/\n"
        "You can disable sharing later: jarvis config set analytics.enabled false\n"
        "(then restart the server and reload the app).\n"
        "Declining does not change OpenJarvis functionality.",
        err=True,
    )
    click.echo(f"Analytics destination: {host or AnalyticsConfig().host}", err=True)
    while True:
        click.echo("Press Enter or Y to consent, or N to decline: ", nl=False, err=True)
        try:
            answer = stream.readline()
        except (EOFError, KeyboardInterrupt):
            click.echo(err=True)
            return False
        if not answer:
            return False
        answer = answer.strip().lower()
        if answer in ("", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        click.echo("Please press Enter, type Y, or type N.", err=True)


def apply_analytics_choice(content: str, choice: bool | None, *, prompt: bool) -> str:
    """Persist an explicit flag or terminal choice in generated/copied TOML."""
    if choice is None:
        if not prompt or not click.get_text_stream("stdin").isatty():
            # Defaults are off. Preserve an explicitly supplied config in
            # unattended init rather than rewriting unrelated input files.
            return content
        doc = tomlkit.parse(content)
        host = doc.get("analytics", {}).get("host", AnalyticsConfig().host)
        choice = ask_analytics_consent(str(host))
    doc = tomlkit.parse(content)
    if "analytics" not in doc:
        doc.add("analytics", tomlkit.table())
    doc["analytics"]["enabled"] = choice
    doc["analytics"]["choice_recorded"] = True
    return tomlkit.dumps(doc)
