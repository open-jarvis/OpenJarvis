"""Export functions for agentic run traces and profiling records."""

from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from openjarvis.evals.core.trace import QueryTrace


def _agg_stats(values: Sequence[Optional[float]]) -> dict[str, Optional[float]]:
    """Return {avg, median, min, max, std} filtering None values."""
    clean = [v for v in values if v is not None]
    if not clean:
        return {"avg": None, "median": None, "min": None, "max": None, "std": None}
    return {
        "avg": statistics.mean(clean),
        "median": statistics.median(clean),
        "min": min(clean),
        "max": max(clean),
        "std": statistics.stdev(clean) if len(clean) > 1 else 0.0,
    }


def _compute_efficiency(
    traces: list[QueryTrace],
    total_gpu_energy: Optional[float],
    total_cpu_energy: Optional[float],
) -> dict[str, Optional[float]]:
    """Compute efficiency metrics from traces and aggregate energy."""
    scored = [t for t in traces if t.is_resolved is not None]
    resolved = sum(1 for t in scored if t.is_resolved is True)
    accuracy = resolved / len(scored) if scored else None
    gpu_powers = [
        t.avg_gpu_power_watts for t in traces if t.avg_gpu_power_watts is not None
    ]
    cpu_powers = [
        t.avg_cpu_power_watts for t in traces if t.avg_cpu_power_watts is not None
    ]
    avg_gpu_power = statistics.mean(gpu_powers) if gpu_powers else None
    avg_cpu_power = statistics.mean(cpu_powers) if cpu_powers else None
    return {
        "accuracy": accuracy,
        "total_gpu_energy_joules": total_gpu_energy,
        "total_cpu_energy_joules": total_cpu_energy,
        "avg_gpu_power_watts": avg_gpu_power,
        "avg_cpu_power_watts": avg_cpu_power,
        "ipj": (accuracy / total_gpu_energy if accuracy and total_gpu_energy else None),
        "ipw": (accuracy / avg_gpu_power if accuracy and avg_gpu_power else None),
    }


def _compute_normalized(
    traces: list[QueryTrace],
) -> Optional[dict[str, Any]]:
    """Recompute stats after trimming top/bottom 5% outliers by wall_clock.

    Returns None if fewer than 4 traces (trimming would remove too much data).
    """
    n = len(traces)
    if n < 4:
        return None

    trim_count = max(1, math.floor(n * 0.05))
    sorted_traces = sorted(traces, key=lambda t: t.total_wall_clock_s)
    trimmed = sorted_traces[trim_count : n - trim_count]

    if not trimmed:
        return None

    # Recompute aggregate energy on trimmed set
    gpu_energy_values = [
        t.total_gpu_energy_joules
        for t in trimmed
        if t.total_gpu_energy_joules is not None
    ]
    total_gpu_energy = sum(gpu_energy_values) if gpu_energy_values else None

    cpu_energy_values: list[float] = []
    for trace in trimmed:
        cpu_vals = [
            turn.cpu_energy_joules
            for turn in trace.turns
            if turn.cpu_energy_joules is not None
        ]
        if cpu_vals:
            cpu_energy_values.append(sum(cpu_vals))
    total_cpu_energy = sum(cpu_energy_values) if cpu_energy_values else None

    norm_stats = {
        "_description": (
            f"Statistics recomputed after trimming {trim_count} outlier(s) "
            f"from each end by wall_clock_s ({len(trimmed)}/{n} traces kept)"
        ),
        "_outliers_removed": trim_count * 2,
        "wall_clock_s": _agg_stats(
            [t.total_wall_clock_s for t in trimmed],
        ),
        "gpu_energy_joules": _agg_stats(
            [t.total_gpu_energy_joules for t in trimmed],
        ),
        "cpu_energy_joules": _agg_stats(
            [t.total_cpu_energy_joules for t in trimmed],
        ),
        "gpu_power_watts": _agg_stats(
            [t.avg_gpu_power_watts for t in trimmed],
        ),
        "cpu_power_watts": _agg_stats(
            [t.avg_cpu_power_watts for t in trimmed],
        ),
        "input_tokens": _agg_stats(
            [float(t.total_input_tokens) for t in trimmed],
        ),
        "output_tokens": _agg_stats(
            [float(t.total_output_tokens) for t in trimmed],
        ),
        "total_tokens": _agg_stats(
            [float(t.total_tokens) for t in trimmed],
        ),
        "throughput_tokens_per_sec": _agg_stats(
            [t.throughput_tokens_per_sec for t in trimmed],
        ),
        "energy_per_token_joules": _agg_stats(
            [t.energy_per_token_joules for t in trimmed],
        ),
        "mbu_avg_pct": _agg_stats(
            [t.query_mbu_avg_pct for t in trimmed],
        ),
    }

    norm_efficiency = _compute_efficiency(trimmed, total_gpu_energy, total_cpu_energy)

    return {
        "normalized_statistics": norm_stats,
        "normalized_efficiency": norm_efficiency,
    }


