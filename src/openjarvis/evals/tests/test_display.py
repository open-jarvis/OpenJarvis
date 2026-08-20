"""Tests for eval display functions."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from openjarvis.evals.core.display import (
    print_accuracy_panel,
    print_compact_table,
    print_energy_table,
    print_full_results,
    print_latency_table,
    print_trace_summary,
)
from openjarvis.evals.core.types import MetricStats, RunSummary


def _make_summary(**overrides) -> RunSummary:
    defaults = dict(
        benchmark="gaia",
        category="agentic",
        backend="jarvis-agent",
        model="qwen3:8b",
        total_samples=100,
        scored_samples=100,
        correct=42,
        accuracy=0.42,
        errors=0,
        mean_latency_seconds=15.0,
        total_cost_usd=0.0,
        total_energy_joules=9300.0,
        avg_power_watts=880.0,
        total_input_tokens=50000,
        total_output_tokens=12000,
        per_subject={"level_1": {"accuracy": 0.58, "correct": 40, "scored": 68}},
    )
    defaults.update(overrides)
    return RunSummary(**defaults)


def _make_stats(mean=10.0) -> MetricStats:
    return MetricStats(
        mean=mean,
        median=mean * 0.9,
        min=mean * 0.2,
        max=mean * 3.0,
        std=mean * 0.5,
        p90=mean * 1.5,
        p95=mean * 2.0,
        p99=mean * 2.5,
    )


class TestAccuracyPanel:
    def test_renders_without_error(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary()
        print_accuracy_panel(console, summary)
        output = console.file.getvalue()
        assert "42.0%" in output or "0.42" in output

    def test_shows_per_subject(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary()
        print_accuracy_panel(console, summary)
        output = console.file.getvalue()
        assert "level_1" in output


class TestLatencyTable:
    def test_renders_with_stats(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary(
            latency_stats=_make_stats(15.0),
            throughput_stats=_make_stats(40.0),
            input_token_stats=_make_stats(1024.0),
            output_token_stats=_make_stats(256.0),
        )
        print_latency_table(console, summary)
        output = console.file.getvalue()
        assert "Latency" in output
        assert "Avg" in output


class TestEnergyTable:
    def test_renders_ipj_ipw(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary(
            energy_stats=_make_stats(46000.0),
            power_stats=_make_stats(880.0),
            ipw_stats=_make_stats(0.00048),
            ipj_stats=_make_stats(9.0e-6),
        )
        print_energy_table(console, summary)
        output = console.file.getvalue()
        assert "IPW" in output
        assert "IPJ" in output


class TestTraceSummary:
    def test_renders_step_type_breakdown(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary(
            trace_step_type_stats={
                "generate": {
                    "count": 580,
                    "avg_duration": 8.2,
                    "total_energy": 22000.0,
                    "avg_input_tokens": 890.0,
                    "avg_output_tokens": 256.0,
                },
                "tool_call": {
                    "count": 420,
                    "avg_duration": 3.1,
                    "total_energy": 0.0,
                    "avg_input_tokens": 0.0,
                    "avg_output_tokens": 0.0,
                },
            },
        )
        print_trace_summary(console, summary)
        output = console.file.getvalue()
        assert "generate" in output
        assert "tool_call" in output


class TestCompactTable:
    def test_renders_all_metrics(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary(
            latency_stats=_make_stats(15.0),
            energy_stats=_make_stats(46000.0),
        )
        print_compact_table(console, summary)
        output = console.file.getvalue()
        assert "Latency" in output
        assert "Energy" in output


class TestFullResults:
    def test_renders_all_sections(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary(
            latency_stats=_make_stats(15.0),
            energy_stats=_make_stats(46000.0),
            power_stats=_make_stats(880.0),
        )
        print_full_results(console, summary)
        output = console.file.getvalue()
        assert "Accuracy" in output
