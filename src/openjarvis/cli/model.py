"""``jarvis model`` — model management subcommands."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from openjarvis.core.config import DEFAULT_CONFIG_DIR, load_config
from openjarvis.core.registry import ModelRegistry
from openjarvis.engine import discover_engines, discover_models
from openjarvis.intelligence import merge_discovered_models, register_builtin_models
from openjarvis.intelligence.model_catalog import BUILTIN_MODELS


@click.group()
def model() -> None:
    """Manage language models."""


@model.command("list")
def list_models() -> None:
    """List available models from running engines."""
    console = Console()
    config = load_config()
    register_builtin_models()

    engines = discover_engines(config)
    if not engines:
        console.print(
            "[yellow]No inference engines detected.[/yellow]\n"
            "Start an engine (e.g. [cyan]ollama serve[/cyan]) and try again."
        )
        return

    all_models = discover_models(engines)
    for ek, model_ids in all_models.items():
        merge_discovered_models(ek, model_ids)

    table = Table(title="Available Models")
    table.add_column("Engine", style="cyan")
    table.add_column("Model", style="green")
    table.add_column("Params", justify="right")
    table.add_column("Active", justify="right")
    table.add_column("Context", justify="right")
    table.add_column("VRAM", justify="right")
    table.add_column("Arch", style="dim")

    for engine_key, model_ids in all_models.items():
        for mid in model_ids:
            try:
                spec = ModelRegistry.get(mid)
                params = f"{spec.parameter_count_b}B" if spec.parameter_count_b else "-"
                active = (
                    f"{spec.active_parameter_count_b}B"
                    if spec.active_parameter_count_b
                    else "-"
                )
                ctx = f"{spec.context_length:,}" if spec.context_length else "-"
                vram = f"{spec.min_vram_gb}GB" if spec.min_vram_gb else "-"
                arch = spec.metadata.get("architecture", "-")
            except KeyError:
                params = "-"
                active = "-"
                ctx = "-"
                vram = "-"
                arch = "-"
            table.add_row(engine_key, mid, params, active, ctx, vram, arch)

    console.print(table)


@model.command()
@click.argument("model_name")
def info(model_name: str) -> None:
    """Show details for a model."""
    console = Console()
    register_builtin_models()

    # Also try discovering from running engines
    config = load_config()
    engines = discover_engines(config)
    all_models = discover_models(engines)
    for ek, model_ids in all_models.items():
        merge_discovered_models(ek, model_ids)

    if not ModelRegistry.contains(model_name):
        console.print(f"[red]Model not found:[/red] {model_name}")
        sys.exit(1)

    spec = ModelRegistry.get(model_name)
    params = f"{spec.parameter_count_b}B" if spec.parameter_count_b else "unknown"
    active = (
        f"{spec.active_parameter_count_b}B" if spec.active_parameter_count_b else "-"
    )
    ctx_len = f"{spec.context_length:,}" if spec.context_length else "unknown"
    vram = f"{spec.min_vram_gb}GB" if spec.min_vram_gb else "-"
    engines_str = ", ".join(spec.supported_engines) if spec.supported_engines else "-"
    provider = spec.provider or "-"
    api_key = "required" if spec.requires_api_key else "not required"
    lines = [
        f"[bold]Model ID:[/bold]       {spec.model_id}",
        f"[bold]Name:[/bold]           {spec.name}",
        f"[bold]Parameters:[/bold]     {params}",
        f"[bold]Active Params:[/bold]  {active}",
        f"[bold]Context:[/bold]        {ctx_len}",
        f"[bold]Quantization:[/bold]   {spec.quantization.value}",
        f"[bold]Min VRAM:[/bold]       {vram}",
        f"[bold]Engines:[/bold]        {engines_str}",
        f"[bold]Provider:[/bold]       {provider}",
        f"[bold]API Key:[/bold]        {api_key}",
    ]

    # Append metadata fields with well-known labels
    meta_labels = {
        "architecture": "Architecture",
        "hf_repo": "HuggingFace",
        "url": "More Info",
        "teacher": "Teacher Model",
        "quantization": "Quant Format",
        "license": "License",
        "pricing_input": "Price (input)",
        "pricing_output": "Price (output)",
    }
    for key, label in meta_labels.items():
        value = spec.metadata.get(key)
        if value is not None:
            if key.startswith("pricing_"):
                value = f"${value}/M tokens"
            elif key == "hf_repo":
                value = f"https://huggingface.co/{value}"
            pad = " " * max(1, 14 - len(label))
            lines.append(f"[bold]{label}:[/bold]{pad}{value}")

    # Any remaining metadata not covered above
    extra_keys = set(spec.metadata) - set(meta_labels)
    for key in sorted(extra_keys):
        pad = " " * max(1, 14 - len(key))
        lines.append(f"[bold]{key}:[/bold]{pad}{spec.metadata[key]}")

    console.print(Panel("\n".join(lines), title=spec.name, border_style="blue"))


def ollama_pull(host: str, model_name: str, console: Console) -> bool:
    """Pull a model via Ollama API. Returns True on success."""
    console.print(f"Pulling [cyan]{model_name}[/cyan] via Ollama...")
    try:
        with httpx.stream(
            "POST",
            f"{host}/api/pull",
            json={"name": model_name, "stream": True},
            timeout=600.0,
        ) as resp:
            resp.raise_for_status()
            import json

            for line in resp.iter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                status = data.get("status", "")
                if "total" in data and "completed" in data:
                    total = data["total"]
                    done = data["completed"]
                    pct = int(done / total * 100) if total else 0
                    console.print(f"  {status}: {pct}%", end="\r")
                elif status:
                    console.print(f"  {status}")
        console.print(f"\n[green]Successfully pulled {model_name}[/green]")
        return True
    except httpx.ConnectError:
        console.print("[red]Cannot connect to Ollama.[/red] Is it running?")
        return False
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Ollama error:[/red] {exc.response.status_code}")
        return False


def find_model_spec(model_name: str):
    """Look up a model in the builtin catalog. Returns None if not found."""
    for spec in BUILTIN_MODELS:
        if spec.model_id == model_name:
            return spec
    return None


def hf_download(repo: str, filename: str | None, console: Console) -> bool:
    """Download from HuggingFace via huggingface-cli. Returns True on success."""
    cmd = ["huggingface-cli", "download", repo]
    if filename:
        cmd.append(filename)
    try:
        subprocess.run(cmd, check=True)
        console.print("[green]Download complete.[/green]")
        return True
    except FileNotFoundError:
        console.print(
            "[red]huggingface-cli not found.[/red]\n"
            "Install it: [cyan]pip install huggingface_hub[/cyan]\n"
            f"Or download manually: https://huggingface.co/{repo}"
        )
        return False
    except subprocess.CalledProcessError:
        console.print("[red]Download failed.[/red]")
        return False


@model.command()
@click.argument("model_name")
@click.option("--engine", default=None, help="Engine to download for.")
def pull(model_name: str, engine: str | None) -> None:
    """Download a model."""
    console = Console()
    config = load_config()
    engine = engine or config.engine.default or "ollama"

    if engine == "ollama":
        host = (
            config.engine.ollama_host
            or os.environ.get("OLLAMA_HOST")
            or "http://localhost:11434"
        ).rstrip("/")
        if not ollama_pull(host, model_name, console):
            sys.exit(1)
    elif engine in ("llamacpp", "mlx"):
        spec = find_model_spec(model_name)
        if not spec:
            console.print(f"[red]Model not in catalog:[/red] {model_name}")
            sys.exit(1)
        if engine == "llamacpp":
            repo = spec.metadata.get("hf_repo", "")
            gguf = spec.metadata.get("gguf_file", "")
            if not repo or not gguf:
                console.print(f"[red]No GGUF download info for {model_name}[/red]")
                sys.exit(1)
            console.print(f"Downloading [cyan]{gguf}[/cyan] from {repo}...")
            if not hf_download(repo, gguf, console):
                sys.exit(1)
        else:  # mlx
            mlx_repo = spec.metadata.get("mlx_repo", "")
            if not mlx_repo:
                console.print(f"[red]No MLX repo info for {model_name}[/red]")
                sys.exit(1)
            console.print(f"Downloading [cyan]{mlx_repo}[/cyan]...")
            if not hf_download(mlx_repo, None, console):
                sys.exit(1)
    elif engine in ("vllm", "sglang"):
        console.print(
            f"[cyan]{model_name}[/cyan] will download automatically when "
            f"{engine} starts serving it."
        )
    else:
        console.print(
            f"Manual download required for engine [cyan]{engine}[/cyan].\n"
            f"Check the engine documentation for instructions."
        )


def _slug_from_repo(
    hf_repo: str, engine: str, quantize: str | None, mlx_4bit: bool
) -> str:
    """Generate output directory slug from HF repo and conversion params."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", hf_repo.replace("/", "--"))
    base = base.strip("._-") or "model"
    if engine == "mlx":
        return f"{base}-mlx-4bit" if mlx_4bit else f"{base}-mlx"
    elif engine == "llamacpp":
        if quantize:
            return f"{base}-{quantize}"
        return f"{base}-gguf"
    return base


