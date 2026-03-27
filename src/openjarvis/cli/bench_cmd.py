"""``jarvis bench`` — run inference benchmarks."""

from __future__ import annotations

import json as json_mod
import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from openjarvis.core.config import load_config

if TYPE_CHECKING:
    from openjarvis.bench._stubs import BenchmarkResult
from openjarvis.engine import get_engine

logger = logging.getLogger(__name__)

_BANNER = r"""
  ___                       _                  _
 / _ \ _ __   ___ _ __     | | __ _ _ ____   _(_)___
| | | | '_ \ / _ \ '_ \ _  | |/ _` | '__\ \ / / / __|
| |_| | |_) |  __/ | | | |_| | (_| | |   \ V /| \__ \
 \___/| .__/ \___|_| |_|\___/ \__,_|_|    \_/ |_|___/
      |_|
"""


def _print_banner(console: Console) -> None:
    panel = Panel(
        _BANNER.rstrip(),
        border_style="cyan",
        title="[bold white]v1.8[/bold white]",
        expand=False,
    )
    console.print(panel)


def _section(console: Console, title: str) -> None:
    console.print(Rule(title, style="bright_blue"))


# -- Stats-aware rendering ----------------------------------------------------

_STATS_PREFIXES = {"mean_", "p50_", "p95_", "min_", "max_", "std_"}


def _detect_stat_groups(metrics: dict[str, float]) -> dict[str, dict[str, float]]:
    """Detect metrics following the stats pattern (mean_X, p50_X, ...).

    Returns ``{metric_base: {prefix: value}}`` for grouped metrics.
    """
    groups: dict[str, dict[str, float]] = {}
    for key, val in metrics.items():
        for pfx in _STATS_PREFIXES:
            if key.startswith(pfx):
                base = key[len(pfx) :]
                groups.setdefault(base, {})[pfx.rstrip("_")] = val
                break
    return groups


def _render_stats_table(console: Console, result: BenchmarkResult) -> None:
    """Render benchmark result as a stats table when stats keys are present."""
    groups = _detect_stat_groups(result.metrics)

    consumed: set[str] = set()
    for base, prefixes in groups.items():
        for pfx in prefixes:
            consumed.add(f"{pfx}_{base}")

    # Stat groups → multi-column table (use "—" for missing stats)
    if groups:
        table = Table(
            title=(
                f"[bold]{result.benchmark_name}[/bold]"
                f"  ({result.samples} samples, {result.errors} errors)"
            ),
            show_header=True,
            header_style="bold bright_white",
            border_style="bright_blue",
            title_style="bold cyan",
        )
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Avg", justify="right")
        table.add_column("Median", justify="right")
        table.add_column("Min", justify="right")
        table.add_column("Max", justify="right")
        table.add_column("Std", justify="right")
        table.add_column("P95", justify="right")

        def _cell(v: float | None) -> str:
            return f"{v:.4f}" if v is not None else "—"

        for base, vals in sorted(groups.items()):
            table.add_row(
                base,
                _cell(vals.get("mean")),
                _cell(vals.get("p50")),
                _cell(vals.get("min")),
                _cell(vals.get("max")),
                _cell(vals.get("std")),
                _cell(vals.get("p95")),
            )
        console.print(table)

    # Remaining non-stats metrics → simple key-value table
    remaining = {k: v for k, v in result.metrics.items() if k not in consumed}
    has_energy_stats = "energy_joules" in groups
    if result.total_energy_joules > 0 and not has_energy_stats:
        remaining["total_energy_joules"] = result.total_energy_joules
    if result.energy_method and not has_energy_stats:
        remaining.setdefault("energy_method", 0.0)

    if remaining:
        kv_title = (
            f"{result.benchmark_name}  "
            f"({result.samples} samples, {result.errors} errors)"
            if not groups
            else None
        )
        kv_table = Table(
            title=kv_title,
            show_header=True,
            header_style="bold bright_white",
            border_style="bright_blue",
            title_style="bold cyan",
        )
        kv_table.add_column("Metric", style="cyan", no_wrap=True)
        kv_table.add_column("Value", justify="right", style="green")
        for k, v in remaining.items():
            if k == "energy_method":
                kv_table.add_row("Energy Method", str(result.energy_method))
            else:
                kv_table.add_row(k, f"{v:.4f}")
        console.print(kv_table)


@click.group()
def bench() -> None:
    """Run inference benchmarks."""


