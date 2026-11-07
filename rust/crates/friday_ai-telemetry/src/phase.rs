//! Phase-level metrics: energy, power, and per-token efficiency for prefill/decode phases.

use crate::session::TelemetrySample;

/// Aggregated metrics for a single inference phase (e.g., prefill or decode).
#[derive(Debug, Clone, Default)]
pub struct PhaseMetrics {
    pub energy_j: f64,
    pub mean_power_w: f64,
    pub duration_s: f64,
    pub energy_per_token_j: f64,
    pub tokens: u64,
}

/// Compute phase metrics from telemetry samples within a time range.
///
/// Uses trapezoidal integration for energy and simple averaging for power.
/// `tokens` is used to compute per-token energy.
pub fn compute_phase_metrics(
    samples: &[TelemetrySample],
    start_ns: u64,
    end_ns: u64,
    tokens: u64,
) -> PhaseMetrics {
    let duration_s = (end_ns.saturating_sub(start_ns)) as f64 / 1e9;

    // Filter samples within the window
    let in_range: Vec<&TelemetrySample> = samples
        .iter()
        .filter(|s| s.timestamp_ns >= start_ns && s.timestamp_ns <= end_ns)
        .collect();

    if in_range.is_empty() {
        return PhaseMetrics {
            duration_s,
            tokens,
            ..Default::default()
        };
    }

    // Trapezoidal integration for total energy (GPU + CPU combined)
    let mut energy_j = 0.0;
    for pair in in_range.windows(2) {
        let dt_s = (pair[1].timestamp_ns - pair[0].timestamp_ns) as f64 / 1e9;
        let total_power_0 = pair[0].gpu_power_w + pair[0].cpu_power_w;
        let total_power_1 = pair[1].gpu_power_w + pair[1].cpu_power_w;
        energy_j += (total_power_0 + total_power_1) / 2.0 * dt_s;
    }

    // Mean total power
    let mean_power_w: f64 = in_range
        .iter()
        .map(|s| s.gpu_power_w + s.cpu_power_w)
        .sum::<f64>()
        / in_range.len() as f64;

    let energy_per_token_j = if tokens > 0 {
        energy_j / tokens as f64
    } else {
        0.0
    };

    PhaseMetrics {
        energy_j,
        mean_power_w,
        duration_s,
        energy_per_token_j,
        tokens,
    }
}

/// Split samples at the TTFT boundary into prefill and decode phases.
///
/// - Prefill phase: [start_ns, ttft_ns] with `input_tokens`
/// - Decode phase: (ttft_ns, end_ns] with `output_tokens`
///
/// Returns `(prefill_metrics, decode_metrics)`.
pub fn split_at_ttft(
    samples: &[TelemetrySample],
    start_ns: u64,
    ttft_ns: u64,
    end_ns: u64,
    input_tokens: u64,
    output_tokens: u64,
) -> (PhaseMetrics, PhaseMetrics) {
    let prefill = compute_phase_metrics(samples, start_ns, ttft_ns, input_tokens);
    let decode = compute_phase_metrics(samples, ttft_ns, end_ns, output_tokens);
    (prefill, decode)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_sample(ts_ns: u64, gpu_w: f64, cpu_w: f64) -> TelemetrySample {
        TelemetrySample {
            timestamp_ns: ts_ns,
            gpu_power_w: gpu_w,
            cpu_power_w: cpu_w,
            ..Default::default()
        }
    }

    #[test]
    fn phase_metrics_constant_power() {
        let samples = vec![
            make_sample(0, 200.0, 100.0),
            make_sample(500_000_000, 200.0, 100.0),
            make_sample(1_000_000_000, 200.0, 100.0),
        ];
        let m = compute_phase_metrics(&samples, 0, 1_000_000_000, 100);

        assert!((m.duration_s - 1.0).abs() < 1e-9);
        assert!((m.energy_j - 300.0).abs() < 1e-9); // 300W * 1s
        assert!((m.mean_power_w - 300.0).abs() < 1e-9);
        assert!((m.energy_per_token_j - 3.0).abs() < 1e-9); // 300J / 100 tokens
        assert_eq!(m.tokens, 100);
    }

    #[test]
    fn phase_metrics_empty_samples() {
        let m = compute_phase_metrics(&[], 0, 1_000_000_000, 10);
        assert!((m.duration_s - 1.0).abs() < 1e-9);
        assert_eq!(m.energy_j, 0.0);
        assert_eq!(m.mean_power_w, 0.0);
        assert_eq!(m.energy_per_token_j, 0.0);
    }

    #[test]
    fn phase_metrics_zero_tokens() {
        let samples = vec![
            make_sample(0, 100.0, 50.0),
            make_sample(1_000_000_000, 100.0, 50.0),
        ];
        let m = compute_phase_metrics(&samples, 0, 1_000_000_000, 0);
        assert_eq!(m.energy_per_token_j, 0.0);
    }

    #[test]
    fn phase_metrics_single_sample() {
        let samples = vec![make_sample(500_000_000, 200.0, 100.0)];
        let m = compute_phase_metrics(&samples, 0, 1_000_000_000, 50);
        // Single sample -> no trapezoids, energy = 0
        assert_eq!(m.energy_j, 0.0);
        assert!((m.mean_power_w - 300.0).abs() < 1e-9);
    }

    #[test]
    fn phase_metrics_ramp() {
        // GPU: 0 -> 200W, CPU: 0 -> 100W over 1 second
        let samples = vec![
            make_sample(0, 0.0, 0.0),
            make_sample(1_000_000_000, 200.0, 100.0),
        ];
        let m = compute_phase_metrics(&samples, 0, 1_000_000_000, 10);
        // Trapezoidal: (0+300)/2 * 1.0 = 150 J
        assert!((m.energy_j - 150.0).abs() < 1e-9);
        assert!((m.energy_per_token_j - 15.0).abs() < 1e-9);
    }

    #[test]
    fn split_at_ttft_basic() {
        let samples = vec![
            make_sample(0, 300.0, 100.0),             // prefill start
            make_sample(500_000_000, 300.0, 100.0),    // prefill end / TTFT
            make_sample(500_000_000, 200.0, 80.0),     // decode start (at TTFT)
            make_sample(1_000_000_000, 200.0, 80.0),   // decode mid
            make_sample(2_000_000_000, 200.0, 80.0),   // decode end
        ];

        let (prefill, decode) = split_at_ttft(
            &samples,
            0,
            500_000_000,
            2_000_000_000,
            128,
            256,
        );

        assert!((prefill.duration_s - 0.5).abs() < 1e-9);
        assert_eq!(prefill.tokens, 128);

        assert!((decode.duration_s - 1.5).abs() < 1e-9);
        assert_eq!(decode.tokens, 256);
        assert!(decode.energy_j > 0.0);
    }

    #[test]
    fn phase_metrics_filters_outside_window() {
        let samples = vec![
            make_sample(0, 999.0, 999.0),               // before window
            make_sample(1_000_000_000, 100.0, 50.0),    // in window
            make_sample(2_000_000_000, 100.0, 50.0),    // in window
            make_sample(9_000_000_000, 999.0, 999.0),   // after window
        ];
        let m = compute_phase_metrics(&samples, 1_000_000_000, 2_000_000_000, 20);
        // Only the two in-window samples contribute
        assert!((m.energy_j - 150.0).abs() < 1e-9); // (150+150)/2 * 1s
        assert!((m.mean_power_w - 150.0).abs() < 1e-9);
    }
}
