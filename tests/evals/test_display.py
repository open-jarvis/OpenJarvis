"""Tests for the Rich display helpers in openjarvis.evals.core.display."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from openjarvis.evals.core.display import (
    print_banner,
    print_completion,
    print_metrics_table,
    print_run_header,
    print_section,
    print_subject_table,
    print_suite_summary,
)
from openjarvis.evals.core.types import MetricStats, RunSummary


def _make_console() -> tuple[Console, StringIO]:
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    return console, buf


def _make_summary(**overrides) -> RunSummary:
    defaults = dict(
        benchmark="supergpqa",
        category="reasoning",
        backend="jarvis-direct",
        model="qwen3:8b",
        total_samples=50,
        scored_samples=48,
        correct=36,
        accuracy=0.75,
        errors=2,
        mean_latency_seconds=1.23,
        total_cost_usd=0.05,
    )
    defaults.update(overrides)
    return RunSummary(**defaults)


def _make_metric_stats(**kw) -> MetricStats:
    defaults = dict(
        mean=1.0,
        median=0.9,
        min=0.1,
        max=2.5,
        std=0.3,
        p90=2.0,
        p95=2.2,
        p99=2.4,
    )
    defaults.update(kw)
    return MetricStats(**defaults)


class TestPrintBanner:
    def test_produces_output(self):
        console, buf = _make_console()
        print_banner(console)
        output = buf.getvalue()
        assert "OpenJarvis" in output or "___" in output

    def test_contains_version(self):
        console, buf = _make_console()
        print_banner(console)
        output = buf.getvalue()
        assert "v1.8" in output


class TestPrintSection:
    def test_produces_rule(self):
        console, buf = _make_console()
        print_section(console, "Configuration")
        output = buf.getvalue()
        assert "Configuration" in output


class TestPrintRunHeader:
    def test_shows_config_details(self):
        console, buf = _make_console()
        print_run_header(
            console,
            benchmark="supergpqa",
            model="qwen3:8b",
            backend="jarvis-direct",
            samples=50,
            workers=4,
        )
        output = buf.getvalue()
        assert "supergpqa" in output
        assert "qwen3:8b" in output
        assert "50" in output

    def test_shows_warmup_when_nonzero(self):
        console, buf = _make_console()
        print_run_header(
            console,
            benchmark="supergpqa",
            model="qwen3:8b",
            backend="jarvis-direct",
            samples=50,
            workers=4,
            warmup=5,
        )
        output = buf.getvalue()
        assert "Warmup" in output


class TestPrintMetricsTable:
    def test_full_stats(self):
        summary = _make_summary(
            accuracy_stats=_make_metric_stats(),
            latency_stats=_make_metric_stats(mean=1.23),
            ttft_stats=_make_metric_stats(mean=0.05),
            input_token_stats=_make_metric_stats(mean=150.0),
            output_token_stats=_make_metric_stats(mean=200.0),
            energy_stats=_make_metric_stats(mean=5.0),
            power_stats=_make_metric_stats(mean=250.0),
            gpu_utilization_stats=_make_metric_stats(mean=85.0),
            throughput_stats=_make_metric_stats(mean=42.0),
            mfu_stats=_make_metric_stats(mean=0.35),
            mbu_stats=_make_metric_stats(mean=0.45),
            ipw_stats=_make_metric_stats(mean=0.003),
            ipj_stats=_make_metric_stats(mean=0.15),
            energy_per_output_token_stats=_make_metric_stats(mean=0.025),
            throughput_per_watt_stats=_make_metric_stats(mean=0.17),
            itl_stats=_make_metric_stats(mean=23.5),
        )
        console, buf = _make_console()
        print_metrics_table(console, summary)
        output = buf.getvalue()
        assert "Task-Level Metrics" in output
        assert "Accuracy" in output
        assert "Latency" in output
        assert "Energy" in output
        assert "0.75" in output  # headline accuracy

    def test_accuracy_latency_only(self):
        summary = _make_summary(
            accuracy_stats=_make_metric_stats(mean=0.75),
            latency_stats=_make_metric_stats(mean=1.23),
        )
        console, buf = _make_console()
        print_metrics_table(console, summary)
        output = buf.getvalue()
        assert "Accuracy" in output
        assert "Latency" in output
        # Energy rows should not appear
        assert "Energy (J)" not in output

    def test_no_stats_produces_headline_only(self):
        summary = _make_summary()
        console, buf = _make_console()
        print_metrics_table(console, summary)
        output = buf.getvalue()
        # Should still show headline stats
        assert "0.75" in output


class TestPrintSubjectTable:
    def test_subject_breakdown(self):
        per_subject = {
            "math": {"accuracy": 0.8, "correct": 8, "scored": 10},
            "science": {"accuracy": 0.6, "correct": 6, "scored": 10},
        }
        console, buf = _make_console()
        print_subject_table(console, per_subject)
        output = buf.getvalue()
        assert "math" in output
        assert "science" in output
        assert "0.8000" in output


class TestPrintSuiteSummary:
    def test_multiple_summaries(self):
        summaries = [
            _make_summary(benchmark="supergpqa", model="qwen3:8b"),
            _make_summary(benchmark="gaia", model="qwen3:8b", accuracy=0.60),
        ]
        console, buf = _make_console()
        print_suite_summary(console, summaries, suite_name="test-suite")
        output = buf.getvalue()
        assert "test-suite" in output
        assert "supergpqa" in output
        assert "gaia" in output


class TestPrintCompletion:
    def test_shows_paths(self):
        summary = _make_summary()
        console, buf = _make_console()
        print_completion(
            console,
            summary,
            output_path=Path("results/test.jsonl"),
            traces_dir=Path("results/traces/supergpqa_qwen3-8b"),
        )
        output = buf.getvalue()
        assert "results/test.jsonl" in output
        assert "traces" in output
        assert "complete" in output.lower()

    def test_no_paths(self):
        summary = _make_summary()
        console, buf = _make_console()
        print_completion(console, summary)
        output = buf.getvalue()
        assert "complete" in output.lower()