@bench.command()
@click.option("-m", "--model", "model_name", default=None, help="Model to benchmark.")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option(
    "-n",
    "--samples",
    "num_samples",
    default=10,
    type=int,
    help="Number of samples per benchmark.",
)
@click.option(
    "-b",
    "--benchmark",
    "benchmark_name",
    default=None,
    help="Specific benchmark to run (default: all).",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    default=None,
    type=click.Path(),
    help="Write JSONL results to file.",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output JSON summary to stdout.",
)
@click.option(
    "-w",
    "--warmup",
    "warmup",
    default=0,
    type=int,
    help="Number of warmup iterations before measurement.",
)
@click.option(
    "--setup-energy",
    "setup_energy",
    is_flag=True,
    help="Run energy monitor setup script when missing (for energy benchmark).",
)
def run(
    model_name: str | None,
    engine_key: str | None,
    num_samples: int,
    benchmark_name: str | None,
    output_path: str | None,
    output_json: bool,
    warmup: int,
    setup_energy: bool,
) -> None:
    """Run benchmarks against an inference engine."""
    console = Console(stderr=True)
    config = load_config()

    # Import and register benchmarks
    from openjarvis.bench import ensure_registered
    from openjarvis.bench._stubs import BenchmarkSuite
    from openjarvis.core.registry import BenchmarkRegistry

    ensure_registered()

    # Get engine
    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print("[red bold]No inference engine available.[/red bold]")
        sys.exit(1)

    engine_name, engine = resolved

    # Resolve model
    if model_name is None:
        models = engine.list_models()
        if models:
            model_name = models[0]
        else:
            console.print("[red]No model available on engine.[/red]")
            sys.exit(1)

    # Select benchmarks
    if benchmark_name:
        if not BenchmarkRegistry.contains(benchmark_name):
            console.print(
                f"[red]Unknown benchmark: {benchmark_name}. "
                f"Available: {', '.join(BenchmarkRegistry.keys())}[/red]"
            )
            sys.exit(1)
        bench_cls = BenchmarkRegistry.get(benchmark_name)
        benchmarks = [bench_cls()]
    else:
        benchmarks = [cls() for _, cls in BenchmarkRegistry.items()]

    if not benchmarks:
        console.print("[yellow]No benchmarks registered.[/yellow]")
        return

    suite = BenchmarkSuite(benchmarks)

    # Create energy monitor when running energy benchmark or when gpu_metrics enabled
    needs_energy = any(b.name == "energy" for b in benchmarks)
    energy_monitor = None
    if config.telemetry.gpu_metrics or needs_energy:
        try:
            from openjarvis.telemetry.energy_monitor import create_energy_monitor

            energy_monitor = create_energy_monitor(
                prefer_vendor=config.telemetry.energy_vendor or None,
            )
        except Exception as exc:
            logger.debug("Energy monitor init skipped: %s", exc)

    # If energy benchmark needs monitor but none available, offer setup
    if needs_energy and energy_monitor is None:
        import platform

        setup_script = (
            Path(__file__).resolve().parents[3] / "scripts" / "setup-energy-monitor.sh"
        )
        is_darwin_arm = platform.system() == "Darwin" and platform.machine() == "arm64"
        extra_hint = (
            "openjarvis[energy-apple]"
            if is_darwin_arm
            else "openjarvis[gpu-metrics]"
            if platform.system() == "Linux"
            else "openjarvis[energy-all]"
        )
        extra_name = extra_hint.split("[")[1].rstrip("]")
        msg = (
            "[yellow]Energy monitor not available"
            " — energy metrics will be zero.[/yellow]\n"
            f"  Install: [bold]uv sync "
            f"--extra {extra_name}[/bold]\n"
        )
        if setup_energy and setup_script.exists():
            console.print("[cyan]Running energy monitor setup...[/cyan]")
            try:
                subprocess.run(
                    [str(setup_script)],
                    cwd=setup_script.parent.parent,
                    check=True,
                )
                from openjarvis.telemetry.energy_monitor import create_energy_monitor

                energy_monitor = create_energy_monitor(
                    prefer_vendor=config.telemetry.energy_vendor or None,
                )
                if energy_monitor is not None:
                    console.print("[green]Energy monitor installed.[/green]")
            except (subprocess.CalledProcessError, Exception) as exc:
                console.print(f"[red]Setup failed: {exc}[/red]")
                console.print(msg)
        else:
            console.print(msg)

    # Banner + configuration
    _print_banner(console)
    _section(console, "Configuration")
    bench_names = [b.name for b in benchmarks]
    config_panel = Panel(
        f"[cyan]Engine:[/cyan]     {engine_name}\n"
        f"[cyan]Model:[/cyan]      {model_name}\n"
        f"[cyan]Benchmarks:[/cyan] {', '.join(bench_names)}\n"
        f"[cyan]Samples:[/cyan]    {num_samples}\n"
        f"[cyan]Warmup:[/cyan]     {warmup}",
        title="[bold]Run Configuration[/bold]",
        border_style="blue",
        expand=False,
    )
    console.print(config_panel)

    # Run benchmarks
    _section(console, "Execution")
    with console.status(
        f"[bold cyan]Running {len(benchmarks)} benchmark(s)...[/bold cyan]",
    ):
        results = suite.run_all(
            engine,
            model_name,
            num_samples=num_samples,
            warmup_samples=warmup,
            energy_monitor=energy_monitor,
        )

    # Output results
    if output_path:
        jsonl = suite.to_jsonl(results)
        with open(output_path, "w") as fh:
            fh.write(jsonl + "\n")
        console.print(f"[green]Results written to {output_path}[/green]")

    if output_json:
        summary = suite.summary(results)
        click.echo(json_mod.dumps(summary, indent=2))
    elif not output_path:
        # Pretty-print results as Rich tables
        _section(console, "Results")
        for r in results:
            _render_stats_table(console, r)

    # Cleanup energy monitor
    if energy_monitor is not None:
        try:
            energy_monitor.close()
        except Exception as exc:
            logger.debug("Energy monitor cleanup failed: %s", exc)
