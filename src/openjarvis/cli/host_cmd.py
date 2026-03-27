"""``jarvis host`` — download and serve a model locally with auto backend setup."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

_BACKENDS = {
    "mlx": {
        "display": "MLX (Apple Silicon)",
        "package": "mlx-lm",
        "import_check": "mlx_lm",
        "pip_spec": "mlx-lm>=0.19",
        "uv_extra": "inference-mlx",
        "platform": "darwin",
        "default_port": 8080,
    },
    "vllm": {
        "display": "vLLM (NVIDIA GPU)",
        "package": "vllm",
        "import_check": "vllm",
        "pip_spec": "vllm>=0.17.1",
        "uv_extra": None,
        "platform": "linux",
        "default_port": 8000,
    },
    "sglang": {
        "display": "SGLang (NVIDIA GPU)",
        "package": "sglang",
        "import_check": "sglang",
        "pip_spec": "sglang[all]",
        "uv_extra": None,
        "platform": None,
        "default_port": 30000,
    },
    "ollama": {
        "display": "Ollama",
        "package": "ollama",
        "import_check": None,
        "pip_spec": None,
        "uv_extra": None,
        "platform": None,
        "default_port": 11434,
        "binary": "ollama",
    },
    "llamacpp": {
        "display": "llama.cpp",
        "package": "llama.cpp",
        "import_check": None,
        "pip_spec": None,
        "uv_extra": None,
        "platform": None,
        "default_port": 8080,
        "binary": "llama-server",
    },
    "exo": {
        "display": "Exo (Distributed)",
        "package": "exo",
        "import_check": None,
        "pip_spec": None,
        "uv_extra": None,
        "platform": None,
        "default_port": 52415,
        "binary": "exo",
    },
    "uzu": {
        "display": "Uzu",
        "package": "uzu",
        "import_check": None,
        "pip_spec": None,
        "uv_extra": None,
        "platform": None,
        "default_port": 8000,
        "binary": "uzu",
    },
}


def _is_package_available(backend: str) -> bool:
    """Check whether the backend's Python package or binary is importable/available."""
    info = _BACKENDS[backend]

    if info.get("import_check"):
        try:
            __import__(info["import_check"])
            return True
        except ImportError:
            return False

    binary = info.get("binary")
    if binary:
        return shutil.which(binary) is not None

    return False


def _detect_backend() -> str | None:
    """Auto-detect the best backend for the current platform."""
    import platform

    system = platform.system().lower()

    if system == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
            )
            if "Apple" in result.stdout:
                return "mlx"
        except FileNotFoundError:
            pass
        return "ollama"

    if system == "linux":
        if shutil.which("nvidia-smi"):
            return "vllm"
        return "ollama"

    return "ollama"


def _install_backend(backend: str, console: Console) -> bool:
    """Prompt the user and install the backend package. Returns True on success."""
    info = _BACKENDS[backend]
    display = info["display"]

    console.print()
    console.print(f"[yellow]Backend [bold]{display}[/bold] is not installed.[/yellow]")

    uv_available = shutil.which("uv") is not None
    in_uv_project = os.path.exists("pyproject.toml") and os.path.exists("uv.lock")

    if info.get("binary") and not info.get("pip_spec"):
        return _install_binary_backend(backend, console)

    pip_spec = info["pip_spec"]
    uv_extra = info.get("uv_extra")
    packages = pip_spec.split()

    if uv_available and in_uv_project and uv_extra:
        install_cmd = ["uv", "pip", "install"] + packages
        install_label = f"uv pip install {pip_spec}"
    elif uv_available:
        install_cmd = ["uv", "pip", "install"] + packages
        install_label = f"uv pip install {pip_spec}"
    else:
        install_cmd = [sys.executable, "-m", "pip", "install"] + packages
        install_label = f"pip install {pip_spec}"

    console.print(f"\n  Install command: [cyan]{install_label}[/cyan]\n")
    if not click.confirm("Install now?", default=True):
        console.print("[dim]Skipped. Install manually and retry.[/dim]")
        return False

    console.print(f"[bold]Running:[/bold] {install_label}")
    result = subprocess.run(install_cmd)
    if result.returncode != 0:
        console.print(f"[red]Installation failed (exit {result.returncode}).[/red]")
        return False

    console.print(f"[green]{display} installed successfully.[/green]\n")
    return True


