"""``jarvis telemetry`` — query and manage telemetry data."""

from __future__ import annotations

import csv as csv_mod
import io
import json as json_mod

import click
from rich.console import Console
from rich.table import Table

from openjarvis.core.config import load_config
from openjarvis.telemetry.aggregator import TelemetryAggregator


def _get_aggregator() -> TelemetryAggregator:
    """Build a TelemetryAggregator from user config."""
    config = load_config()
    return TelemetryAggregator(config.telemetry.db_path)


@click.group()
def telemetry() -> None:
    """Query and manage inference telemetry data."""


@telemetry.command()
@click.option(
    "-n",
    "--top",
    "top_n",
    default=10,
    type=int,
    help="Number of top models to show.",
)
def stats(top_n: int) -> None:
    """Show aggregated telemetry statistics."""
    console = Console()
    agg = _get_aggregator()
    try:
        summary = agg.summary()

        # Overview
        overview = Table(title="Telemetry Overview")
        overview.add_column("Metric", style="cyan")
        overview.add_column("Value", style="green")
        overview.add_row("Total Calls", str(summary.total_calls))
        overview.add_row("Total Tokens", str(summary.total_tokens))
        overview.add_row("Total Cost (USD)", f"${summary.total_cost:.6f}")
        overview.add_row("Total Latency (s)", f"{summary.total_latency:.2f}")
        if summary.total_energy_joules > 0:
            overview.add_row("Total Energy (J)", f"{summary.total_energy_joules:.2f}")
        if summary.avg_throughput_tok_per_sec > 0:
            tps = summary.avg_throughput_tok_per_sec
            overview.add_row("Avg Throughput (tok/s)", f"{tps:.1f}")
        if summary.avg_gpu_utilization_pct > 0:
            gpu = summary.avg_gpu_utilization_pct
            overview.add_row("Avg GPU Utilization (%)", f"{gpu:.1f}")
        # Derived metrics
        if summary.avg_energy_per_output_token_joules > 0:
            overview.add_row(
                "Energy/Output Token (J)",
                f"{summary.avg_energy_per_output_token_joules:.6f}",
            )
        if summary.avg_throughput_per_watt > 0:
            overview.add_row(
                "Throughput/Watt (tok/s/W)",
                f"{summary.avg_throughput_per_watt:.2f}",
            )
        # ITL metrics
        if summary.avg_mean_itl_ms > 0:
            overview.add_row("Mean ITL (ms)", f"{summary.avg_mean_itl_ms:.2f}")
        if summary.avg_median_itl_ms > 0:
            overview.add_row("Median ITL (ms)", f"{summary.avg_median_itl_ms:.2f}")
        if summary.avg_p95_itl_ms > 0:
            overview.add_row("P95 ITL (ms)", f"{summary.avg_p95_itl_ms:.2f}")
        console.print(overview)

        # Per-model table
        if summary.per_model:
            has_energy = any(
                ms.total_energy_joules > 0 for ms in summary.per_model[:top_n]
            )
            has_itl = any(ms.avg_mean_itl_ms > 0 for ms in summary.per_model[:top_n])
            model_table = Table(title=f"Top {top_n} Models")
            model_table.add_column("Model", style="cyan")
            model_table.add_column("Calls", justify="right")
            model_table.add_column("Tokens", justify="right")
            model_table.add_column("Avg Latency", justify="right")
            model_table.add_column("Cost", justify="right")
            if has_energy:
                model_table.add_column("Energy (J)", justify="right")
                model_table.add_column("E/OutTok (J)", justify="right")
                model_table.add_column("Tok/s/W", justify="right")
                model_table.add_column("Throughput", justify="right")
                model_table.add_column("GPU Util %", justify="right")
            if has_itl:
                model_table.add_column("Mean ITL", justify="right")
                model_table.add_column("P95 ITL", justify="right")
            for ms in summary.per_model[:top_n]:
                row = [
                    ms.model_id,
                    str(ms.call_count),
                    str(ms.total_tokens),
                    f"{ms.avg_latency:.3f}s",
                    f"${ms.total_cost:.6f}",
                ]
                if has_energy:
                    row.append(f"{ms.total_energy_joules:.2f}")
                    row.append(f"{ms.avg_energy_per_output_token_joules:.6f}")
                    row.append(f"{ms.avg_throughput_per_watt:.2f}")
                    row.append(f"{ms.avg_throughput_tok_per_sec:.1f}")
                    row.append(f"{ms.avg_gpu_utilization_pct:.1f}")
                if has_itl:
                    row.append(f"{ms.avg_mean_itl_ms:.2f}")
                    row.append(f"{ms.avg_p95_itl_ms:.2f}")
                model_table.add_row(*row)
            console.print(model_table)

        # Per-engine table
        if summary.per_engine:
            has_engine_energy = any(
                es.total_energy_joules > 0 for es in summary.per_engine
            )
            has_engine_itl = any(es.avg_mean_itl_ms > 0 for es in summary.per_engine)
            engine_table = Table(title="Engines")
            engine_table.add_column("Engine", style="cyan")
            engine_table.add_column("Calls", justify="right")
            engine_table.add_column("Tokens", justify="right")
            engine_table.add_column("Avg Latency", justify="right")
            engine_table.add_column("Cost", justify="right")
            if has_engine_energy:
                engine_table.add_column("Energy (J)", justify="right")
                engine_table.add_column("E/OutTok (J)", justify="right")
                engine_table.add_column("Tok/s/W", justify="right")
                engine_table.add_column("Throughput", justify="right")
                engine_table.add_column("GPU Util %", justify="right")
            if has_engine_itl:
                engine_table.add_column("Mean ITL", justify="right")
                engine_table.add_column("P95 ITL", justify="right")
            for es in summary.per_engine:
                row = [
                    es.engine,
                    str(es.call_count),
                    str(es.total_tokens),
                    f"{es.avg_latency:.3f}s",
                    f"${es.total_cost:.6f}",
                ]
                if has_engine_energy:
                    row.append(f"{es.total_energy_joules:.2f}")
                    row.append(f"{es.avg_energy_per_output_token_joules:.6f}")
                    row.append(f"{es.avg_throughput_per_watt:.2f}")
                    row.append(f"{es.avg_throughput_tok_per_sec:.1f}")
                    row.append(f"{es.avg_gpu_utilization_pct:.1f}")
                if has_engine_itl:
                    row.append(f"{es.avg_mean_itl_ms:.2f}")
                    row.append(f"{es.avg_p95_itl_ms:.2f}")
                engine_table.add_row(*row)
            console.print(engine_table)

        if summary.total_calls == 0:
            console.print("[dim]No telemetry data recorded yet.[/dim]")
    finally:
        agg.close()


