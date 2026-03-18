//! FLOPs estimation and Model FLOPs Utilization (MFU) computation.

/// Peak TFLOPS (FP16/BF16) for common GPU/accelerator models.
pub const GPU_PEAK_TFLOPS: &[(&str, f64)] = &[
    ("H100", 989.0),
    ("H200", 989.0),
    ("A100", 312.0),
    ("A10G", 31.2),
    ("L4", 30.3),
    ("L40", 181.0),
    ("L40S", 362.0),
    ("T4", 65.1),
    ("V100", 125.0),
    ("4090", 82.6),
    ("4080", 48.7),
    ("3090", 35.6),
    ("M3 Max", 14.2),
    ("M3 Ultra", 27.0),
    ("M4 Max", 18.0),
];

/// Approximate parameter counts (billions) for common models.
pub const MODEL_PARAMS: &[(&str, f64)] = &[
    ("qwen3:8b", 8.0),
    ("llama-3.1-70b", 70.0),
    ("llama-3.1-8b", 8.0),
    ("mistral-7b", 7.0),
    ("mixtral-8x7b", 47.0),
    ("gpt-4o", 200.0),
    ("claude-opus", 137.0),
    ("gemini-pro", 137.0),
];

/// Look up a value in a `&[(&str, f64)]` table using case-insensitive substring matching.
fn lookup(table: &[(&str, f64)], key: &str) -> Option<f64> {
    let key_lower = key.to_lowercase();
    // Try exact match first (case-insensitive)
    for &(name, val) in table {
        if name.to_lowercase() == key_lower {
            return Some(val);
        }
    }
    // Fall back to substring match
    for &(name, val) in table {
        if key_lower.contains(&name.to_lowercase()) || name.to_lowercase().contains(&key_lower) {
            return Some(val);
        }
    }
    None
}

/// Estimate FLOPs for a model inference using the `2 * params * tokens` approximation.
/// Assumes KV caching (each token processed once).
///
/// Returns `(total_flops, flops_per_token)`. If the model is not found in `MODEL_PARAMS`,
/// returns `(0.0, 0.0)`.
pub fn estimate_flops(model: &str, input_tokens: u64, output_tokens: u64) -> (f64, f64) {
    let params_b = match lookup(MODEL_PARAMS, model) {
        Some(p) => p,
        None => return (0.0, 0.0),
    };

    let total_tokens = input_tokens + output_tokens;
    if total_tokens == 0 {
        return (0.0, 0.0);
    }

    let params = params_b * 1e9;
    // 2 * params * tokens approximation for transformer FLOPs
    let total_flops = 2.0 * params * total_tokens as f64;
    let flops_per_token = 2.0 * params;

    (total_flops, flops_per_token)
}

/// Estimate FLOPs without KV caching (full recompute per token).
///
/// Without KV cache, each token is re-processed for every subsequent token.
/// FLOPs = P * N * (N + 1) where P = params, N = total_tokens.
///
/// Returns `(total_flops, flops_per_token_avg)`. If the model is not found,
/// returns `(0.0, 0.0)`.
pub fn estimate_flops_no_kv_cache(
    model: &str,
    input_tokens: u64,
    output_tokens: u64,
) -> (f64, f64) {
    let params_b = match lookup(MODEL_PARAMS, model) {
        Some(p) => p,
        None => return (0.0, 0.0),
    };

    let total_tokens = input_tokens + output_tokens;
    if total_tokens == 0 {
        return (0.0, 0.0);
    }

    let params = params_b * 1e9;
    let n = total_tokens as f64;
    let total_flops = params * n * (n + 1.0);
    let flops_per_token = total_flops / n;

    (total_flops, flops_per_token)
}

