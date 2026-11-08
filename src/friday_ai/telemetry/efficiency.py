"""MFU/MBU efficiency calculator for GPU inference telemetry.

Computes Model FLOPs Utilization (MFU) and Model Bandwidth Utilization (MBU)
to quantify how efficiently a model uses available GPU compute and memory bandwidth.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EfficiencyMetrics:
    """Results of an MFU/MBU efficiency calculation."""

    mfu_pct: float = 0.0  # Model FLOPs Utilization %
    mbu_pct: float = 0.0  # Model Bandwidth Utilization %
    actual_flops: float = 0.0  # Actual FLOPs achieved
    peak_flops: float = 0.0  # Peak theoretical FLOPs
    actual_bandwidth_gb_s: float = 0.0  # Actual memory bandwidth (GB/s)
    peak_bandwidth_gb_s: float = 0.0  # Peak memory bandwidth (GB/s)
    ipj: float = 0.0  # Intelligence Per Joule


def estimate_model_flops_per_token(
    param_count_b: float,
    active_params_b: float | None = None,
) -> float:
    """Estimate FLOPs for one forward-pass token of a dense transformer.

    For dense models, FLOPs per token ≈ 2 * params.  For MoE models, pass
    ``active_params_b`` (the number of *active* parameters per token).

    Args:
        param_count_b: Total parameter count in billions.
        active_params_b: Active parameters per token in billions.  If *None*,
            defaults to ``param_count_b`` (dense model).

    Returns:
        Estimated FLOPs per token.
    """
    active = active_params_b if active_params_b is not None else param_count_b
    return 2.0 * active * 1e9


def estimate_model_bytes_per_token(
    param_count_b: float,
    bytes_per_param: float = 2.0,
) -> float:
    """Estimate bytes of memory loaded per decode step.

    Args:
        param_count_b: Total parameter count in billions.
        bytes_per_param: Bytes per parameter (default 2.0 for FP16).

    Returns:
        Bytes loaded per token.
    """
    return param_count_b * 1e9 * bytes_per_param


def compute_efficiency(
    param_count_b: float,
    active_params_b: float | None,
    gpu_peak_tflops: float,
    gpu_peak_bandwidth_gb_s: float,
    tokens_per_sec: float,
    num_gpus: int = 1,
    energy_joules: float = 0.0,
    accuracy: float = 0.0,
    bytes_per_param: float = 2.0,
) -> EfficiencyMetrics:
    """Compute MFU, MBU, and derived efficiency metrics.

    Args:
        param_count_b: Total parameter count in billions.
        active_params_b: Active parameters per token in billions (*None* for dense).
        gpu_peak_tflops: Peak theoretical TFLOPS per GPU (e.g. 312 for A100 SXM FP16).
        gpu_peak_bandwidth_gb_s: Peak memory bandwidth per GPU in GB/s
            (e.g. 2039 for A100 SXM).
        tokens_per_sec: Measured generation throughput (tokens/second).
        num_gpus: Number of GPUs used for inference.
        energy_joules: Total energy consumed in joules (for IPJ calculation).
        accuracy: Accuracy score in [0, 1] (for IPJ calculation).
        bytes_per_param: Bytes per parameter (default 2.0 for FP16).

    Returns:
        :class:`EfficiencyMetrics` with all computed values.
    """
    flops_per_token = estimate_model_flops_per_token(param_count_b, active_params_b)
    bytes_per_token = estimate_model_bytes_per_token(param_count_b, bytes_per_param)

    # Actual achieved rates
    actual_flops = flops_per_token * tokens_per_sec
    actual_bandwidth_bytes = bytes_per_token * tokens_per_sec
    actual_bandwidth_gb_s = actual_bandwidth_bytes / 1e9

    # Peak rates across all GPUs
    peak_flops = gpu_peak_tflops * 1e12 * num_gpus
    peak_bandwidth_gb_s = gpu_peak_bandwidth_gb_s * num_gpus

    # MFU and MBU
    mfu_pct = (actual_flops / peak_flops * 100.0) if peak_flops > 0 else 0.0
    mbu_pct = (
        (actual_bandwidth_gb_s / peak_bandwidth_gb_s * 100.0)
        if peak_bandwidth_gb_s > 0
        else 0.0
    )

    # Intelligence Per Joule
    ipj = (accuracy / energy_joules) if energy_joules > 0 else 0.0

    return EfficiencyMetrics(
        mfu_pct=mfu_pct,
        mbu_pct=mbu_pct,
        actual_flops=actual_flops,
        peak_flops=peak_flops,
        actual_bandwidth_gb_s=actual_bandwidth_gb_s,
        peak_bandwidth_gb_s=peak_bandwidth_gb_s,
        ipj=ipj,
    )


__all__ = [
    "EfficiencyMetrics",
    "compute_efficiency",
    "estimate_model_bytes_per_token",
    "estimate_model_flops_per_token",
]
