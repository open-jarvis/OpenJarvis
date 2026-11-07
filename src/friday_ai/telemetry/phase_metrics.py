"""Phase metrics computation -- prefill/decode energy separation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from friday_ai.telemetry.session import TelemetrySession


def compute_phase_metrics(
    session: TelemetrySession,
    start_ns: int,
    end_ns: int,
    tokens: int,
) -> dict:
    """Compute energy/power metrics for a phase window."""
    gpu_j, cpu_j = session.energy_delta(start_ns, end_ns)
    gpu_w, cpu_w = session.avg_power(start_ns, end_ns)
    duration_s = (end_ns - start_ns) / 1e9
    energy_per_token = gpu_j / tokens if tokens > 0 else 0.0
    return {
        "energy_j": gpu_j,
        "cpu_energy_j": cpu_j,
        "mean_power_w": gpu_w,
        "cpu_mean_power_w": cpu_w,
        "duration_s": duration_s,
        "energy_per_token_j": energy_per_token,
        "tokens": tokens,
    }


def split_at_ttft(
    session: TelemetrySession,
    start_ns: int,
    ttft_ns: int,
    end_ns: int,
    input_tokens: int,
    output_tokens: int,
) -> tuple[dict, dict]:
    """Split energy at TTFT boundary into prefill and decode phases."""
    prefill = compute_phase_metrics(session, start_ns, ttft_ns, input_tokens)
    decode = compute_phase_metrics(session, ttft_ns, end_ns, output_tokens)
    return (prefill, decode)
