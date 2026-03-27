"""CLI commands for API key management."""

from __future__ import annotations

import os
import re
import stat

import click

from openjarvis.core.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
)
from openjarvis.server.auth_middleware import generate_api_key


@click.group("auth")
def auth() -> None:
    """Manage API authentication keys."""


@auth.command("create-key")
def create_key() -> None:
    """Generate a new API key and store it in config."""
    key = generate_api_key()
    config_path = DEFAULT_CONFIG_PATH

    # Ensure config directory exists
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Read existing config or start fresh
    if config_path.exists():
        content = config_path.read_text()
    else:
        content = ""

    # Update or add [server.auth] section
    if "[server.auth]" in content:
        content = re.sub(
            r'(api_key\s*=\s*)"[^"]*"',
            f'\\1"{key}"',
            content,
        )
    else:
        content += f'\n[server.auth]\napi_key = "{key}"\n'

    config_path.write_text(content)
    os.chmod(config_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600

    click.echo(f"API key generated: {key}")
    click.echo(f"Stored in: {config_path}")
    click.echo("File permissions set to 0600 (user-only read/write).")


@auth.command("revoke-key")
def revoke_key() -> None:
    """Revoke the current API key."""
    config_path = DEFAULT_CONFIG_PATH
    if not config_path.exists():
        click.echo("No config file found.")
        return

    content = config_path.read_text()
    if "api_key" not in content:
        click.echo("No API key found in config.")
        return

    content = re.sub(r'api_key\s*=\s*"[^"]*"', 'api_key = ""', content)
    config_path.write_text(content)
    click.echo("API key revoked.")
