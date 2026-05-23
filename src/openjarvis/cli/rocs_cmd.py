"""``jarvis rocs`` — Return on Cognitive Spend ledger.

Joins the telemetry store (joules, dollars, tokens) against the trace store
(user feedback) and reports the energy-weighted value per joule per bucket.
This is the manifesto's RoCS metric, applied to your local agent fleet.
"""

from __future__ import annotations

import json as json_mod
import re
import sys
import time
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from openjarvis.core.config import load_config
from openjarvis.telemetry.aggregator import RoCSRow, TelemetryAggregator


_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$", re.IGNORECASE)
_DURATION_MULT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_duration(text: str) -> float:
    """Parse '7d', '24h', '30m', '90s' into seconds."""
    m = _DURATION_RE.match(text)
    if not m:
        raise click.BadParameter(
            f"Invalid duration {text!r}. Use e.g. '7d', '24h', '30m', '90s'."
        )
    return float(m.group(1)) * _DURATION_MULT[m.group(2).lower()]


def _resolve_since(
    day: bool, week: bool, month: bool, since: Optional[str]
) -> tuple[Optional[float], str]:
    """Translate the time-window flags into (since_timestamp, human_label)."""
    flags_set = sum(1 for f in (day, week, month, since is not None) if f)
    if flags_set > 1:
        raise click.UsageError(
            "Use at most one of --day, --week, --month, or --since=DURATION."
        )
    now = time.time()
    if since is not None:
        delta = _parse_duration(since)
        return now - delta, f"last {since}"
    if day:
        return now - _DURATION_MULT["d"], "last 24h"
    if month:
        return now - 30 * _DURATION_MULT["d"], "last 30 days"
    # Default
    return now - 7 * _DURATION_MULT["d"], "last 7 days"


def _format_energy(joules: float) -> str:
    """Format joules with Wh for context if non-trivial."""
    if joules <= 0:
        return "0 J"
    if joules >= 3600:
        return f"{joules:,.0f} J ({joules / 3600:.2f} Wh)"
    return f"{joules:,.1f} J"


def _format_money(usd: float) -> str:
    if usd <= 0:
        return "$0.00"
    if usd < 0.01:
        return f"${usd:.6f}"
    return f"${usd:,.2f}"


def _format_rocs(value: float, graded_count: int) -> str:
    if graded_count == 0:
        return "[dim]—[/dim]"
    return f"{value:.3f}"


def _row_to_dict(r: RoCSRow) -> dict:
    """Serialize a RoCSRow for --json output."""
    return {
        "bucket": r.bucket,
        "traces_count": r.traces_count,
        "graded_count": r.graded_count,
        "ungraded_calls": r.ungraded_calls,
        "total_energy_joules": r.total_energy_joules,
        "graded_energy_joules": r.graded_energy_joules,
        "weighted_value_joules": r.weighted_value_joules,
        "total_cost_usd": r.total_cost_usd,
        "total_completion_tokens": r.total_completion_tokens,
        "rocs": r.rocs,
        "pct_graded": r.pct_graded,
        "joules_per_trace": r.joules_per_trace,
    }


@click.group(invoke_without_command=True)
@click.option("--day", is_flag=True, help="Window: last 24 hours.")
@click.option("--week", is_flag=True, help="Window: last 7 days (default).")
@click.option("--month", is_flag=True, help="Window: last 30 days.")
@click.option(
    "--since",
    type=str,
    default=None,
    metavar="DURATION",
    help="Custom window, e.g. '12h', '3d', '90m'.",
)
@click.option(
    "--by",
    "group_by",
    type=click.Choice(["agent", "model", "engine", "day"]),
    default="agent",
    help="Group RoCS by this dimension.",
)
@click.option("--top", type=int, default=10, help="Show top N buckets by spend.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON instead of a table.")
@click.pass_context
def rocs(
    ctx: click.Context,
    day: bool,
    week: bool,
    month: bool,
    since: Optional[str],
    group_by: str,
    top: int,
    as_json: bool,
) -> None:
    """Return on Cognitive Spend — energy-weighted feedback per joule.

    Joins telemetry (energy, cost) with trace feedback (your thumbs) to show
    where your local AI is actually delivering value vs burning power for
    ungraded or low-quality output.
    """
    # If a subcommand was invoked, defer to it.
    if ctx.invoked_subcommand is not None:
        return

    since_ts, window_label = _resolve_since(day, week, month, since)

    config = load_config()
    tel_path = config.telemetry.db_path
    traces_path = getattr(config, "traces", None)
    traces_path = traces_path.db_path if traces_path else None
    if traces_path is None:
        # Fallback to the canonical default if config has no traces section
        from openjarvis.core.config import DEFAULT_CONFIG_DIR

        traces_path = str(DEFAULT_CONFIG_DIR / "traces.db")

    if not Path(tel_path).exists():
        click.echo(
            f"No telemetry database at {tel_path}. "
            "Run some agent calls first, then come back.",
            err=True,
        )
        sys.exit(1)

    agg = TelemetryAggregator(tel_path)
    try:
        overall = agg.compute_rocs_overall(traces_path, since=since_ts)
        rows = agg.compute_rocs(traces_path, since=since_ts, group_by=group_by)
    finally:
        agg.close()

    if as_json:
        click.echo(
            json_mod.dumps(
                {
                    "window": window_label,
                    "since_timestamp": since_ts,
                    "group_by": group_by,
                    "traces_db": traces_path,
                    "telemetry_db": tel_path,
                    "overall": _row_to_dict(overall),
                    "buckets": [_row_to_dict(r) for r in rows[:top]],
                },
                indent=2,
            )
        )
        return

    _render_human(overall, rows, window_label, group_by, top, traces_path)


