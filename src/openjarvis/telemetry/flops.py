"""FLOPs estimation and Model FLOPs Utilization (MFU) computation."""

from __future__ import annotations

GPU_PEAK_TFLOPS_BF16: dict[str, float] = {
    "H100": 989.0,
    "H200": 989.0,
    "A100": 312.0,
    "A10G": 31.2,
    "L4": 30.3,
    "L40": 181.0,
    "L40S": 362.0,
    "T4": 65.1,
    "V100": 125.0,
    "4090": 82.6,
    "4080": 48.7,
    "3090": 35.6,
    "M3 Max": 14.2,
    "M3 Ultra": 27.0,
    "M4 Max": 18.0,
}

MODEL_PARAMS_B: dict[str, float] = {
    "qwen3:8b": 8.0,
    "qwen3:0.6b": 0.6,
    "qwen3:4b": 4.0,
    "llama-3.1-70b": 70.0,
    "llama-3.1-8b": 8.0,
    "mistral-7b": 7.0,
    "mixtral-8x7b": 47.0,
}


def _get_params_b(model: str) -> float:
    """Look up model parameter count (billions)."""
    params_b = MODEL_PARAMS_B.get(model, 0.0)
    if params_b == 0.0:
        for key, val in MODEL_PARAMS_B.items():
            if model.startswith(key.split(":")[0]):
                params_b = val
                break
    return params_b


def estimate_flops(
    model: str, input_tokens: int, output_tokens: int
) -> tuple[float, float]:
    """Estimate FLOPs for an inference pass (assumes KV caching).

    Uses the 2 * P * T approximation where P = params, T = total tokens.
    Returns (total_flops, flops_per_token).

    ``input_tokens`` must include system-prompt tokens and must *not*
    be reduced for KV-cache reuse — it should represent the full prompt
    size that was sent to the engine.
    """
    params_b = _get_params_b(model)
    total_tokens = input_tokens + output_tokens
    params = params_b * 1e9
    total_flops = 2.0 * params * total_tokens
    flops_per_token = 2.0 * params if total_tokens > 0 else 0.0
    return (total_flops, flops_per_token)


def estimate_flops_no_kv_cache(
    model: str, input_tokens: int, output_tokens: int
) -> tuple[float, float]:
    """Estimate FLOPs without KV caching (full recompute per token).

    Without KV cache, each token is re-processed for every subsequent token.
    FLOPs = P * N * (N + 1) where P = params, N = total_tokens.
    Returns (total_flops, flops_per_token_avg).
    """
    params_b = _get_params_b(model)
    total_tokens = input_tokens + output_tokens
    if total_tokens == 0:
        return (0.0, 0.0)
    params = params_b * 1e9
    total_flops = params * total_tokens * (total_tokens + 1)
    flops_per_token = total_flops / total_tokens
    return (total_flops, flops_per_token)


def compute_mfu(
    flops: float, duration_s: float, gpu_name: str, num_gpus: int = 1
) -> float:
    """Compute Model FLOPs Utilization.

    MFU = actual_tflops / (peak_tflops * num_gpus)
    """
    peak = GPU_PEAK_TFLOPS_BF16.get(gpu_name, 0.0)
    if peak == 0.0:
        # Try substring matching
        for key, val in GPU_PEAK_TFLOPS_BF16.items():
            if key.lower() in gpu_name.lower():
                peak = val
                break
    if peak <= 0 or duration_s <= 0:
        return 0.0
    actual_tflops = flops / (duration_s * 1e12)
    return (actual_tflops / (peak * num_gpus)) * 100.0
