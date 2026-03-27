"""``jarvis init`` — detect hardware, generate config, write to disk."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import httpx
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from openjarvis.cli.model import find_model_spec, hf_download, ollama_pull
from openjarvis.cli.scan_cmd import PrivacyScanner
from openjarvis.core.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    detect_hardware,
    estimated_download_gb,
    generate_default_toml,
    generate_minimal_toml,
    recommend_engine,
    recommend_model,
)

# Engines supported by ``jarvis init --engine``.
_SUPPORTED_ENGINES = [
    "ollama",
    "vllm",
    "sglang",
    "llamacpp",
    "mlx",
    "lmstudio",
    "exo",
    "nexa",
]


def _detect_running_engines() -> list[str]:
    """Probe well-known ports and return engine keys that respond."""
    import httpx

    _PROBES: dict[str, str] = {
        "ollama": "http://localhost:11434/api/tags",
        "vllm": "http://localhost:8000/v1/models",
        "sglang": "http://localhost:30000/v1/models",
        "llamacpp": "http://localhost:8080/v1/models",
        "mlx": "http://localhost:8080/v1/models",
        "lmstudio": "http://localhost:1234/v1/models",
        "exo": "http://localhost:52415/v1/models",
        "nexa": "http://localhost:18181/v1/models",
    }
    running: list[str] = []
    for key, url in _PROBES.items():
        try:
            resp = httpx.get(url, timeout=2.0)
            if resp.status_code < 500:
                running.append(key)
        except Exception:
            pass
    return running


def _next_steps_text(engine: str, model: str = "") -> str:
    """Return engine-specific next-steps guidance after init."""
    pull_model = model or "qwen3.5:2b"
    steps: dict[str, str] = {
        "ollama": (
            "Next steps:\n"
            "\n"
            "  1. Install and start Ollama:\n"
            "     curl -fsSL https://ollama.com/install.sh | sh\n"
            "     ollama serve\n"
            "\n"
            f"  2. Pull a model:\n"
            f"     ollama pull {pull_model}\n"
            "\n"
            "  3. Try it out:\n"
            '     jarvis ask "Hello"\n'
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
        "vllm": (
            "Next steps:\n"
            "\n"
            "  1. Install and start vLLM:\n"
            "     pip install vllm\n"
            "     vllm serve Qwen/Qwen3-4B\n"
            "\n"
            "  2. Try it out:\n"
            '     jarvis ask "Hello"\n'
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
        "llamacpp": (
            "Next steps:\n"
            "\n"
            "  1. Install and start llama.cpp:\n"
            "     brew install llama.cpp\n"
            "     llama-server -m path/to/model.gguf\n"
            "\n"
            "  2. Try it out:\n"
            '     jarvis ask "Hello"\n'
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
        "sglang": (
            "Next steps:\n"
            "\n"
            "  1. Install and start SGLang:\n"
            "     pip install sglang[all]\n"
            "     python -m sglang.launch_server --model-path Qwen/Qwen3-8B\n"
            "\n"
            "  2. Try it out:\n"
            '     jarvis ask "Hello"\n'
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
        "mlx": (
            "Next steps:\n"
            "\n"
            "  1. Install and start MLX:\n"
            "     pip install mlx-lm\n"
            "     mlx_lm.server --model mlx-community/Qwen2.5-7B-4bit\n"
            "\n"
            "  2. Try it out:\n"
            '     jarvis ask "Hello"\n'
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
            '     jarvis ask "Hello"\n'
            "\n"
            "  Run `jarvis doctor` to verify your setup."
        ),
        "exo": (
            "Next steps:\n\n"
            "  1. Install and start Exo:\n"
            "     pip install exo\n"
            "     exo\n\n"
            "  2. Try it out:\n"
            '     jarvis ask "Hello"\n\n'
            "  Run `jarvis doctor` to verify your setup."
        ),
        "nexa": (
            "Next steps:\n\n"
            "  1. Install and start Nexa:\n"
            "     pip install nexaai\n"
            "     nexa server\n\n"
            "  2. Try it out:\n"
            '     jarvis ask "Hello"\n\n'
            "  Run `jarvis doctor` to verify your setup."
        ),
    }
    return steps.get(engine, steps["ollama"])


def _quick_privacy_check(console: Console) -> None:
    """Run critical privacy checks and print compact summary."""
    scanner = PrivacyScanner()
    results = scanner.run_quick()
    if results:
        console.print("  [bold]Privacy check:[/bold]")
        for r in results:
            if r.status == "ok":
                console.print(f"  [green]\u2713[/green] {r.message}")
            elif r.status == "warn":
                console.print(f"  [yellow]![/yellow] {r.message}")
            elif r.status == "fail":
                console.print(f"  [red]\u2717[/red] {r.message}")
    console.print()
    console.print("  Run [cyan]jarvis scan[/cyan] for a full environment audit.")


def _do_download(engine: str, model: str, spec, console: Console) -> None:
    """Dispatch model download based on engine type."""
    import os

    if engine == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        ollama_pull(host, model, console)
    elif engine == "llamacpp":
        repo = spec.metadata.get("hf_repo", "")
        gguf = spec.metadata.get("gguf_file", "")
        if repo and gguf:
            console.print(f"  Downloading [cyan]{gguf}[/cyan] from {repo}...")
            hf_download(repo, gguf, console)
        else:
            console.print(f"  [yellow]No GGUF download info for {model}[/yellow]")
    elif engine == "mlx":
        mlx_repo = spec.metadata.get("mlx_repo", "")
        if mlx_repo:
            console.print(f"  Downloading [cyan]{mlx_repo}[/cyan]...")
            hf_download(mlx_repo, None, console)
        else:
            console.print(f"  [yellow]No MLX repo info for {model}[/yellow]")
    elif engine in ("vllm", "sglang"):
        console.print(
            f"  [cyan]{model}[/cyan] will download automatically when "
            f"{engine} starts serving it."
        )
    else:
        console.print(f"  Download {model} through the {engine} interface.")


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
@click.option(
    "--engine",
    type=click.Choice(_SUPPORTED_ENGINES, case_sensitive=False),
    default=None,
    help="Inference engine to use (skips interactive selection).",
)
@click.option(
    "--no-download", is_flag=True, default=False, help="Skip the model download prompt."
)
@click.option(
    "--no-scan",
    "skip_scan",
    is_flag=True,
    default=False,
    help="Skip the post-init security environment audit.",
)
@click.option(
    "--host",
    default=None,
    help="Remote engine host URL (e.g. http://192.168.1.50:11434).",
)
def init(
    force: bool,
    config: Optional[Path],
    full_config: bool = False,
    engine: Optional[str] = None,
    no_download: bool = False,
    skip_scan: bool = False,
    host: Optional[str] = None,
) -> None:
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

    # Resolve engine: explicit flag > interactive selection > auto-detect
    if engine is None and config is None:
        recommended = recommend_engine(hw)
        console.print()
        console.print("[bold]Detecting running inference engines...[/bold]")
        running = _detect_running_engines()
        if running:
            console.print(f"  Found running: [green]{', '.join(running)}[/green]")
        else:
            console.print("  No running engines detected.")

        # Build choices: show running engines first, then recommended, then rest
        seen: set[str] = set()
        choices: list[str] = []
        for r in running:
            if r not in seen:
                choices.append(r)
                seen.add(r)
        if recommended not in seen:
            choices.append(recommended)
            seen.add(recommended)
        for e in _SUPPORTED_ENGINES:
            if e not in seen:
                choices.append(e)
                seen.add(e)

        # Default: first running engine, or hardware recommendation
        default = running[0] if running else recommended

        labels = []
        for c in choices:
            parts = [c]
            if c in running:
                parts.append("running")
            if c == recommended:
                parts.append("recommended")
            labels.append(
                f"  {c}" + (f"  ({', '.join(parts[1:])})" if len(parts) > 1 else "")
            )

        console.print()
        console.print("[bold]Available engines:[/bold]")
        for label in labels:
            console.print(label)

        engine = click.prompt(
            "\nSelect inference engine",
            type=click.Choice(choices, case_sensitive=False),
            default=default,
        )

    # Probe remote host if specified
    if host:
        console.print("\n[bold]Checking remote host...[/bold]")
        try:
            resp = httpx.get(host.rstrip("/") + "/", timeout=2.0)
            if resp.status_code < 500:
                console.print(f"  [green]Reachable[/green] ({host})")
            else:
                console.print(
                    f"  [yellow]Warning:[/yellow] Host returned status "
                    f"{resp.status_code} — writing config anyway."
                )
        except Exception:
            console.print(
                f"  [yellow]Warning:[/yellow] Host unreachable ({host}) "
                f"— writing config anyway."
            )

    if config:
        toml_content = config.read_text()
    else:
        if full_config:
            toml_content = generate_default_toml(hw, engine=engine, host=host)
        else:
            toml_content = generate_minimal_toml(hw, engine=engine, host=host)

    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if config:
        config.write_text(toml_content)
    else:
        DEFAULT_CONFIG_PATH.write_text(toml_content)

    console.print()
    console.print(
        Panel(
            escape(toml_content),
            title=str(DEFAULT_CONFIG_PATH),
            border_style="green",
        )
    )
    console.print("[green]Config written successfully.[/green]")

    # Create default memory files (skip if they already exist)
    soul_path = DEFAULT_CONFIG_DIR / "SOUL.md"
    if not soul_path.exists():
        soul_path.write_text(
            "# Agent Persona\n\nYou are Jarvis, a helpful personal AI assistant.\n"
        )

    memory_path = DEFAULT_CONFIG_DIR / "MEMORY.md"
    if not memory_path.exists():
        memory_path.write_text("# Agent Memory\n\n")

    user_path = DEFAULT_CONFIG_DIR / "USER.md"
    if not user_path.exists():
        user_path.write_text("# User Profile\n\n")

    skills_dir = DEFAULT_CONFIG_DIR / "skills"
    skills_dir.mkdir(exist_ok=True)

    selected_engine = engine or recommend_engine(hw)
    model = recommend_model(hw, selected_engine)

    if not model:
        console.print(
            "\n  [yellow]! Not enough memory to run any local model.[/yellow]\n"
            "  Consider a cloud engine or a machine with more RAM."
        )
    else:
        spec = find_model_spec(model)
        size_gb = estimated_download_gb(spec.parameter_count_b) if spec else 0
        console.print(
            f"\n  [bold]Recommended model:[/bold] {model} (~{size_gb:.1f} GB estimated)"
        )

        if not no_download and spec:
            prompt = f"  Download {model} (~{size_gb:.1f} GB estimated) now?"
            if click.confirm(prompt, default=True):
                _do_download(selected_engine, model, spec, console)

    if not skip_scan:
        _quick_privacy_check(console)
    console.print()
    console.print(
        Panel(
            _next_steps_text(selected_engine, model),
            title="Getting Started",
            border_style="cyan",
        )
    )
