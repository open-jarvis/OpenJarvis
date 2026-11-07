"""Rich-formatted error hints for common CLI failure modes."""

from __future__ import annotations

from typing import Optional


def hint_no_config() -> str:
    """Return a suggestion when no config file is found."""
    return (
        "[yellow]Hint:[/yellow] No config file found.\n"
        "  Run [bold]friday init[/bold] to detect hardware and generate "
        "[cyan]~/.friday_ai/config.toml[/cyan].\n"
        "  Or run [bold]friday quickstart[/bold] for a guided setup."
    )


def hint_no_engine(engine_name: Optional[str] = None) -> str:
    """Return a suggestion when the inference engine is unreachable."""
    name = engine_name or "ollama"
    return (
        f"[yellow]Hint:[/yellow] Engine '{name}' is not reachable.\n"
        f"  Make sure the {name} server is running.\n"
        "  Run [bold]friday doctor[/bold] to check all engines.\n"
        "  Run [bold]friday quickstart[/bold] for guided setup.\n"
        "\n"
        "  [dim]To use a remote engine:[/dim]\n"
        f"    [cyan]friday config set engine.{name}.host http://<remote-ip>:<port>[/cyan]\n"
        f"    [dim]or[/dim] [cyan]export OLLAMA_HOST=http://<remote-ip>:11434[/cyan]"
    )


def hint_no_model(model_name: Optional[str] = None) -> str:
    """Return a suggestion when no model is available."""
    if model_name:
        return (
            f"[yellow]Hint:[/yellow] Model '{model_name}' not found.\n"
            f"  Try: [bold]ollama pull {model_name}[/bold]\n"
            "  Run [bold]friday model list[/bold] to see available models."
        )
    return (
        "[yellow]Hint:[/yellow] No models available.\n"
        "  Pull a model first: [bold]ollama pull qwen3.5:2b[/bold]\n"
        "  Run [bold]friday model list[/bold] to see available models."
    )


def mining_not_running_hint(cfg: object | None, sidecar_present: bool) -> Optional[str]:
    """Return a mining hint when configured but no session sidecar exists."""
    if cfg is None or sidecar_present:
        return None
    return "mining configured but not running - start it with `friday mine start`"