def export_jsonl(traces: list[QueryTrace], path: Path) -> Path:
    """Export traces as JSONL (one JSON object per line).

    Args:
        traces: List of QueryTrace objects to export.
        path: Output file path. Parent directories are created if needed.

    Returns:
        The path to the written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for trace in traces:
            f.write(json.dumps(trace.to_dict()) + "\n")
    return path


def export_hf_dataset(traces: list[QueryTrace], path: Path) -> Path:
    """Export traces as a HuggingFace Arrow dataset.

    Args:
        traces: List of QueryTrace objects to export.
        path: Output directory for the Arrow dataset.

    Returns:
        The path to the saved dataset directory.

    Raises:
        ImportError: If the ``datasets`` package is not installed.
    """
    ds = QueryTrace.to_hf_dataset(traces)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_to_disk(str(path))
    return path


def _hardware_info_dict() -> dict[str, Any]:
    """Detect hardware and return a JSON-serializable dict."""
    try:
        from openjarvis.core.config import detect_hardware

        hw = detect_hardware()
        info: dict[str, Any] = {
            "platform": hw.platform,
            "cpu_brand": hw.cpu_brand,
            "cpu_count": hw.cpu_count,
            "ram_gb": hw.ram_gb,
        }
        if hw.gpu is not None:
            info["gpu"] = {
                "vendor": hw.gpu.vendor,
                "name": hw.gpu.name,
                "vram_gb": hw.gpu.vram_gb,
                "count": hw.gpu.count,
            }
        else:
            info["gpu"] = None
        return info
    except Exception:
        return {}


def export_summary_json(
    traces: list[QueryTrace],
    config: dict[str, Any],
    path: Path,
    *,
    bench_energy: Optional[dict[str, Any]] = None,
) -> Path:
    """Export aggregate summary as JSON.

    Args:
        traces: List of QueryTrace objects.
        config: Run configuration dictionary.
        path: Output file path.
        bench_energy: Optional benchmark-level aggregate telemetry dict.

    Returns:
        The path to the written file.
    """
    total_queries = len(traces)
    completed = sum(1 for t in traces if t.completed)
    total_turns = sum(t.num_turns for t in traces)
    total_tool_calls = sum(t.total_tool_calls for t in traces)

    total_input_tokens = sum(t.total_input_tokens for t in traces)
    total_output_tokens = sum(t.total_output_tokens for t in traces)
    total_wall_clock_s = sum(t.total_wall_clock_s for t in traces)

    gpu_energy_values = [
        t.total_gpu_energy_joules
        for t in traces
        if t.total_gpu_energy_joules is not None
    ]
    total_gpu_energy = sum(gpu_energy_values) if gpu_energy_values else None

    cpu_energy_values: list[float] = []
    for trace in traces:
        cpu_vals = [
            turn.cpu_energy_joules
            for turn in trace.turns
            if turn.cpu_energy_joules is not None
        ]
        if cpu_vals:
            cpu_energy_values.append(sum(cpu_vals))
    total_cpu_energy = sum(cpu_energy_values) if cpu_energy_values else None

    resolved = sum(1 for t in traces if t.is_resolved is True)
    unresolved = sum(1 for t in traces if t.is_resolved is False)

    cost_values = [t.total_cost_usd for t in traces if t.total_cost_usd is not None]
    total_cost = sum(cost_values) if cost_values else None

    avg_turns = total_turns / total_queries if total_queries > 0 else 0
    avg_wall_clock = total_wall_clock_s / total_queries if total_queries > 0 else 0
    avg_gpu_energy = (
        total_gpu_energy / total_queries
        if total_gpu_energy is not None and total_queries > 0
        else None
    )

    stats = {
        "wall_clock_s": _agg_stats([t.total_wall_clock_s for t in traces]),
        "gpu_energy_joules": _agg_stats(
            [t.total_gpu_energy_joules for t in traces],
        ),
        "cpu_energy_joules": _agg_stats(
            [t.total_cpu_energy_joules for t in traces],
        ),
        "gpu_power_watts": _agg_stats(
            [t.avg_gpu_power_watts for t in traces],
        ),
        "cpu_power_watts": _agg_stats(
            [t.avg_cpu_power_watts for t in traces],
        ),
        "input_tokens": _agg_stats(
            [float(t.total_input_tokens) for t in traces],
        ),
        "output_tokens": _agg_stats(
            [float(t.total_output_tokens) for t in traces],
        ),
        "total_tokens": _agg_stats(
            [float(t.total_tokens) for t in traces],
        ),
        "throughput_tokens_per_sec": _agg_stats(
            [t.throughput_tokens_per_sec for t in traces],
        ),
        "energy_per_token_joules": _agg_stats(
            [t.energy_per_token_joules for t in traces],
        ),
        "cost_usd": _agg_stats([t.total_cost_usd for t in traces]),
        "turns": _agg_stats([float(t.num_turns) for t in traces]),
        "tool_calls": _agg_stats(
            [float(t.total_tool_calls) for t in traces],
        ),
        "mbu_avg_pct": _agg_stats(
            [t.query_mbu_avg_pct for t in traces],
        ),
    }

    accuracy = (
        resolved / (resolved + unresolved) if (resolved + unresolved) > 0 else None
    )

    efficiency = _compute_efficiency(traces, total_gpu_energy, total_cpu_energy)

    normalized = _compute_normalized(traces)

    # Aggregate per-action energy across all turns
    action_totals: dict[str, dict[str, float]] = {}
    for trace in traces:
        for turn in trace.turns:
            if not turn.action_energy_breakdown:
                continue
            for action in turn.action_energy_breakdown:
                atype = action["action_type"]
                if atype not in action_totals:
                    action_totals[atype] = {
                        "count": 0,
                        "total_duration_s": 0.0,
                        "total_gpu_energy_joules": 0.0,
                        "total_cpu_energy_joules": 0.0,
                    }
                entry = action_totals[atype]
                entry["count"] += 1
                entry["total_duration_s"] += action.get(
                    "duration_s",
                    0.0,
                )
                gpu_e = action.get("gpu_energy_joules")
                if gpu_e is not None:
                    entry["total_gpu_energy_joules"] += gpu_e
                cpu_e = action.get("cpu_energy_joules")
                if cpu_e is not None:
                    entry["total_cpu_energy_joules"] += cpu_e

    summary: dict[str, Any] = {
        "generated_at": time.time(),
        "config": config,
        "hardware_info": _hardware_info_dict(),
        "totals": {
            "queries": total_queries,
            "completed": completed,
            "resolved": resolved,
            "unresolved": unresolved,
            "accuracy": accuracy,
            "turns": total_turns,
            "tool_calls": total_tool_calls,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "wall_clock_s": total_wall_clock_s,
            "gpu_energy_joules": total_gpu_energy,
            "cpu_energy_joules": total_cpu_energy,
            "cost_usd": total_cost,
        },
        "averages": {
            "turns_per_query": avg_turns,
            "wall_clock_per_query_s": avg_wall_clock,
            "gpu_energy_per_query_joules": avg_gpu_energy,
        },
        "statistics": stats,
        "efficiency": efficiency,
    }

    if action_totals:
        summary["action_energy_summary"] = action_totals

    if normalized is not None:
        summary["normalized_statistics"] = normalized["normalized_statistics"]
        summary["normalized_efficiency"] = normalized["normalized_efficiency"]

    if bench_energy is not None:
        summary["bench_telemetry"] = bench_energy

    # ---- Spec §6.3: table_gen-compatible flat schema ----
    # Emit framework / framework_commit / model / benchmark / n_tasks /
    # metrics at the top level so the framework-comparison `table_gen`
    # loader (`_SummarySchema`) can parse this file. The existing rich
    # schema is preserved untouched; this is purely additive.
    fwk = ""
    fwk_commit = ""
    if isinstance(config, dict):
        fwk = config.get("framework", "") or ""
        fwk_commit = config.get("framework_commit", "") or ""
    if not fwk:
        fwk = "openjarvis"

    def _stats_block(vals: list[float]) -> dict[str, Any]:
        if not vals:
            return {"mean": 0.0, "std": 0.0, "n": 0}
        return {
            "mean": float(statistics.fmean(vals)),
            "std": (float(statistics.stdev(vals)) if len(vals) > 1 else 0.0),
            "n": len(vals),
        }

    accuracy_vals: list[float] = [
        1.0 if t.is_resolved is True else 0.0
        for t in traces
        if t.is_resolved is not None
    ]
    latency_vals = [t.total_wall_clock_s for t in traces if t.total_wall_clock_s > 0]
    energy_vals = [
        t.total_gpu_energy_joules
        for t in traces
        if t.total_gpu_energy_joules is not None and t.total_gpu_energy_joules > 0
    ]
    in_tok_vals = [
        float(t.total_input_tokens) for t in traces if t.total_input_tokens > 0
    ]
    out_tok_vals = [
        float(t.total_output_tokens) for t in traces if t.total_output_tokens > 0
    ]
    cost_vals = [
        t.total_cost_usd
        for t in traces
        if t.total_cost_usd is not None and t.total_cost_usd > 0
    ]
    power_vals = [
        t.avg_gpu_power_watts
        for t in traces
        if t.avg_gpu_power_watts is not None and t.avg_gpu_power_watts > 0
    ]

    summary["framework"] = fwk
    summary["framework_commit"] = fwk_commit
    summary["model"] = config.get("model", "") if isinstance(config, dict) else ""
    summary["benchmark"] = (
        config.get("benchmark", "") if isinstance(config, dict) else ""
    )
    summary["n_tasks"] = len(traces)
    summary["metrics"] = {
        "accuracy": _stats_block(accuracy_vals),
        "latency_seconds": _stats_block(latency_vals),
        "energy_joules_per_query": _stats_block(energy_vals),
        "input_tokens_per_query": _stats_block(in_tok_vals),
        "output_tokens_per_query": _stats_block(out_tok_vals),
        "cost_usd_per_query": _stats_block(cost_vals),
        "peak_power_w": _stats_block(power_vals),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, default=str))
    return path


def export_artifacts_manifest(run_dir: Path) -> Optional[Path]:
    """Scan ``{run_dir}/artifacts/`` and write ``artifacts_manifest.json``.

    The manifest lists every per-query artifact directory together with
    the files it contains, making it easy for downstream tools to discover
    what was produced without walking the directory tree themselves.

    Returns:
        The manifest path, or ``None`` if there is no artifacts directory.
    """
    artifacts_root = run_dir / "artifacts"
    if not artifacts_root.is_dir():
        return None

    entries: list[dict[str, object]] = []
    for query_dir in sorted(artifacts_root.iterdir()):
        if not query_dir.is_dir():
            continue
        files = sorted(
            str(p.relative_to(artifacts_root))
            for p in query_dir.rglob("*")
            if p.is_file()
        )
        entries.append({"query_dir": query_dir.name, "files": files})

    manifest_path = run_dir / "artifacts_manifest.json"
    manifest_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return manifest_path


__all__ = [
    "export_jsonl",
    "export_hf_dataset",
    "export_summary_json",
    "export_artifacts_manifest",
]