def _render_human(
    overall: RoCSRow,
    rows: list[RoCSRow],
    window_label: str,
    group_by: str,
    top: int,
    traces_path: str,
) -> None:
    """Render the Throughput Ledger as a rich panel + table."""
    console = Console()

    # --- Overall summary ---
    traces_db_exists = Path(traces_path).exists()
    summary_lines: list[str] = []
    summary_lines.append(
        f"[bold]Energy:[/bold]  {_format_energy(overall.total_energy_joules)}"
    )
    summary_lines.append(
        f"[bold]Cost:[/bold]    {_format_money(overall.total_cost_usd)}"
    )
    summary_lines.append(
        f"[bold]Tokens:[/bold]  {overall.total_completion_tokens:,} completion"
    )
    summary_lines.append(
        f"[bold]Traces:[/bold]  {overall.traces_count} "
        f"({overall.graded_count} graded, {overall.pct_graded * 100:.0f}%)"
    )
    if overall.ungraded_calls > 0:
        summary_lines.append(
            f"[dim]         {overall.ungraded_calls} ungraded engine calls[/dim]"
        )
    summary_lines.append("")
    if overall.graded_count > 0:
        summary_lines.append(
            f"[bold cyan]RoCS:[/bold cyan]    "
            f"{overall.rocs:.3f}  "
            f"[dim](energy-weighted feedback per joule, [0=bad, 1=great])[/dim]"
        )
    else:
        summary_lines.append(
            "[bold cyan]RoCS:[/bold cyan]    [dim]— (no graded traces in window)[/dim]"
        )

    if not traces_db_exists:
        summary_lines.append("")
        summary_lines.append(
            f"[yellow]Note: traces.db not found at {traces_path}. "
            "All calls treated as ungraded. "
            "Run an agent inside TraceCollector + `jarvis feedback thumbs --up`"
            " to start grading.[/yellow]"
        )

    console.print(
        Panel(
            "\n".join(summary_lines),
            title=f"[bold]Throughput Ledger — {window_label}[/bold]",
            border_style="cyan",
            expand=False,
        )
    )

    # --- Per-bucket table ---
    if not rows:
        console.print(
            f"[dim]No telemetry rows in window. "
            f"Try a wider window (--month or --since=30d).[/dim]"
        )
        return

    table = Table(
        title=f"By {group_by} (top {min(top, len(rows))} by spend)",
        title_style="bold",
    )
    table.add_column(group_by.title(), style="cyan", no_wrap=True)
    table.add_column("Traces", justify="right")
    table.add_column("Graded %", justify="right")
    table.add_column("RoCS", justify="right", style="bold")
    table.add_column("Energy", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("J / trace", justify="right")
    table.add_column("Ungraded calls", justify="right", style="dim")

    for r in rows[:top]:
        table.add_row(
            r.bucket or "[dim](direct ask)[/dim]",
            f"{r.traces_count}",
            f"{r.pct_graded * 100:.0f}%" if r.traces_count else "—",
            _format_rocs(r.rocs, r.graded_count),
            _format_energy(r.total_energy_joules),
            _format_money(r.total_cost_usd),
            f"{r.joules_per_trace:.1f}" if r.traces_count else "—",
            f"{r.ungraded_calls}" if r.ungraded_calls else "",
        )
    console.print(table)

    # --- Insights footer ---
    graded_rows = [r for r in rows if r.graded_count > 0]
    if len(graded_rows) >= 2:
        best = max(graded_rows, key=lambda r: r.rocs)
        worst = min(graded_rows, key=lambda r: r.rocs)
        if best.bucket != worst.bucket:
            console.print()
            console.print(
                f"  [green]Best RoCS:[/green]   {best.bucket} ({best.rocs:.3f})"
            )
            console.print(
                f"  [red]Worst RoCS:[/red]  {worst.bucket} ({worst.rocs:.3f})"
            )


@rocs.command("explain")
def rocs_explain() -> None:
    """Explain what RoCS means and how it's computed."""
    console = Console()
    console.print(
        Panel(
            (
                "[bold]Return on Cognitive Spend (RoCS)[/bold]\n\n"
                "RoCS = SUM(feedback × energy_joules) / SUM(energy_joules of graded calls)\n\n"
                "Interpretation:\n"
                "  • Range: [0, 1] where 1 = every joule produced a perfect outcome\n"
                "  • Energy-weighted: a thumbs-up on a 100J research loop counts more\n"
                "    than a thumbs-up on a 1J one-shot ask. This is intentional —\n"
                "    you want to know where your *cognitive spend* is paying off.\n"
                "  • Only graded calls contribute. Ungraded calls are tracked\n"
                "    separately so you can see how much spend is currently\n"
                "    un-judgeable.\n\n"
                "To grade more traces:\n"
                "  jarvis feedback thumbs --up --last\n"
                "  jarvis feedback thumbs --down <trace_id>\n"
                "  jarvis feedback score <trace_id> --score 0.8\n\n"
                "From the [italic]Solve Everything[/italic] manifesto: 'If you "
                "cannot prove that every dollar of electricity you burn is "
                "generating a verified unit of intelligence, you are functionally "
                "bankrupt.'"
            ),
            border_style="cyan",
            expand=False,
        )
    )


__all__ = ["rocs"]
