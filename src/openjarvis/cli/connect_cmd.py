"""``jarvis connect`` -- manage data source connections."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table


def _list_sources(registry: object) -> None:
    """Print a Rich table of registered connectors and their sync status."""
    console = Console()
    items = registry.items()  # type: ignore[attr-defined]

    if not items:
        console.print("[yellow]No connectors registered.[/yellow]")
        return

    table = Table(title="Connected Sources")
    table.add_column("Source", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")

    for key, connector_cls in items:
        # Try to instantiate with no args to check status (best-effort)
        try:
            instance = connector_cls()
            connected = instance.is_connected()
            status = "connected" if connected else "disconnected"
            auth_type = getattr(connector_cls, "auth_type", "unknown")
        except Exception:  # noqa: BLE001
            status = "unknown"
            auth_type = getattr(connector_cls, "auth_type", "unknown")

        table.add_row(key, auth_type, status)

    console.print(table)


def _disconnect_source(registry: object, source: str, account: str = "") -> None:
    """Find and disconnect a registered source connector."""
    console = Console()

    if source == "google" and account:
        from openjarvis.connectors.oauth import (
            delete_tokens,
            google_account_credentials_path,
        )

        delete_tokens(google_account_credentials_path(account))
        console.print(f"[green]Disconnected google:{account}.[/green]")
        return

    if not registry.contains(source):  # type: ignore[attr-defined]
        console.print(f"[red]Unknown source: {source}[/red]")
        return

    connector_cls = registry.get(source)  # type: ignore[attr-defined]
    try:
        try:
            instance = connector_cls(account=account) if account else connector_cls()
        except TypeError:
            instance = connector_cls()
        instance.disconnect()
        suffix = f":{account}" if account else ""
        console.print(f"[green]Disconnected {source}{suffix}.[/green]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to disconnect {source}: {exc}[/red]")


def _connect_source(
    registry: object,
    source: str,
    path: str = "",
    account: str = "",
) -> None:
    """Route connector setup by auth_type."""
    console = Console()

    if source == "google":
        from openjarvis.connectors.oauth import (
            OAUTH_PROVIDERS,
            get_client_credentials,
            run_connector_oauth,
            save_client_credentials,
        )

        try:
            provider = OAUTH_PROVIDERS["google"]
            creds = get_client_credentials(provider, account=account)
            client_id = creds[0] if creds else ""
            client_secret = creds[1] if creds else ""

            if not client_id or not client_secret:
                console.print("[cyan]First-time setup for Google.[/cyan]")
                console.print(
                    f"[yellow]Create an OAuth app at: {provider.setup_url}[/yellow]"
                )
                console.print(f"[dim]{provider.setup_hint}[/dim]")
                client_id = click.prompt("Client ID")
                client_secret = click.prompt("Client Secret")
                save_client_credentials(
                    provider,
                    client_id,
                    client_secret,
                    account=account,
                )

            run_connector_oauth(
                "gmail",
                client_id,
                client_secret,
                account=account,
            )
            suffix = f":{account}" if account else ""
            console.print(f"[green]google{suffix} authorised successfully.[/green]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]OAuth flow failed for google: {exc}[/red]")
        return

    if not registry.contains(source):  # type: ignore[attr-defined]
        console.print(f"[red]Unknown source: {source}[/red]")
        console.print(
            "[yellow]Available sources: "
            + ", ".join(registry.keys())  # type: ignore[attr-defined]
            + "[/yellow]"
        )
        return

    connector_cls = registry.get(source)  # type: ignore[attr-defined]
    auth_type = getattr(connector_cls, "auth_type", "")

    if auth_type == "filesystem":
        # Filesystem connectors (e.g. Obsidian) need a path
        if not path:
            console.print(
                f"[red]{source} requires a --path argument (e.g. --path ~/vault).[/red]"
            )
            return
        try:
            instance = connector_cls(vault_path=path)
        except TypeError:
            try:
                instance = connector_cls(path)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]Failed to create {source} connector: {exc}[/red]")
                return

        if instance.is_connected():
            console.print(f"[green]{source} connected at path: {path}[/green]")
        else:
            console.print(
                f"[red]{source}: path '{path}' does not exist or is not accessible."
                "[/red]"
            )

    elif auth_type == "oauth":
        # OAuth connectors — auto-open browser + catch callback
        from openjarvis.connectors.oauth import (
            get_client_credentials,
            get_provider_for_connector,
            run_connector_oauth,
            save_client_credentials,
        )

        try:
            try:
                instance = (
                    connector_cls(account=account) if account else connector_cls()
                )
            except TypeError:
                instance = connector_cls()
            if instance.is_connected():
                suffix = f":{account}" if account else ""
                console.print(f"[green]{source}{suffix} is already connected.[/green]")
                return

            provider = get_provider_for_connector(source)
            if provider is None:
                console.print(f"[red]No OAuth provider configured for {source}.[/red]")
                return

            creds = get_client_credentials(provider, account=account)
            client_id = creds[0] if creds else ""
            client_secret = creds[1] if creds else ""

            if not client_id or not client_secret:
                console.print(f"[cyan]First-time setup for {source}.[/cyan]")
                console.print(
                    f"[yellow]Create an OAuth app at: {provider.setup_url}[/yellow]"
                )
                console.print(f"[dim]{provider.setup_hint}[/dim]")
                client_id = click.prompt("Client ID")
                client_secret = click.prompt("Client Secret")
                save_client_credentials(
                    provider,
                    client_id,
                    client_secret,
                    account=account,
                )

            run_connector_oauth(source, client_id, client_secret, account=account)
            suffix = f":{account}" if account else ""
            console.print(f"[green]{source}{suffix} authorised successfully.[/green]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]OAuth flow failed for {source}: {exc}[/red]")

    elif auth_type == "token":
        # Token-based connectors (e.g. Oura) — prompt for personal access token
        import json
        from pathlib import Path

        from openjarvis.connectors.oauth import save_tokens
        from openjarvis.core.config import DEFAULT_CONFIG_DIR

        try:
            instance = connector_cls()
            if instance.is_connected():
                console.print(f"[green]{source} is already connected.[/green]")
                return

            token = click.prompt(f"Enter your {source} personal access token")
            token_dir = Path(DEFAULT_CONFIG_DIR) / "connectors"
            token_dir.mkdir(parents=True, exist_ok=True)
            token_file = token_dir / f"{source}.json"
            token_file.write_text(json.dumps({"token": token}))
            save_tokens(source, {"token": token})
            console.print(f"[green]{source} connected successfully.[/green]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Token setup failed for {source}: {exc}[/red]")

    else:
        # Generic / bridge connectors
        try:
            instance = connector_cls()
            connected = instance.is_connected()
            status = "connected" if connected else "disconnected"
            console.print(f"{source} status: {status}")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Failed to connect {source}: {exc}[/red]")


@click.group(invoke_without_command=True)
@click.argument("source", required=False)
@click.option(
    "--list",
    "list_sources",
    is_flag=True,
    help="List connected sources and sync status.",
)
@click.option(
    "--sync",
    "trigger_sync",
    is_flag=True,
    help="Trigger incremental sync for all sources.",
)
@click.option(
    "--disconnect",
    "disconnect_source",
    default="",
    help="Disconnect a source.",
)
@click.option(
    "--path",
    default="",
    help="Path for filesystem connectors (e.g., Obsidian vault).",
)
@click.option(
    "--account",
    default="",
    help="Named connector account alias (e.g., personal, work).",
)
@click.option(
    "--profile",
    default="",
    help="Alias for --account.",
)
@click.pass_context
def connect(
    ctx: click.Context,
    source: str | None,
    list_sources: bool,
    trigger_sync: bool,
    disconnect_source: str,
    path: str,
    account: str,
    profile: str,
) -> None:
    """Manage data source connections (Gmail, Obsidian, etc.)."""
    # Lazy imports to avoid top-level side effects
    import openjarvis.connectors  # noqa: F401 — registers all connectors
    from openjarvis.core.registry import ConnectorRegistry

    account_alias = account or profile

    if list_sources:
        _list_sources(ConnectorRegistry)
        return

    if trigger_sync:
        click.echo("Sync not yet implemented in CLI")
        return

    if disconnect_source:
        _disconnect_source(ConnectorRegistry, disconnect_source, account=account_alias)
        return

    if source:
        _connect_source(ConnectorRegistry, source, path=path, account=account_alias)
        return

    # No arguments — show help
    click.echo(ctx.get_help())
