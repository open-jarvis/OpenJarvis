"""``jarvis gateway start|stop|status|logs`` — multi-channel gateway management."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

import click


def _require_service_manager() -> None:
    """Fail cleanly where systemd/launchd do not exist (Windows)."""
    if platform.system() == "Windows":
        raise click.ClickException(
            "The gateway service manager (systemd/launchd) is not available on "
            "Windows. Run the gateway in the foreground with `jarvis gateway "
            "start` without --install."
        )


@click.group()
def gateway() -> None:
    """Manage the OpenJarvis multi-channel gateway."""


@gateway.command()
@click.option(
    "--install",
    is_flag=True,
    help="Generate and enable systemd/launchd service",
)
def start(install: bool) -> None:
    """Start the gateway daemon."""
    if install:
        _require_service_manager()
        import platform as plat

        from openjarvis.daemon.service import (
            generate_launchd_plist,
            generate_systemd_service,
        )

        if plat.system() == "Darwin":
            plist_path = (
                Path.home() / "Library/LaunchAgents/com.openjarvis.gateway.plist"
            )
            generate_launchd_plist(plist_path)
            click.echo(f"Wrote {plist_path}")
            subprocess.run(
                ["launchctl", "load", str(plist_path)],
                check=False,
            )
        else:
            service_path = (
                Path.home() / ".config/systemd/user/openjarvis-gateway.service"
            )
            generate_systemd_service(service_path)
            click.echo(f"Wrote {service_path}")
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                check=False,
            )
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "openjarvis-gateway"],
                check=False,
            )
    else:
        raise click.ClickException(
            "The standalone gateway daemon is not implemented. Channel "
            "handling runs inside the API server: start it with `jarvis serve` "
            "or `jarvis start`."
        )


@gateway.command()
def stop() -> None:
    """Stop the gateway daemon."""
    _require_service_manager()
    import platform as plat

    if plat.system() == "Darwin":
        subprocess.run(
            ["launchctl", "remove", "com.openjarvis.gateway"],
            check=False,
        )
    else:
        subprocess.run(
            ["systemctl", "--user", "stop", "openjarvis-gateway"],
            check=False,
        )
    click.echo("Gateway stopped.")


@gateway.command()
def status() -> None:
    """Check gateway status."""
    _require_service_manager()
    import platform as plat

    if plat.system() == "Darwin":
        subprocess.run(
            ["launchctl", "list", "com.openjarvis.gateway"],
            check=False,
        )
    else:
        subprocess.run(
            ["systemctl", "--user", "status", "openjarvis-gateway"],
            check=False,
        )


@gateway.command()
def logs() -> None:
    """View gateway logs."""
    _require_service_manager()
    import platform as plat

    if plat.system() == "Darwin":
        click.echo("Check ~/Library/Logs/com.openjarvis.gateway.log")
    else:
        subprocess.run(
            ["journalctl", "--user", "-u", "openjarvis-gateway", "-f"],
            check=False,
        )