@telemetry.command()
@click.option(
    "-f",
    "--format",
    "fmt",
    default="json",
    type=click.Choice(["json", "csv"]),
    help="Output format.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    default=None,
    type=click.Path(),
    help="Output file path (default: stdout).",
)
def export(fmt: str, output_path: str | None) -> None:
    """Export telemetry records."""
    agg = _get_aggregator()
    try:
        records = agg.export_records()

        if fmt == "json":
            text = json_mod.dumps(records, indent=2)
        else:
            # CSV
            buf = io.StringIO()
            if records:
                writer = csv_mod.DictWriter(buf, fieldnames=records[0].keys())
                writer.writeheader()
                writer.writerows(records)
            text = buf.getvalue()

        if output_path:
            with open(output_path, "w") as fh:
                fh.write(text)
            click.echo(f"Exported {len(records)} records to {output_path}")
        else:
            click.echo(text)
    finally:
        agg.close()


@telemetry.command()
@click.option(
    "-y",
    "--yes",
    "confirmed",
    is_flag=True,
    help="Skip confirmation prompt.",
)
def clear(confirmed: bool) -> None:
    """Delete all telemetry records."""
    if not confirmed:
        if not click.confirm("Delete all telemetry records?"):
            click.echo("Aborted.")
            return

    agg = _get_aggregator()
    try:
        count = agg.clear()
        click.echo(f"Deleted {count} telemetry records.")
    finally:
        agg.close()
