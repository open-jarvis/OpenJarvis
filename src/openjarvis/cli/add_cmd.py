"""``jarvis add`` — quick MCP server setup."""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console

from openjarvis.core.config import DEFAULT_CONFIG_DIR

_MCP_CONFIG_DIR = DEFAULT_CONFIG_DIR / "mcp"


# Known MCP server templates
_MCP_TEMPLATES = {
    "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env_key": "GITHUB_PERSONAL_ACCESS_TOKEN",
        "description": "GitHub API (repos, issues, PRs)",
    },
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        "env_key": None,
        "description": "Local filesystem operations",
    },
    "slack": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env_key": "SLACK_BOT_TOKEN",
        "description": "Slack workspace integration",
    },
    "postgres": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres"],
        "env_key": "POSTGRES_CONNECTION_STRING",
        "description": "PostgreSQL database",
    },
    "brave-search": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env_key": "BRAVE_API_KEY",
        "description": "Brave web search",
    },
    "memory": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "env_key": None,
        "description": "Knowledge graph memory",
    },
    "puppeteer": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "env_key": None,
        "description": "Browser automation via Puppeteer",
    },
    "google-maps": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-google-maps"],
        "env_key": "GOOGLE_MAPS_API_KEY",
        "description": "Google Maps API",
    },
}


@click.command()
@click.argument("server_name")
@click.option("--key", default=None, help="API key or token for the server.")
@click.option(
    "--args",
    "extra_args",
    default=None,
    help="Additional arguments (comma-separated).",
)
def add(server_name: str, key: str | None, extra_args: str | None) -> None:
    """Add an MCP server configuration.

    Quick setup for common MCP servers:

      jarvis add github --key TOKEN
      jarvis add filesystem
      jarvis add slack --key TOKEN

    Known servers: github, filesystem, slack, postgres, brave-search,
    memory, puppeteer, google-maps
    """
    console = Console(stderr=True)

    template = _MCP_TEMPLATES.get(server_name)
    if template is None:
        console.print(f"[red]Unknown MCP server: {server_name}[/red]")
        console.print("[dim]Known servers:[/dim]")
        for name, tmpl in _MCP_TEMPLATES.items():
            console.print(f"  [cyan]{name}[/cyan] — {tmpl['description']}")
        sys.exit(1)

    # Build server config
    config = {
        "command": template["command"],
        "args": list(template["args"]),
    }

    # Add extra args
    if extra_args:
        config["args"].extend(a.strip() for a in extra_args.split(","))

    # Handle API key
    env = {}
    env_key = template["env_key"]
    if env_key:
        if key:
            env[env_key] = key
        else:
            console.print(
                f"[yellow]Tip: Pass --key to set {env_key},"
                " or set it as an environment variable.[/yellow]"
            )
    if env:
        config["env"] = env

    # Save to MCP config dir
    _MCP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_file = _MCP_CONFIG_DIR / f"{server_name}.json"
    config_file.write_text(json.dumps(config, indent=2))

    console.print(
        f"[green]Added MCP server: {server_name}[/green]\n"
        f"  Config: {config_file}\n"
        f"  Description: {template['description']}"
    )
    if env_key and not key:
        console.print(f"  [dim]Set {env_key} env var or re-run with --key[/dim]")


__all__ = ["add"]