def _download_snapshot(hf_repo: str, console: Console) -> str | None:
    """Download *hf_repo* and return the concrete local snapshot directory."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        console.print(
            "[red]Model conversion needs huggingface_hub.[/red]\n"
            "Install it: [cyan]pip install huggingface_hub[/cyan]"
        )
        return None

    try:
        console.print(f"Downloading [cyan]{hf_repo}[/cyan]...")
        return str(snapshot_download(repo_id=hf_repo))
    except Exception as exc:
        console.print(f"[red]Hugging Face download failed:[/red] {exc}")
        return None


def _convert_mlx(hf_repo: str, output: str, mlx_4bit: bool, console: Console) -> bool:
    """Convert an HF model to MLX format. Returns True on success."""
    try:
        import mlx_lm
    except ImportError:
        console.print(
            "[red]MLX conversion needs the inference-mlx extra.[/red]\n"
            'Install it: [cyan]pip install "openjarvis[inference-mlx]"[/cyan]'
        )
        return False

    snapshot = _download_snapshot(hf_repo, console)
    if snapshot is None:
        return False

    try:
        # mlx_lm.convert deliberately refuses an existing output path. The
        # command gives it a fresh staging destination and only publishes that
        # directory after conversion succeeds.
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        console.print(
            f"Converting [cyan]{hf_repo}[/cyan] to MLX at [cyan]{output}[/cyan]..."
        )
        mlx_lm.convert(hf_path=snapshot, mlx_path=output, quantize=mlx_4bit)
        if not Path(output).is_dir() or not any(Path(output).iterdir()):
            raise RuntimeError("converter completed without producing an artifact")
        console.print(f"[green]Converted → {output}[/green]")
        return True
    except Exception as exc:
        console.print(f"[red]MLX conversion failed:[/red] {exc}")
        return False


def _convert_gguf(
    hf_repo: str,
    output: str,
    quantize: str | None,
    console: Console,
    config: object | None = None,
) -> str | None:
    """Convert an HF model to GGUF and return the final artifact path."""
    snapshot = _download_snapshot(hf_repo, console)
    if snapshot is None:
        return None

    # Step 2: locate and run convert_hf_to_gguf.py
    convert_script = _locate_convert_script(console, config)
    if not convert_script:
        return None

    # Determine output file path
    os.makedirs(output, exist_ok=True)
    artifact_stem = _slug_from_repo(hf_repo, "", None, False)
    output_gguf = os.path.join(output, f"{artifact_stem}.f16.gguf")

    console.print(f"Converting to [cyan]{output_gguf}[/cyan]...")
    try:
        subprocess.run(
            [
                sys.executable,
                convert_script,
                snapshot,
                "--outtype",
                "f16",
                "--outfile",
                output_gguf,
            ],
            check=True,
        )
        if not os.path.isfile(output_gguf):
            raise RuntimeError("converter completed without producing a GGUF file")
    except FileNotFoundError:
        console.print(
            "[red]convert_hf_to_gguf.py not found.[/red]\n"
            "Install llama.cpp and set [cyan]$LLAMACPP_PATH[/cyan] to the repo "
            "root, or configure [cyan]engine.llamacpp.binary_path[/cyan]."
        )
        return None
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        if isinstance(exc, RuntimeError):
            console.print(f"[red]Conversion to GGUF failed:[/red] {exc}")
            return None
        console.print("[red]Conversion to GGUF failed.[/red]")
        return None

    # Step 3: optional quantization
    if quantize:
        console.print(f"Quantizing to [cyan]{quantize}[/cyan]...")
        quant_script = _locate_quantize_script(console, config)
        if not quant_script:
            return None

        quantized_out = os.path.join(output, f"{artifact_stem}.{quantize}.gguf")
        try:
            subprocess.run(
                [quant_script, output_gguf, quantized_out, quantize],
                check=True,
            )
            if not os.path.isfile(quantized_out):
                raise RuntimeError("quantizer completed without producing a GGUF file")
            console.print(f"[green]Quantized → {quantized_out}[/green]")
        except FileNotFoundError:
            console.print(
                "[red]llama-quantize not found.[/red]\n"
                "Install llama.cpp and set [cyan]$LLAMACPP_PATH[/cyan] to the "
                "repo root, or configure "
                "[cyan]engine.llamacpp.binary_path[/cyan]."
            )
            return None
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            if isinstance(exc, RuntimeError):
                console.print(f"[red]Quantization failed:[/red] {exc}")
                return None
            console.print("[red]Quantization failed.[/red]")
            return None
        return quantized_out
    else:
        console.print(f"[green]Converted → {output_gguf}[/green]")

    return output_gguf


def _llamacpp_search_roots(config: object | None) -> list[Path]:
    """Return deduplicated llama.cpp roots from env and engine config."""
    configured_path = ""
    try:
        configured_path = str(config.engine.llamacpp.binary_path)  # type: ignore[attr-defined]
    except AttributeError:
        pass

    raw_paths = [
        os.environ.get("LLAMACPP_PATH", ""),
        os.environ.get("LLAMA_CPP_DIR", ""),
        configured_path,
    ]
    roots: list[Path] = []
    for raw_path in raw_paths:
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        # A configured path commonly points at build/bin/llama-server. Walk a
        # few ancestors so the repository-level conversion script is found.
        if path.name.startswith("llama-") or path.name.endswith(".py"):
            path = path.parent
        for root in (path, *list(path.parents)[:4]):
            if root not in roots:
                roots.append(root)
    return roots


def _locate_convert_script(
    console: Console, config: object | None = None
) -> str | None:
    """Locate convert_hf_to_gguf.py via env, config, or PATH."""
    for llama_dir in _llamacpp_search_roots(config):
        script = llama_dir / "convert_hf_to_gguf.py"
        if script.is_file():
            return str(script)
    # Try PATH
    script = shutil.which("convert_hf_to_gguf.py")
    if script:
        return script
    console.print(
        "[red]convert_hf_to_gguf.py not found.[/red]\n"
        "Install llama.cpp and set [cyan]$LLAMACPP_PATH[/cyan] to the repo "
        "root, or configure [cyan]engine.llamacpp.binary_path[/cyan]."
    )
    return None


def _locate_quantize_script(
    console: Console, config: object | None = None
) -> str | None:
    """Locate llama-quantize via env, config, or PATH."""
    for llama_dir in _llamacpp_search_roots(config):
        # llama-quantize is typically in the main llama.cpp build directory
        for name in (
            "llama-quantize",
            "bin/llama-quantize",
            "build/bin/llama-quantize",
        ):
            script = llama_dir / name
            if script.is_file():
                return str(script)
    # Try PATH
    script = shutil.which("llama-quantize")
    if script:
        return script
    console.print(
        "[red]llama-quantize not found.[/red]\n"
        "Install llama.cpp and set [cyan]$LLAMACPP_PATH[/cyan] to the repo "
        "root, or configure [cyan]engine.llamacpp.binary_path[/cyan]."
    )
    return None


def _remove_path(path: Path) -> None:
    """Remove one file, symlink, or directory without following symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _publish_output(staged: Path, output: Path) -> None:
    """Publish a completed staging directory, restoring the old output on error."""
    output.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if os.path.lexists(output):
        backup = output.with_name(f".{output.name}.backup-{uuid.uuid4().hex}")
        os.replace(output, backup)
    try:
        os.replace(staged, output)
    except Exception:
        if backup is not None and os.path.lexists(backup):
            os.replace(backup, output)
        raise
    else:
        if backup is not None:
            _remove_path(backup)


