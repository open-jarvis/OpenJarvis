"""Tests for benchmark stats output and Rich table rendering."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock

from rich.console import Console

from friday_ai.bench._stubs import BenchmarkResult
from friday_ai.cli.bench_cmd import _render_stats_table


class TestLatencyBenchmarkStats:
    def test_latency_includes_std(self):
        """LatencyBenchmark should include std_latency in metrics."""
        from friday_ai.bench.latency import LatencyBenchmark

        bench = LatencyBenchmark()
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = {"content": "hi", "usage": {}}
        result = bench.run(engine, model="test", num_samples=5)
        assert "std_latency" in result.metrics


class TestRenderStatsTable:
    def test_renders_stats_columns(self):
        """_render_stats_table should produce Avg/Median/Min/Max/Std columns."""
        result = BenchmarkResult(
            benchmark_name="latency",
            model="test",
            engine="mock",
            metrics={
                "mean_latency": 1.5,
                "p50_latency": 1.4,
                "p95_latency": 2.1,
                "min_latency": 0.8,
                "max_latency": 3.0,
                "std_latency": 0.5,
            },
            samples=10,
            errors=0,
        )
        console = Console(file=StringIO(), force_terminal=True)
        _render_stats_table(console, result)
        output = console.file.getvalue()
        assert "Avg" in output
        assert "Median" in output
        assert "Min" in output
        assert "Max" in output

    def test_falls_back_for_non_stats_metrics(self):
        """Non-stats metrics should still render as simple key-value pairs."""
        result = BenchmarkResult(
            benchmark_name="throughput",
            model="test",
            engine="mock",
            metrics={
                "tokens_per_second": 42.5,
                "total_time_seconds": 10.0,
            },
            samples=5,
            errors=0,
        )
        console = Console(file=StringIO(), force_terminal=True)
        _render_stats_table(console, result)
        output = console.file.getvalue()
        assert "tokens_per_second" in output or "42.5" in output
