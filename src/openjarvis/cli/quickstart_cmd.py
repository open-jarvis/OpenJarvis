"""``jarvis quickstart`` — guided 5-step setup for new users."""

from __future__ import annotations

import logging

import click
from rich.console import Console

from openjarvis.core.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    detect_hardware,
    generate_default_toml,
    recommend_engine,
)

logger = logging.getLogger(__name__)


def _check_engine_health(engine_key: str) -> bool:
    """Return True if the recommended engine is reachable."""
    try:
        import openjarvis.engine  # noqa: F401 — trigger registration
        from openjarvis.core.config import load_config
        from openjarvis.core.registry import EngineRegistry
        from openjarvis.engine import _discovery

        config = load_config()
        if engine_key not in EngineRegistry.keys():
            return False
        engine = _discovery._make_engine(engine_key, config)
        return engine.health()
    except Exception as exc:
        logger.warning("Engine health check failed for %r: %s", engine_key, exc)
        return False


def _discover_healthy_engines() -> list[str]:
    """Return keys for all healthy engines discovered at runtime."""
    try:
        import openjarvis.engine  # noqa: F401 — trigger registration
        from openjarvis.core.config import load_config
        from openjarvis.engine import _discovery

        config = load_config()
        return [key for key, _ in _discovery.discover_engines(config)]
    except Exception as exc:
        logger.warning("Healthy engine discovery failed: %s", exc)
        return []


def _check_model_available(engine_key: str) -> bool:
    """Return True if at least one model is available on the engine."""
    try:
        from openjarvis.core.config import load_config
        from openjarvis.core.registry import EngineRegistry
        from openjarvis.engine import _discovery

        config = load_config()
        if engine_key not in EngineRegistry.keys():
            return False
        engine = _discovery._make_engine(engine_key, config)
        return bool(engine.list_models())
    except Exception as exc:
        logger.warning("Model availability check failed for %r: %s", engine_key, exc)
        return False


def _test_query(engine_key: str) -> str:
    """Run a quick test query and return the response text."""
    try:
        from openjarvis import Jarvis

        j = Jarvis(engine_key=engine_key)
        response = j.ask("Say hello in one sentence.")
        j.close()
        return response
    except Exception as exc:
        return f"(query failed: {exc})"


@click.command()
@click.option("--force", is_flag=True, help="Redo all steps even if already done.")
def quickstart(force: bool) -> None:
    """Guided 5-step setup for new users."""
    console = Console()

    # Step 1: Detect hardware
    console.print("[bold cyan][1/5][/bold cyan] Detecting hardware...")
    hw = detect_hardware()
    console.print(f"  Platform : {hw.platform}")
    console.print(f"  CPU      : {hw.cpu_brand} ({hw.cpu_count} cores)")
    console.print(f"  RAM      : {hw.ram_gb} GB")
    if hw.gpu:
        console.print(
            f"  GPU      : {hw.gpu.name} ({hw.gpu.vram_gb} GB VRAM, x{hw.gpu.count})"
        )
    else:
        console.print("  GPU      : none detected")

    engine_key = recommend_engine(hw)

    # Step 2: Write config
    console.print()
    console.print("[bold cyan][2/5][/bold cyan] Writing config...")
    if DEFAULT_CONFIG_PATH.exists() and not force:
        console.print(
            f"  [dim]Config already exists at {DEFAULT_CONFIG_PATH} (skip)[/dim]"
        )
    else:
        toml_content = generate_default_toml(hw)
        DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_CONFIG_PATH.write_text(toml_content)
        console.print(f"  [green]Config written to {DEFAULT_CONFIG_PATH}[/green]")

    # Step 3: Check engine
    console.print()
    console.print(f"[bold cyan][3/5][/bold cyan] Checking engine ({engine_key})...")
    active_engine = engine_key
    if not _check_engine_health(engine_key):
        fallbacks = [k for k in _discover_healthy_engines() if k != engine_key]
        if fallbacks:
            active_engine = fallbacks[0]
            console.print(
                f"  [yellow]Engine '{engine_key}' is not reachable; "
                f"falling back to '{active_engine}'.[/yellow]"
            )
        else:
            console.print(
                f"  [red bold]Engine '{engine_key}' is not reachable.[/red bold]"
            )
            console.print()
            console.print(f"  Start the {engine_key} server and try again.")
            console.print("  Run [bold]jarvis doctor[/bold] for detailed diagnostics.")
            raise SystemExit(1)
    else:
        console.print(f"  [green]Engine '{engine_key}' is healthy.[/green]")

    # Step 4: Verify model
    console.print()
    console.print("[bold cyan][4/5][/bold cyan] Checking for available models...")
    if not _check_model_available(active_engine):
        console.print("  [yellow]No models found.[/yellow]")
        console.print(
            "  Pull a model first (e.g. [bold]ollama pull qwen3.5:2b[/bold])."
        )
        raise SystemExit(1)
    console.print("  [green]Models available.[/green]")

    # Step 5: Test query
    console.print()
    console.print("[bold cyan][5/5][/bold cyan] Running test query...")
    response = _test_query(active_engine)
    console.print(f"  [green]Response:[/green] {response[:200]}")

    console.print()
    console.print(
        '[bold green]Setup complete![/bold green] Try: [bold]jarvis ask "Hello"[/bold]'
    )
