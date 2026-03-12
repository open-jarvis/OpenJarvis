"""``jarvis init`` — detect hardware, generate config, write to disk."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel

from openjarvis.core.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    detect_hardware,
    generate_default_toml,
    generate_minimal_toml,
    recommend_engine,
    recommend_model,
)


def _next_steps_text(engine: str, model: str = "") -> str:
    """Return engine-specific next-steps guidance after init."""
    pull_model = model or "qwen3.5:4b"
    steps: dict[str, str] = {
        "ollama": (
            "Next steps:\n"
            "\n"
            "  1. Start the model server:\n"
            f"     jarvis host {pull_model} --backend ollama\n"
            "\n"
            "  2. Try it out:\n"
            "     jarvis ask \"Hello\"\n"
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
        "vllm": (
            "Next steps:\n"
            "\n"
            "  1. Start the vLLM server:\n"
            "     jarvis host Qwen/Qwen3-4B --backend vllm\n"
            "\n"
            "  2. Try it out:\n"
            "     jarvis ask \"Hello\"\n"
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
        "llamacpp": (
            "Next steps:\n"
            "\n"
            "  1. Start the llama.cpp server (use path to a GGUF model):\n"
            "     jarvis host path/to/model.gguf --backend llamacpp\n"
            "\n"
            "  2. Try it out:\n"
            "     jarvis ask \"Hello\"\n"
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
        "sglang": (
            "Next steps:\n"
            "\n"
            "  1. Start the SGLang server:\n"
            "     jarvis host Qwen/Qwen3-8B --backend sglang\n"
            "\n"
            "  2. Try it out:\n"
            "     jarvis ask \"Hello\"\n"
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
        "mlx": (
            "Next steps:\n"
            "\n"
            "  1. Start the MLX server:\n"
            "     jarvis host mlx-community/Qwen2.5-7B-4bit --backend mlx\n"
            "\n"
            "  2. Try it out:\n"
            "     jarvis ask \"Hello\"\n"
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
        "lmstudio": (
            "Next steps:\n"
            "\n"
            "  1. Download LM Studio:\n"
            "     https://lmstudio.ai\n"
            "\n"
            "  2. Load a model and start the local server (port 1234)\n"
            "\n"
            "  3. Try it out:\n"
            "     jarvis ask \"Hello\"\n"
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
    }
    return steps.get(engine, steps["ollama"])


@click.command()
@click.option(
    "--force", is_flag=True, help="Overwrite existing config without prompting."
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Path to config file to use.",
)
@click.option(
    "--full",
    "full_config",
    is_flag=True,
    help="Generate full reference config with all sections",
)
def init(force: bool, config: Optional[Path], full_config: bool = False) -> None:
    """Detect hardware and generate ~/.openjarvis/config.toml."""
    console = Console()

    if DEFAULT_CONFIG_PATH.exists() and not force:
        console.print(
            f"[yellow]Config already exists at {DEFAULT_CONFIG_PATH}[/yellow]"
        )
        console.print("Use [bold]--force[/bold] to overwrite.")
        raise SystemExit(1)

    console.print("[bold]Detecting hardware...[/bold]")
    hw = detect_hardware()

    console.print(f"  Platform : {hw.platform}")
    console.print(f"  CPU      : {hw.cpu_brand} ({hw.cpu_count} cores)")
    console.print(f"  RAM      : {hw.ram_gb} GB")
    if hw.gpu:
        mem_label = "unified memory" if hw.gpu.vendor == "apple" else "VRAM"
        gpu = hw.gpu
        console.print(
            f"  GPU      : {gpu.name} ({gpu.vram_gb} GB {mem_label}, x{gpu.count})"
        )
    else:
        console.print("  GPU      : none detected")

    if config:
        toml_content = config.read_text()
    else:
        if full_config:
            toml_content = generate_default_toml(hw)
        else:
            toml_content = generate_minimal_toml(hw)

    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if config:
        config.write_text(toml_content)
    else:
        DEFAULT_CONFIG_PATH.write_text(toml_content)

    console.print()
    console.print(
        Panel(toml_content, title=str(DEFAULT_CONFIG_PATH), border_style="green")
    )
    console.print("[green]Config written successfully.[/green]")

    engine = recommend_engine(hw)
    model = recommend_model(hw, engine)
    if model:
        console.print(f"\n  [bold]Recommended model:[/bold] {model}")
    console.print()
    console.print(
        Panel(
            _next_steps_text(engine, model),
            title="Getting Started",
            border_style="cyan",
        )
    )

