"""``jarvis config`` — configuration inspection commands."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table


@click.group()
def config() -> None:
    """Inspect configuration — show loaded settings, hardware, and config files."""


def _get_config_path(path: str | None) -> Path:
    """Determine the config path from argument or environment."""
    from openjarvis.core.config import DEFAULT_CONFIG_PATH

    if path:
        return Path(path)
    return Path(os.environ.get("OPENJARVIS_CONFIG", DEFAULT_CONFIG_PATH))


def _show_hardware_info(console: Console, show_recommendations: bool = True) -> None:
    """Display detected hardware information."""
    from openjarvis.core.config import detect_hardware, recommend_engine

    hardware = detect_hardware()

    console.print("\n[bold]Detected Hardware[/bold]")

    hardware_table = Table(show_header=True, header_style="cyan")
    hardware_table.add_column("Component", style="green")
    hardware_table.add_column("Value", style="white")

    # Platform
    hardware_table.add_row("Platform", str(hardware.platform))

    # CPU
    if hardware.cpu_brand:
        hardware_table.add_row("CPU", hardware.cpu_brand)
    hardware_table.add_row("CPU Count", str(hardware.cpu_count))
    hardware_table.add_row("RAM", f"{hardware.ram_gb:.1f} GB")

    # GPU
    if hardware.gpu:
        hardware_table.add_row("GPU Vendor", hardware.gpu.vendor)
        hardware_table.add_row("GPU Model", hardware.gpu.name)
        hardware_table.add_row("GPU VRAM", f"{hardware.gpu.vram_gb:.1f} GB")
        hardware_table.add_row("GPU Count", str(hardware.gpu.count))

    console.print(hardware_table)

    # Show recommended engine
    if show_recommendations:
        recommended = recommend_engine(hardware)
        console.print(f"\n[bold]Recommended Engine:[/bold] [cyan]{recommended}[/cyan]")


def _show_config_template(console: Console, config_path: Path) -> None:
    """Show default config template when config file doesn't exist."""
    from openjarvis.core.config import (
        DEFAULT_CONFIG_DIR,
        detect_hardware,
        generate_default_toml,
    )

    console.print(f"[yellow]Config file not found: {config_path}[/yellow]")
    config_location = str(DEFAULT_CONFIG_DIR / "config.toml")
    msg = f"Create one at {config_location} or use --path to specify a location."
    console.print(f"[dim]{msg}[/dim]")

    console.print("\n[bold]Default Configuration Template:[/bold]")
    hw = detect_hardware()
    template = generate_default_toml(hw)
    syntax = Syntax(template, "toml", theme="monokai", line_numbers=True)
    console.print(Panel(syntax, border_style="dim"))


def _show_loaded_config(console: Console, config_path: Path, as_json: bool) -> None:
    """Show the loaded effective configuration from config.toml."""
    from openjarvis.core.config import load_config

    console.print(f"[dim]Loading config from: {config_path}[/dim]")

    if config_path.exists():
        config = load_config(config_path)

        if as_json:
            # Convert the dataclass to a dict and output as JSON
            from dataclasses import fields, is_dataclass

            def convert(obj):
                if obj is None:
                    return None
                if isinstance(obj, (str, int, float, bool)):
                    return obj
                if isinstance(obj, (list, tuple)):
                    return [convert(item) for item in obj]
                if isinstance(obj, dict):
                    return {k: convert(v) for k, v in obj.items()}
                if is_dataclass(obj):
                    result = {}
                    for field in fields(obj):
                        field_value = getattr(obj, field.name)
                        if field_value is not None:
                            result[field.name] = convert(field_value)
                    return result
                # Fallback for other types
                return str(obj)

            config_dict = convert(config)
            # Write JSON to stdout so it is pipeable
            stdout_console = Console()
            stdout_console.print_json(json.dumps(config_dict, indent=2, default=str))
        else:
            # Show as formatted table
            console.print("[bold]Engine Configuration[/bold]")
            console.print(f"  Default Engine: [cyan]{config.engine.default}[/cyan]")

            console.print("\n[bold]Intelligence Configuration[/bold]")
            console.print(
                f"  Default Model: [cyan]{config.intelligence.default_model}[/cyan]"
            )
            fallback = config.intelligence.fallback_model or "N/A"
            console.print(f"  Fallback Model: [cyan]{fallback}[/cyan]")
            console.print(
                f"  Temperature: [cyan]{config.intelligence.temperature}[/cyan]"
            )
            console.print(
                f"  Max Tokens: [cyan]{config.intelligence.max_tokens}[/cyan]"
            )

            console.print("\n[bold]Agent Configuration[/bold]")
            console.print(f"  Default Agent: [cyan]{config.agent.default_agent}[/cyan]")
            console.print(f"  Max Turns: [cyan]{config.agent.max_turns}[/cyan]")
            console.print(f"  Tools: [cyan]{config.agent.tools or 'none'}[/cyan]")
            ctx_mem = config.agent.context_from_memory
            console.print(f"  Context from Memory: [cyan]{ctx_mem}[/cyan]")

            # Show hardware info
            _show_hardware_info(console)

    else:
        _show_config_template(console, config_path)


def _show_toml_config(console: Console, config_path: Path) -> None:
    """Show the raw TOML configuration file content with syntax highlighting."""
    console.print(f"[dim]Loading config from: {config_path}[/dim]")

    if config_path.exists():
        config_content = config_path.read_text()
        syntax = Syntax(config_content, "toml", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title="Config File", border_style="cyan"))
    else:
        _show_config_template(console, config_path)