/// Compute Model FLOPs Utilization (MFU).
///
/// MFU = actual_flops / (peak_tflops * 1e12 * duration_s * num_gpus)
///
/// Returns 0.0 if the GPU is not found or inputs are zero.
pub fn compute_mfu(flops: f64, duration_s: f64, gpu_name: &str, num_gpus: u32) -> f64 {
    if duration_s <= 0.0 || num_gpus == 0 || flops <= 0.0 {
        return 0.0;
    }

    let peak_tflops = match lookup(GPU_PEAK_TFLOPS, gpu_name) {
        Some(p) => p,
        None => return 0.0,
    };

    let peak_flops_per_sec = peak_tflops * 1e12 * num_gpus as f64;
    let theoretical_flops = peak_flops_per_sec * duration_s;

    flops / theoretical_flops
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn estimate_flops_known_model() {
        let (total, per_token) = estimate_flops("qwen3:8b", 100, 50);
        // 2 * 8e9 * 150 = 2.4e12
        assert!((total - 2.4e12).abs() < 1e3);
        // 2 * 8e9 = 16e9
        assert!((per_token - 16e9).abs() < 1e3);
    }

    #[test]
    fn estimate_flops_unknown_model() {
        let (total, per_token) = estimate_flops("unknown-model", 100, 50);
        assert_eq!(total, 0.0);
        assert_eq!(per_token, 0.0);
    }

    #[test]
    fn estimate_flops_zero_tokens() {
        let (total, per_token) = estimate_flops("qwen3:8b", 0, 0);
        assert_eq!(total, 0.0);
        assert_eq!(per_token, 0.0);
    }

    #[test]
    fn estimate_flops_large_model() {
        let (total, _) = estimate_flops("llama-3.1-70b", 1000, 500);
        // 2 * 70e9 * 1500 = 210e12
        assert!((total - 210e12).abs() < 1e3);
    }

    #[test]
    fn compute_mfu_basic() {
        // 1e12 FLOPs in 1 second on a single H100 (989 TFLOPS)
        let mfu = compute_mfu(1e12, 1.0, "H100", 1);
        // MFU = 1e12 / (989e12) ~= 0.001011
        let expected = 1e12 / (989.0 * 1e12);
        assert!((mfu - expected).abs() < 1e-9, "mfu = {mfu}, expected = {expected}");
    }

    #[test]
    fn compute_mfu_multi_gpu() {
        let mfu_1 = compute_mfu(1e12, 1.0, "A100", 1);
        let mfu_4 = compute_mfu(1e12, 1.0, "A100", 4);
        // 4 GPUs -> 4x theoretical -> 1/4 MFU for same actual FLOPs
        assert!((mfu_1 - 4.0 * mfu_4).abs() < 1e-12);
    }

    #[test]
    fn compute_mfu_unknown_gpu() {
        let mfu = compute_mfu(1e12, 1.0, "unknown-gpu", 1);
        assert_eq!(mfu, 0.0);
    }

    #[test]
    fn compute_mfu_zero_duration() {
        let mfu = compute_mfu(1e12, 0.0, "H100", 1);
        assert_eq!(mfu, 0.0);
    }

    #[test]
    fn compute_mfu_zero_gpus() {
        let mfu = compute_mfu(1e12, 1.0, "H100", 0);
        assert_eq!(mfu, 0.0);
    }

    #[test]
    fn compute_mfu_zero_flops() {
        let mfu = compute_mfu(0.0, 1.0, "H100", 1);
        assert_eq!(mfu, 0.0);
    }

    #[test]
    fn lookup_case_insensitive() {
        assert!(lookup(GPU_PEAK_TFLOPS, "h100").is_some());
        assert!(lookup(GPU_PEAK_TFLOPS, "H100").is_some());
    }

    #[test]
    fn lookup_substring_match() {
        // "NVIDIA RTX 4090" should match "4090"
        assert!(lookup(GPU_PEAK_TFLOPS, "NVIDIA RTX 4090").is_some());
        assert!(lookup(MODEL_PARAMS, "mistral-7b-instruct").is_some());
    }

    #[test]
    fn all_gpus_have_positive_tflops() {
        for &(name, tflops) in GPU_PEAK_TFLOPS {
            assert!(tflops > 0.0, "{name} has non-positive TFLOPS: {tflops}");
        }
    }

    #[test]
    fn all_models_have_positive_params() {
        for &(name, params) in MODEL_PARAMS {
            assert!(params > 0.0, "{name} has non-positive params: {params}");
        }
    }
}
