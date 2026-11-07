//! Inter-token latency (ITL) statistics — percentiles, mean, min, max.

/// Aggregated inter-token latency statistics.
#[derive(Debug, Clone, Default)]
pub struct ItlStats {
    pub p50_ms: f64,
    pub p90_ms: f64,
    pub p95_ms: f64,
    pub p99_ms: f64,
    pub mean_ms: f64,
    pub min_ms: f64,
    pub max_ms: f64,
}

/// Compute inter-token latency statistics from token arrival timestamps.
///
/// `token_timestamps_ms` should be a slice of monotonically increasing timestamps
/// in milliseconds. At least 2 timestamps are needed to compute any latencies.
pub fn compute_itl_stats(token_timestamps_ms: &[f64]) -> ItlStats {
    if token_timestamps_ms.len() < 2 {
        return ItlStats::default();
    }

    // Compute inter-token latencies (consecutive diffs)
    let mut itls: Vec<f64> = token_timestamps_ms
        .windows(2)
        .map(|w| w[1] - w[0])
        .collect();

    // Sort for percentile computation
    itls.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    let n = itls.len();
    let mean_ms = itls.iter().sum::<f64>() / n as f64;
    let min_ms = itls[0];
    let max_ms = itls[n - 1];

    ItlStats {
        p50_ms: percentile(&itls, 50.0),
        p90_ms: percentile(&itls, 90.0),
        p95_ms: percentile(&itls, 95.0),
        p99_ms: percentile(&itls, 99.0),
        mean_ms,
        min_ms,
        max_ms,
    }
}

/// Compute a percentile from a sorted slice using linear interpolation.
fn percentile(sorted: &[f64], pct: f64) -> f64 {
    assert!(!sorted.is_empty());
    if sorted.len() == 1 {
        return sorted[0];
    }
    let rank = pct / 100.0 * (sorted.len() - 1) as f64;
    let lo = rank.floor() as usize;
    let hi = rank.ceil() as usize;
    if lo == hi {
        sorted[lo]
    } else {
        let frac = rank - lo as f64;
        sorted[lo] * (1.0 - frac) + sorted[hi] * frac
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn itl_stats_basic() {
        // 5 tokens at 0, 10, 20, 30, 40 ms -> ITLs = [10, 10, 10, 10]
        let timestamps = vec![0.0, 10.0, 20.0, 30.0, 40.0];
        let stats = compute_itl_stats(&timestamps);

        assert!((stats.mean_ms - 10.0).abs() < 1e-9);
        assert!((stats.min_ms - 10.0).abs() < 1e-9);
        assert!((stats.max_ms - 10.0).abs() < 1e-9);
        assert!((stats.p50_ms - 10.0).abs() < 1e-9);
        assert!((stats.p99_ms - 10.0).abs() < 1e-9);
    }

    #[test]
    fn itl_stats_varying_latencies() {
        // ITLs: [5, 10, 15, 20]
        let timestamps = vec![0.0, 5.0, 15.0, 30.0, 50.0];
        let stats = compute_itl_stats(&timestamps);
        // ITLs: [5, 10, 15, 20], sorted: [5, 10, 15, 20]

        assert!((stats.mean_ms - 12.5).abs() < 1e-9);
        assert!((stats.min_ms - 5.0).abs() < 1e-9);
        assert!((stats.max_ms - 20.0).abs() < 1e-9);

        // p50: rank = 0.5 * 3 = 1.5 -> interpolate between index 1 and 2
        // = 10 * 0.5 + 15 * 0.5 = 12.5
        assert!((stats.p50_ms - 12.5).abs() < 1e-9);
    }

    #[test]
    fn itl_stats_empty() {
        let stats = compute_itl_stats(&[]);
        assert_eq!(stats.mean_ms, 0.0);
        assert_eq!(stats.p50_ms, 0.0);
    }

    #[test]
    fn itl_stats_single_timestamp() {
        let stats = compute_itl_stats(&[100.0]);
        assert_eq!(stats.mean_ms, 0.0);
    }

    #[test]
    fn itl_stats_two_timestamps() {
        let stats = compute_itl_stats(&[0.0, 42.0]);
        // Single ITL of 42ms
        assert!((stats.mean_ms - 42.0).abs() < 1e-9);
        assert!((stats.min_ms - 42.0).abs() < 1e-9);
        assert!((stats.max_ms - 42.0).abs() < 1e-9);
        assert!((stats.p50_ms - 42.0).abs() < 1e-9);
        assert!((stats.p90_ms - 42.0).abs() < 1e-9);
        assert!((stats.p95_ms - 42.0).abs() < 1e-9);
        assert!((stats.p99_ms - 42.0).abs() < 1e-9);
    }

    #[test]
    fn itl_stats_percentile_interpolation() {
        // 10 ITLs: 1..=10
        let timestamps: Vec<f64> = {
            let mut ts = vec![0.0];
            for i in 1..=10 {
                ts.push(ts.last().unwrap() + i as f64);
            }
            ts
        };
        let stats = compute_itl_stats(&timestamps);
        // ITLs sorted: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

        assert!((stats.min_ms - 1.0).abs() < 1e-9);
        assert!((stats.max_ms - 10.0).abs() < 1e-9);
        assert!((stats.mean_ms - 5.5).abs() < 1e-9);

        // p50: rank = 0.5 * 9 = 4.5 -> interpolate idx 4 and 5 -> (5+6)/2 = 5.5
        assert!((stats.p50_ms - 5.5).abs() < 1e-9);

        // p90: rank = 0.9 * 9 = 8.1 -> interpolate idx 8 and 9 -> 9*0.9 + 10*0.1 = 9.1
        assert!((stats.p90_ms - 9.1).abs() < 1e-9);
    }

    #[test]
    fn percentile_function_edge_cases() {
        assert!((percentile(&[5.0], 50.0) - 5.0).abs() < 1e-9);
        assert!((percentile(&[1.0, 2.0], 0.0) - 1.0).abs() < 1e-9);
        assert!((percentile(&[1.0, 2.0], 100.0) - 2.0).abs() < 1e-9);
        assert!((percentile(&[1.0, 2.0], 50.0) - 1.5).abs() < 1e-9);
    }
}
