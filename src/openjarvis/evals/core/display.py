"""Rich display helpers for the evaluation framework and bench CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

if TYPE_CHECKING:
    from pathlib import Path

    from openjarvis.evals.core.types import MetricStats, RunSummary

OPENJARVIS_BANNER = r"""
  ___                       _                  _
 / _ \ _ __   ___ _ __     | | __ _ _ ____   _(_)___
| | | | '_ \ / _ \ '_ \ _  | |/ _` | '__\ \ / / / __|
| |_| | |_) |  __/ | | | |_| | (_| | |   \ V /| \__ \
 \___/| .__/ \___|_| |_|\___/ \__,_|_|    \_/ |_|___/
      |_|
"""

VERSION = "v1.8"


def print_banner(console: Console) -> None:
    """Print the OpenJarvis ASCII banner inside a styled panel."""
    panel = Panel(
        OPENJARVIS_BANNER.rstrip(),
        border_style="cyan",
        title=f"[bold white]{VERSION}[/bold white]",
        expand=False,
    )
    console.print(panel)


def print_section(console: Console, title: str) -> None:
    """Print a horizontal rule section separator."""
    console.print(Rule(title, style="bright_blue"))


def print_run_header(
    console: Console,
    benchmark: str,
    model: str,
    backend: str,
    samples: Optional[int],
    workers: int,
    warmup: int = 0,
) -> None:
    """Print a compact run configuration panel."""
    lines = [
        f"[cyan]Benchmark:[/cyan]  {benchmark}",
        f"[cyan]Model:[/cyan]      {model}",
        f"[cyan]Backend:[/cyan]    {backend}",
        f"[cyan]Samples:[/cyan]    {samples if samples is not None else 'all'}",
        f"[cyan]Workers:[/cyan]    {workers}",
    ]
    if warmup > 0:
        lines.append(f"[cyan]Warmup:[/cyan]     {warmup}")
    body = "\n".join(lines)
    panel = Panel(
        body,
        title="[bold]Run Configuration[/bold]",
        border_style="blue",
        expand=False,
    )
    console.print(panel)


def _fmt(val: float, decimals: int = 4) -> str:
    """Format a float to a fixed number of decimal places."""
    return f"{val:.{decimals}f}"


def _add_metric_row(
    table: Table,
    label: str,
    stats: Optional[MetricStats],
    decimals: int = 4,
) -> None:
    """Add a row for a metric if stats exist."""
    if stats is None:
        return
    table.add_row(
        label,
        _fmt(stats.mean, decimals),
        _fmt(stats.median, decimals),
        _fmt(stats.min, decimals),
        _fmt(stats.max, decimals),
        _fmt(stats.std, decimals),
        _fmt(stats.p95, decimals),
        _fmt(stats.p99, decimals),
    )


def print_metrics_table(console: Console, summary: RunSummary) -> None:
    """Print the unified metrics table with all available stats."""
    table = Table(
        title="[bold]Task-Level Metrics[/bold]",
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
    table.add_column("P99", justify="right")

    _add_metric_row(table, "Accuracy", summary.accuracy_stats)
    _add_metric_row(table, "Latency (s)", summary.latency_stats)
    _add_metric_row(table, "TTFT (s)", summary.ttft_stats)
    _add_metric_row(table, "Input Tokens", summary.input_token_stats, decimals=1)
    _add_metric_row(table, "Output Tokens", summary.output_token_stats, decimals=1)
    _add_metric_row(table, "Throughput (tok/s)", summary.throughput_stats)
    _add_metric_row(table, "Energy (J)", summary.energy_stats)
    _add_metric_row(table, "Power (W)", summary.power_stats)
    _add_metric_row(table, "GPU Util (%)", summary.gpu_utilization_stats, decimals=1)
    _add_metric_row(
        table,
        "Energy/OutTok (J)",
        summary.energy_per_output_token_stats,
        decimals=6,
    )
    _add_metric_row(table, "Throughput/Watt", summary.throughput_per_watt_stats)
    _add_metric_row(table, "MFU (%)", summary.mfu_stats, decimals=2)
    _add_metric_row(table, "MBU (%)", summary.mbu_stats, decimals=2)
    _add_metric_row(table, "IPW", summary.ipw_stats)
    _add_metric_row(table, "IPJ", summary.ipj_stats)
    _add_metric_row(table, "Mean ITL (ms)", summary.itl_stats, decimals=2)

    if table.row_count > 0:
        console.print(table)

    # Headline stats below the table
    headline = (
        f"[bold]Accuracy:[/bold] {summary.accuracy:.4f}  "
        f"({summary.correct}/{summary.scored_samples} scored)  "
        f"[bold]Mean Latency:[/bold] {summary.mean_latency_seconds:.2f}s  "
        f"[bold]Cost:[/bold] ${summary.total_cost_usd:.4f}"
    )
    if summary.total_energy_joules > 0:
        headline += f"  [bold]Total Energy:[/bold] {summary.total_energy_joules:.4f}J"
    if summary.warmup_samples_excluded > 0:
        headline += f"  [dim](warmup: {summary.warmup_samples_excluded} excluded)[/dim]"
    console.print(headline)

    # MBU row from agentic trace metrics
    if summary.mbu_stats is not None:
        console.print(
            f"  [bold]MBU:[/bold] avg={summary.mbu_stats.mean:.2f}%"
            f"  max={summary.mbu_stats.max:.2f}%"
        )


def _stats_table(
    title: str,
    rows: list[tuple[str, Optional[MetricStats], int]],
) -> Table:
    """Build a stats table with Avg/Median/Min/Max/Std columns."""
    table = Table(
        title=f"[bold]{title}[/bold]",
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
    for label, stats, decimals in rows:
        if stats is not None:
            table.add_row(
                label,
                _fmt(stats.mean, decimals),
                _fmt(stats.median, decimals),
                _fmt(stats.min, decimals),
                _fmt(stats.max, decimals),
                _fmt(stats.std, decimals),
            )
    return table


def print_accuracy_panel(console: Console, summary: RunSummary) -> None:
    """Print accuracy panel with per-subject breakdown."""
    lines = [
        f"[bold]Overall Accuracy    {summary.accuracy:.1%}[/bold]"
        f"  ({summary.correct}/{summary.scored_samples})",
    ]
    for subj, stats in sorted(summary.per_subject.items()):
        acc = stats.get("accuracy", 0.0)
        correct = int(stats.get("correct", 0))
        scored = int(stats.get("scored", 0))
        lines.append(f"  {subj:<20s} {acc:.1%}  ({correct}/{scored})")
    body = "\n".join(lines)
    panel = Panel(
        body,
        title="[bold]Accuracy[/bold]",
        border_style="green",
        expand=False,
    )
    console.print(panel)


def print_latency_table(console: Console, summary: RunSummary) -> None:
    """Print latency, throughput, and token stats table."""
    table = _stats_table(
        "Latency & Throughput",
        [
            ("Latency (s)", summary.latency_stats, 2),
            ("TTFT (s)", summary.ttft_stats, 3),
            ("Throughput (tok/s)", summary.throughput_stats, 1),
            ("Avg Input Tokens", summary.input_token_stats, 1),
            ("Avg Output Tokens", summary.output_token_stats, 1),
        ],
    )
    if table.row_count > 0:
        console.print(table)


def print_energy_table(console: Console, summary: RunSummary) -> None:
    """Print energy, efficiency, and IPJ/IPW table."""
    table = _stats_table(
        "Energy & Efficiency",
        [
            ("Energy (J)", summary.energy_stats, 1),
            ("Power (W)", summary.power_stats, 1),
            ("GPU Util (%)", summary.gpu_utilization_stats, 1),
            ("Energy/OutTok (J)", summary.energy_per_output_token_stats, 6),
            ("MFU (%)", summary.mfu_stats, 3),
            ("MBU (%)", summary.mbu_stats, 3),
        ],
    )
    if table.row_count > 0:
        console.print(table)
    # Headline: IPW, IPJ, Total Energy
    parts: list[str] = []
    if summary.ipw_stats:
        parts.append(f"[bold]IPW (acc/W):[/bold] {summary.ipw_stats.mean:.6f}")
    if summary.ipj_stats:
        parts.append(f"[bold]IPJ (acc/J):[/bold] {summary.ipj_stats.mean:.2e}")
    if summary.total_energy_joules > 0:
        val = summary.total_energy_joules
        unit = "kJ" if val > 1000 else "J"
        display = val / 1000 if val > 1000 else val
        parts.append(f"[bold]Total Energy:[/bold] {display:.1f} {unit}")
    if summary.avg_power_watts > 0:
        parts.append(f"[bold]Avg Power:[/bold] {summary.avg_power_watts:.1f} W")
    if parts:
        console.print("  ".join(parts))


def print_trace_summary(console: Console, summary: RunSummary) -> None:
    """Print agentic trace step-type breakdown."""
    sts = summary.trace_step_type_stats
    if not sts:
        return
    total_steps = sum(s.get("count", 0) for s in sts.values())
    avg_per_sample = (
        total_steps / summary.scored_samples if summary.scored_samples > 0 else 0
    )

    table = Table(
        title="[bold]Agentic Trace Summary[/bold]",
        show_header=True,
        header_style="bold bright_white",
        border_style="bright_blue",
        title_style="bold cyan",
        caption=(
            f"Total Steps: {total_steps}  |  Avg Steps/Sample: {avg_per_sample:.1f}"
        ),
    )
    table.add_column("Step Type", style="cyan", no_wrap=True)
    table.add_column("Count", justify="right")
    table.add_column("Avg Duration", justify="right")
    table.add_column("Avg Energy (J)", justify="right")
    table.add_column("Avg In Tokens", justify="right")
    table.add_column("Avg Out Tokens", justify="right")

    for stype, data in sorted(sts.items()):
        count = data.get("count", 0)
        avg_dur = data.get("avg_duration", 0.0)
        total_e = data.get("total_energy", 0.0)
        avg_e = total_e / count if count > 0 else 0.0
        avg_in = data.get("avg_input_tokens", 0.0)
        avg_out = data.get("avg_output_tokens", 0.0)
        table.add_row(
            stype,
            str(count),
            f"{avg_dur:.2f}s",
            f"{avg_e:.1f}" if avg_e > 0 else "\u2014",
            f"{avg_in:.0f}" if avg_in > 0 else "\u2014",
            f"{avg_out:.0f}" if avg_out > 0 else "\u2014",
        )
    console.print(table)


def print_compact_table(console: Console, summary: RunSummary) -> None:
    """Print a single dense metrics table (legacy behavior, enhanced)."""
    print_metrics_table(console, summary)


def print_full_results(
    console: Console,
    summary: RunSummary,
    *,
    compact: bool = False,
    trace_detail: bool = False,
) -> None:
    """Orchestrate all result panels."""
    if compact:
        print_compact_table(console, summary)
        return
    print_accuracy_panel(console, summary)
    print_latency_table(console, summary)
    print_energy_table(console, summary)
    print_trace_summary(console, summary)


def print_subject_table(
    console: Console,
    per_subject: Dict[str, Dict[str, float]],
) -> None:
    """Print per-subject accuracy breakdown."""
    table = Table(
        title="[bold]Per-Subject Breakdown[/bold]",
        show_header=True,
        header_style="bold bright_white",
        border_style="bright_blue",
        title_style="bold cyan",
    )
    table.add_column("Subject", style="cyan", no_wrap=True)
    table.add_column("Accuracy", justify="right")
    table.add_column("Correct", justify="right")
    table.add_column("Scored", justify="right")

    for subj, stats in sorted(per_subject.items()):
        table.add_row(
            subj,
            f"{stats['accuracy']:.4f}",
            str(int(stats.get("correct", 0))),
            str(int(stats.get("scored", 0))),
        )

    console.print(table)


def print_suite_summary(
    console: Console,
    summaries: List[RunSummary],
    suite_name: str = "",
) -> None:
    """Print a multi-run suite summary table."""
    title = f"Suite Results: {suite_name}" if suite_name else "Suite Results"
    table = Table(
        title=f"[bold]{title}[/bold]",
        show_header=True,
        header_style="bold bright_white",
        border_style="green",
        title_style="bold green",
    )
    table.add_column("Benchmark", style="cyan", no_wrap=True)
    table.add_column("Model", style="white")
    table.add_column("Accuracy", justify="right", style="bold")
    table.add_column("Scored", justify="right")
    table.add_column("Latency (s)", justify="right")
    table.add_column("Cost ($)", justify="right")

    for s in summaries:
        model_display = s.model if len(s.model) <= 24 else s.model[:21] + "..."
        table.add_row(
            s.benchmark,
            model_display,
            f"{s.accuracy:.4f}",
            f"{s.correct}/{s.scored_samples}",
            f"{s.mean_latency_seconds:.2f}",
            f"{s.total_cost_usd:.4f}",
        )

    console.print(table)


def print_completion(
    console: Console,
    summary: RunSummary,
    output_path: Optional[Path] = None,
    traces_dir: Optional[Path] = None,
    bench_energy: Optional[Dict[str, float]] = None,
) -> None:
    """Print a completion panel showing where data was saved."""
    lines = [
        "[bold green]Evaluation complete[/bold green]",
        (
            f"  Samples: {summary.total_samples}"
            f"  Scored: {summary.scored_samples}"
            f"  Errors: {summary.errors}"
        ),
    ]
    # Show resolved count when available
    resolved = summary.correct
    if resolved > 0:
        lines.append(f"  Resolved: {resolved}/{summary.scored_samples}")
    # Bench-level energy fallback
    if bench_energy is not None:
        be_energy = bench_energy.get("total_energy_joules")
        be_power = bench_energy.get("avg_power_watts")
        if be_energy is not None:
            lines.append(f"  [cyan]Bench Energy:[/cyan] {be_energy:.1f} J")
        if be_power is not None:
            lines.append(f"  [cyan]Bench Power:[/cyan]  {be_power:.1f} W")
    if output_path:
        lines.append(f"  [cyan]JSONL:[/cyan]   {output_path}")
        summary_path = (
            output_path.with_suffix(".summary.json")
            if hasattr(output_path, "with_suffix")
            else None
        )
        if summary_path:
            lines.append(f"  [cyan]Summary:[/cyan] {summary_path}")
    if traces_dir:
        lines.append(f"  [cyan]Traces:[/cyan]  {traces_dir}")
    body = "\n".join(lines)
    panel = Panel(body, border_style="green", expand=False)
    console.print(panel)


__all__ = [
    "OPENJARVIS_BANNER",
    "print_accuracy_panel",
    "print_banner",
    "print_compact_table",
    "print_completion",
    "print_energy_table",
    "print_full_results",
    "print_latency_table",
    "print_metrics_table",
    "print_run_header",
    "print_section",
    "print_subject_table",
    "print_suite_summary",
    "print_trace_summary",
]