def _import_ollama(
    gguf_path: str,
    staging_output: Path,
    model_name: str,
    console: Console,
) -> bool:
    """Import a staged GGUF into Ollama using a relocatable Modelfile."""
    artifact = Path(gguf_path)
    relative_artifact = artifact.relative_to(staging_output)
    modelfile = staging_output / "Modelfile"
    modelfile.write_text(f"FROM ./{relative_artifact.as_posix()}\n", encoding="utf-8")
    try:
        subprocess.run(
            ["ollama", "create", model_name, "-f", str(modelfile)],
            check=True,
        )
    except FileNotFoundError:
        console.print(
            "[red]ollama not found.[/red] Install Ollama and ensure the "
            "[cyan]ollama[/cyan] command is on PATH."
        )
        return False
    except subprocess.CalledProcessError:
        console.print("[red]Ollama model import failed.[/red]")
        return False
    return True


@model.command()
@click.argument("hf_repo")
@click.option("--engine", default=None, help="Engine to convert for.")
@click.option(
    "--quantize",
    default=None,
    help="GGUF quantization type (e.g., q4_k_m, q8_0).",
)
@click.option(
    "-q",
    "--mlx-4bit",
    is_flag=True,
    default=False,
    help="Enable 4-bit quantization for MLX.",
)
@click.option(
    "--output",
    default=None,
    help="Output directory for converted artifact.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Replace existing output only after conversion succeeds.",
)
def convert(
    hf_repo: str,
    engine: str | None,
    quantize: str | None,
    mlx_4bit: bool,
    output: str | None,
    force: bool,
) -> None:
    """Convert a Hugging Face model to a local engine format."""
    console = Console()
    config = load_config()

    # Resolve engine and reject combinations that would otherwise be silently
    # ignored or produce an artifact the selected runtime cannot consume.
    engine = (engine or config.engine.default or "mlx").lower()
    if engine in ("vllm", "sglang"):
        console.print(
            f"[green]No conversion needed for {engine}.[/green] It consumes "
            f"Hugging Face repositories directly.\n"
            f"[cyan]Start with:[/cyan] jarvis host {shlex.quote(hf_repo)} "
            f"--backend {engine}"
        )
        return
    if engine not in ("mlx", "llamacpp", "ollama"):
        console.print(f"[red]Unsupported conversion engine:[/red] {engine}")
        raise SystemExit(1)
    if engine == "mlx" and quantize:
        console.print("[red]--quantize is only valid for GGUF conversion.[/red]")
        raise SystemExit(1)
    if engine != "mlx" and mlx_4bit:
        console.print("[red]--mlx-4bit is only valid with --engine mlx.[/red]")
        raise SystemExit(1)
    if quantize and not re.fullmatch(r"[A-Za-z0-9_]+", quantize):
        console.print("[red]Invalid GGUF quantization name.[/red]")
        raise SystemExit(1)
    quantize = quantize.lower() if quantize else None

    # Resolve output path
    if output is None:
        slug = _slug_from_repo(hf_repo, engine, quantize, mlx_4bit)
        output = str(DEFAULT_CONFIG_DIR / "models" / slug)

    # Keep the final path absolute without resolving a user-supplied symlink:
    # --force must replace the link itself, never its target.
    output_path = Path(os.path.abspath(Path(output).expanduser()))

    # Check existing output. --force does not remove it yet: conversion happens
    # in a sibling staging directory, so failures leave the old artifact intact.
    if os.path.lexists(output_path):
        # A symlink is always an existing output object, even when it points to
        # an empty directory. Never follow it to decide whether overwriting is
        # safe; --force replaces the link itself after conversion succeeds.
        if output_path.is_symlink() and not force:
            console.print(
                f"[red]Output path exists as a symlink:[/red] {output_path}\n"
                "Use [cyan]--force[/cyan] to overwrite."
            )
            sys.exit(1)
        if output_path.is_dir() and not output_path.is_symlink():
            contents = os.listdir(output_path)
            if contents and not force:
                console.print(
                    "[red]Output directory exists and is non-empty:[/red] "
                    f"{output_path}\n"
                    "Use [cyan]--force[/cyan] to overwrite."
                )
                sys.exit(1)
        elif not force:
            console.print(
                f"[red]Output path exists as a file:[/red] {output_path}\n"
                "Use [cyan]--force[/cyan] to overwrite."
            )
            sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(
        tempfile.mkdtemp(prefix=f".{output_path.name}.convert-", dir=output_path.parent)
    )
    staged_output = temp_root / "artifact"
    artifact_relative: Path | None = None
    ollama_name: str | None = None
    try:
        if engine == "mlx":
            if not _convert_mlx(hf_repo, str(staged_output), mlx_4bit, console):
                raise SystemExit(1)
        else:
            gguf_path = _convert_gguf(
                hf_repo,
                str(staged_output),
                quantize,
                console,
                config,
            )
            if gguf_path is None:
                raise SystemExit(1)
            artifact_relative = Path(gguf_path).relative_to(staged_output)
            if engine == "ollama":
                ollama_name = _slug_from_repo(
                    hf_repo.rsplit("/", 1)[-1], "", None, False
                ).lower()
                if not _import_ollama(
                    gguf_path,
                    staged_output,
                    ollama_name,
                    console,
                ):
                    raise SystemExit(1)

        _publish_output(staged_output, output_path)
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)

    if engine == "mlx":
        artifact = output_path
        hint = f"jarvis host {shlex.quote(str(artifact))} --backend mlx"
        title = "MLX conversion complete"
    else:
        assert artifact_relative is not None
        artifact = output_path / artifact_relative
        if engine == "ollama":
            assert ollama_name is not None
            hint = f"jarvis chat --engine ollama --model {shlex.quote(ollama_name)}"
            title = "GGUF conversion and Ollama import complete"
        else:
            hint = f"jarvis host {shlex.quote(str(artifact))} --backend llamacpp"
            title = "GGUF conversion complete"
    console.print(
        Panel(
            f"[bold]Artifact:[/bold] {artifact}\n\n[cyan]Start with:[/cyan]\n  {hint}",
            title=title,
            border_style="green",
        )
    )