def _show_json_config(console: Console, config_path: Path) -> None:
    """Show the parsed TOML configuration as JSON."""
    console.print(f"[dim]Loading config from: {config_path}[/dim]")

    if config_path.exists():
        config_content = config_path.read_text()

        try:
            import tomllib  # Python 3.11+
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

        config_dict = tomllib.loads(config_content)
        # Write JSON to stdout so it is pipeable
        stdout_console = Console()
        stdout_console.print_json(json.dumps(config_dict, indent=2))
    else:
        _show_config_template(console, config_path)


def _show_hardware(console: Console) -> None:
    """Show detected hardware information with recommended engine and model."""
    from openjarvis.core.config import (
        detect_hardware,
        recommend_engine,
        recommend_model,
    )

    hardware = detect_hardware()
    _show_hardware_info(console, show_recommendations=False)

    # Show recommended engine
    recommended_engine = recommend_engine(hardware)
    console.print(
        f"\n[bold]Recommended Engine:[/bold] [cyan]{recommended_engine}[/cyan]"
    )

    # Show recommended model
    console.print("\n[bold]Model Recommendations[/bold]")
    recommended_model = recommend_model(hardware, recommended_engine)
    console.print(f"  Recommended Model: [cyan]{recommended_model}[/cyan]")


# Nested group for show sub-commands
@click.group(invoke_without_command=True)
@click.option("--path", "-p", default=None, help="Explicit config file path")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
@click.pass_context
def show_group(ctx: click.Context, path: str | None, as_json: bool) -> None:
    """Show configuration details."""
    # Default to 'loaded' if no subcommand is invoked
    if ctx.invoked_subcommand is None:
        console = Console(stderr=True)
        try:
            config_path = _get_config_path(path)
            _show_loaded_config(console, config_path, as_json)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")


@show_group.command()
@click.option("--path", "-p", default=None, help="Explicit config file path")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
def loaded(path: str | None, as_json: bool) -> None:
    """Show the loaded effective configuration from config.toml."""
    console = Console(stderr=True)
    try:
        config_path = _get_config_path(path)
        _show_loaded_config(console, config_path, as_json)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@show_group.command()
@click.option("--path", "-p", default=None, help="Explicit config file path")
def toml(path: str | None) -> None:
    """Show the raw TOML configuration file content with syntax highlighting."""
    console = Console(stderr=True)
    try:
        config_path = _get_config_path(path)
        _show_toml_config(console, config_path)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@show_group.command("json")
@click.option("--path", "-p", default=None, help="Explicit config file path")
def as_json(path: str | None) -> None:
    """Show the parsed TOML configuration as JSON."""
    console = Console(stderr=True)
    try:
        config_path = _get_config_path(path)
        _show_json_config(console, config_path)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@show_group.command()
def hardware() -> None:
    """Show detected hardware information with recommended engine and model."""
    console = Console(stderr=True)
    try:
        _show_hardware(console)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


# Register the show group under config
config.add_command(show_group, "show")


def _probe_engine_host(url: str, console: Console) -> None:
    """Probe an engine host URL and print reachability status."""
    try:
        resp = httpx.get(url.rstrip("/") + "/", timeout=2.0)
        if resp.status_code < 500:
            console.print(f"  [green]Reachable[/green] ({url})")
        else:
            console.print(
                f"  [yellow]Warning:[/yellow] Host returned status "
                f"{resp.status_code} — config saved anyway."
            )
    except Exception:
        console.print(
            f"  [yellow]Warning:[/yellow] Host unreachable ({url}) "
            f"— config saved anyway."
        )


def _coerce_value(value: str, target_type: type) -> object:
    """Coerce a CLI string value to the target Python type."""
    if target_type is bool:
        low = value.lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        raise ValueError(
            f"Invalid boolean value: {value!r} (expected: true/false, yes/no, 1/0)"
        )
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    return value


@click.command("set")
@click.argument("key")
@click.argument("value")
def set_config(key: str, value: str) -> None:
    """Set a configuration value (e.g. jarvis config set engine.ollama.host URL)."""
    import tomlkit

    from openjarvis.core.config import DEFAULT_CONFIG_DIR, validate_config_key

    console = Console(stderr=True)

    # Validate key
    try:
        target_type = validate_config_key(key)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    # Coerce value
    try:
        typed_value = _coerce_value(value, target_type)
    except (ValueError, TypeError) as exc:
        console.print(
            f"[red]Error:[/red] Cannot convert {value!r} to "
            f"{target_type.__name__}: {exc}"
        )
        raise SystemExit(1)

    # Load or create TOML document
    config_path = Path(
        os.environ.get("OPENJARVIS_CONFIG", DEFAULT_CONFIG_DIR / "config.toml")
    )
    if config_path.exists():
        doc = tomlkit.parse(config_path.read_text())
    else:
        doc = tomlkit.document()
        config_path.parent.mkdir(parents=True, exist_ok=True)

    # Set nested key
    parts = key.split(".")
    current = doc
    for part in parts[:-1]:
        if part not in current:
            current.add(part, tomlkit.table())
        current = current[part]
    current[parts[-1]] = typed_value

    # Write back
    config_path.write_text(tomlkit.dumps(doc))

    console.print(f"[green]Set[/green] {key} = {value!r}")

    # Probe engine host if applicable
    if re.match(r"^engine\.\w+\.host$", key):
        _probe_engine_host(value, console)


config.add_command(set_config, "set")


__all__ = ["config"]