def _install_binary_backend(backend: str, console: Console) -> bool:
    """Guide the user through installing a binary backend (Ollama, llama.cpp)."""
    info = _BACKENDS[backend]
    binary = info["binary"]

    instructions = {
        "ollama": (
            "Install Ollama:\n"
            "\n"
            "  macOS / Linux:\n"
            "    curl -fsSL https://ollama.com/install.sh | sh\n"
            "\n"
            "  Or download from: https://ollama.com/download"
        ),
        "llamacpp": (
            "Install llama.cpp:\n"
            "\n"
            "  macOS:\n"
            "    brew install llama.cpp\n"
            "\n"
            "  From source:\n"
            "    https://github.com/ggerganov/llama.cpp"
        ),
        "exo": (
            "Install Exo:\n"
            "\n"
            "  pip install exo\n"
            "\n"
            "  Or from source:\n"
            "    https://github.com/exo-explore/exo"
        ),
        "uzu": ("Install Uzu:\n\n  See https://uzu.ai for installation instructions."),
    }

    console.print()
    console.print(
        Panel(
            instructions.get(
                backend,
                f"Install {binary} and ensure it's on PATH.",
            ),
            title=f"{info['display']} Installation",
            border_style="yellow",
        )
    )

    if backend == "ollama":
        import platform

        system = platform.system().lower()
        if system in ("linux", "darwin"):
            if click.confirm("Run the Ollama install script now?", default=True):
                console.print("[bold]Running Ollama installer...[/bold]")
                result = subprocess.run(
                    ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                )
                if result.returncode == 0 and shutil.which("ollama"):
                    console.print("[green]Ollama installed successfully.[/green]\n")
                    return True
                console.print(
                    "[red]Installation may have failed. Check above for errors.[/red]"
                )
                return False

    console.print("[dim]Install manually and retry.[/dim]")
    return False


def _build_serve_command(backend: str, model: str, port: int) -> list[str]:
    """Build the subprocess command list to start the inference server."""
    if backend == "mlx":
        return [
            sys.executable,
            "-m",
            "mlx_lm.server",
            "--model",
            model,
            "--port",
            str(port),
        ]

    if backend == "vllm":
        return ["vllm", "serve", model, "--port", str(port)]

    if backend == "sglang":
        return [
            sys.executable,
            "-m",
            "sglang.launch_server",
            "--model-path",
            model,
            "--port",
            str(port),
        ]

    if backend == "ollama":
        return ["ollama", "run", model]

    if backend == "llamacpp":
        return ["llama-server", "-m", model, "--port", str(port)]

    if backend == "exo":
        return ["exo", "--port", str(port)]

    if backend == "uzu":
        return ["uzu", "serve", "--port", str(port)]

    raise ValueError(f"Unknown backend: {backend}")


@click.command()
@click.argument("model")
@click.option(
    "-b",
    "--backend",
    type=click.Choice(list(_BACKENDS.keys()), case_sensitive=False),
    default=None,
    help="Inference backend to use. Auto-detected if omitted.",
)
@click.option(
    "-p",
    "--port",
    type=int,
    default=None,
    help="Port to serve on (default depends on backend).",
)
@click.option(
    "--trust-remote-code",
    is_flag=True,
    default=False,
    help="Pass --trust-remote-code to the backend.",
)
def host(
    model: str,
    backend: Optional[str],
    port: Optional[int],
    trust_remote_code: bool,
) -> None:
    """Download (if needed) and serve a model locally.

    Examples:

    \b
      jarvis host mlx-community/Qwen2.5-7B-4bit --backend mlx
      jarvis host Qwen/Qwen3-8B --backend vllm
      jarvis host qwen3:8b --backend ollama
      jarvis host meta-llama/Llama-3-8B -b sglang
    """
    console = Console()

    if backend is None:
        detected = _detect_backend()
        if detected is None:
            console.print("[red]Could not auto-detect a suitable backend.[/red]")
            console.print("Specify one with [cyan]--backend[/cyan].")
            raise SystemExit(1)
        backend = detected
        name = _BACKENDS[backend]["display"]
        console.print(f"Auto-detected backend: [bold cyan]{name}[/bold cyan]")

    info = _BACKENDS[backend]

    if not _is_package_available(backend):
        if not _install_backend(backend, console):
            raise SystemExit(1)
        if not _is_package_available(backend):
            console.print(
                f"[red]{info['display']} still not available after install.[/red]"
            )
            console.print(
                "You may need to restart your shell or "
                "activate the correct environment."
            )
            raise SystemExit(1)

    serve_port = port or info["default_port"]
    cmd = _build_serve_command(backend, model, serve_port)

    if trust_remote_code:
        if backend in ("vllm", "sglang"):
            cmd.append("--trust-remote-code")
        elif backend == "mlx":
            cmd.extend(["--trust-remote-code", "True"])

    host_url = f"http://localhost:{serve_port}"

    table = Table.grid(padding=(0, 2))
    table.add_row("[bold]Backend:[/bold]", info["display"])
    table.add_row("[bold]Model:[/bold]", model)
    table.add_row("[bold]Endpoint:[/bold]", host_url)
    table.add_row("[bold]Command:[/bold]", " ".join(cmd))

    console.print()
    console.print(Panel(table, title="Hosting Model", border_style="green"))
    console.print()

    if backend != "ollama":
        console.print(f"[dim]The model server will be available at {host_url}[/dim]")
        console.print(
            "[dim]OpenJarvis will auto-discover it. Press Ctrl+C to stop.[/dim]\n"
        )

    try:
        proc = subprocess.Popen(cmd)
        proc.wait()
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down model server...[/yellow]")
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        console.print("[green]Server stopped.[/green]")
    except FileNotFoundError:
        console.print(f"[red]Command not found:[/red] {cmd[0]}")
        console.print(f"Make sure {info['display']} is installed and on your PATH.")
        raise SystemExit(1)
