"""Tests for the local stack performance sampler."""

from __future__ import annotations

import json

from openjarvis.telemetry.stack import (
    ProcessCounters,
    ProcessMemory,
    StackSample,
    descendant_pids,
    make_stack_sample,
    summarize_samples,
    write_jsonl,
)


def test_descendant_pids_includes_only_processes_below_requested_roots() -> None:
    counters = {
        10: ProcessCounters(ppid=1, cpu_ticks=100),
        11: ProcessCounters(ppid=10, cpu_ticks=20),
        12: ProcessCounters(ppid=11, cpu_ticks=10),
        20: ProcessCounters(ppid=1, cpu_ticks=100),
    }

    assert descendant_pids((10,), counters) == (10, 11, 12)


def test_make_stack_sample_uses_pss_and_scales_cpu_to_machine_capacity() -> None:
    before = {
        10: ProcessCounters(ppid=1, cpu_ticks=100),
        11: ProcessCounters(ppid=10, cpu_ticks=20),
    }
    after = {
        10: ProcessCounters(ppid=1, cpu_ticks=160),
        11: ProcessCounters(ppid=10, cpu_ticks=40),
    }
    memory = {
        10: ProcessMemory(pss_kib=1024, rss_kib=2048),
        11: ProcessMemory(pss_kib=512, rss_kib=1024),
    }

    sample = make_stack_sample(
        timestamp_ns=123,
        roots=(10,),
        before=before,
        after=after,
        memory=memory,
        elapsed_seconds=2.0,
        clock_ticks_per_second=100,
        logical_cpus=8,
        gpu_utilization_pct=25.0,
        gpu_memory_used_mib=512,
    )

    assert sample.pids == (10, 11)
    assert sample.pss_kib == 1536
    assert sample.rss_kib == 3072
    assert sample.cpu_percent_one_core == 40.0
    assert sample.cpu_percent_machine == 5.0
    assert sample.gpu_utilization_pct == 25.0


def test_summary_uses_raw_samples_and_omits_unavailable_gpu_metrics() -> None:
    samples = [
        StackSample(1, (10,), 100, 200, 10.0, 1.25, None, None),
        StackSample(2, (10,), 300, 400, 30.0, 3.75, None, None),
        StackSample(3, (10,), 200, 500, 20.0, 2.5, None, None),
    ]

    summary = summarize_samples(samples)

    assert summary["samples"] == 3
    assert summary["cpu_percent_machine"]["p50"] == 2.5
    assert summary["pss_mib"]["peak"] == 300 / 1024
    assert "gpu_utilization_pct" not in summary


def test_jsonl_contains_only_resource_measurements(tmp_path) -> None:
    path = tmp_path / "stack.jsonl"
    write_jsonl(
        path,
        [StackSample(1, (10,), 100, 200, 10.0, 1.25, 25.0, 512)],
    )

    row = json.loads(path.read_text().strip())
    assert row == {
        "cpu_percent_machine": 1.25,
        "cpu_percent_one_core": 10.0,
        "gpu_memory_used_mib": 512,
        "gpu_utilization_pct": 25.0,
        "pids": [10],
        "pss_kib": 100,
        "rss_kib": 200,
        "schema": "openjarvis.stack-benchmark.v1",
        "timestamp_ns": 1,
    }
