//! Ring-buffer backed telemetry session for high-frequency power/energy sampling.

use parking_lot::RwLock;

/// Single telemetry sample with nanosecond timestamp.
#[derive(Debug, Clone, Default)]
pub struct TelemetrySample {
    pub timestamp_ns: u64,
    pub gpu_power_w: f64,
    pub cpu_power_w: f64,
    pub gpu_energy_j: f64,
    pub cpu_energy_j: f64,
    pub gpu_util_pct: f64,
    pub gpu_temp_c: f64,
    pub gpu_mem_gb: f64,
}

/// Fixed-capacity ring buffer with O(1) push and O(log n) window queries.
pub struct RingBuffer<T> {
    data: Vec<Option<T>>,
    head: usize,
    len: usize,
    cap: usize,
}

impl<T: Clone> RingBuffer<T> {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0, "RingBuffer capacity must be > 0");
        Self {
            data: (0..capacity).map(|_| None).collect(),
            head: 0,
            len: 0,
            cap: capacity,
        }
    }

    /// Push an item, overwriting the oldest when full.
    pub fn push(&mut self, item: T) {
        self.data[self.head] = Some(item);
        self.head = (self.head + 1) % self.cap;
        if self.len < self.cap {
            self.len += 1;
        }
    }

    pub fn len(&self) -> usize {
        self.len
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    pub fn clear(&mut self) {
        for slot in self.data.iter_mut() {
            *slot = None;
        }
        self.head = 0;
        self.len = 0;
    }

    /// Return items ordered oldest to newest.
    pub fn as_ordered(&self) -> Vec<&T> {
        if self.len == 0 {
            return Vec::new();
        }
        let mut result = Vec::with_capacity(self.len);
        // Start index is where the oldest element lives
        let start = if self.len < self.cap {
            0
        } else {
            self.head // head points to the next write position = oldest element when full
        };
        for i in 0..self.len {
            let idx = (start + i) % self.cap;
            if let Some(ref item) = self.data[idx] {
                result.push(item);
            }
        }
        result
    }
}

/// Core telemetry session using ring buffer.
pub struct TelemetrySessionCore {
    buffer: RwLock<RingBuffer<TelemetrySample>>,
    sampling_interval_ms: u64,
}

impl TelemetrySessionCore {
    pub fn new(capacity: usize, sampling_interval_ms: u64) -> Self {
        Self {
            buffer: RwLock::new(RingBuffer::new(capacity)),
            sampling_interval_ms,
        }
    }

    pub fn sampling_interval_ms(&self) -> u64 {
        self.sampling_interval_ms
    }

    pub fn add_sample(&self, sample: TelemetrySample) {
        self.buffer.write().push(sample);
    }

    /// Return samples within [start_ns, end_ns] using binary search on monotonic timestamps.
    pub fn window(&self, start_ns: u64, end_ns: u64) -> Vec<TelemetrySample> {
        let buf = self.buffer.read();
        let ordered = buf.as_ordered();
        if ordered.is_empty() {
            return Vec::new();
        }

        // Binary search for first element >= start_ns
        let lo = match ordered.binary_search_by(|s| s.timestamp_ns.cmp(&start_ns)) {
            Ok(i) => i,
            Err(i) => i,
        };

        // Binary search for last element <= end_ns
        let hi = match ordered.binary_search_by(|s| s.timestamp_ns.cmp(&end_ns)) {
            Ok(i) => i + 1,
            Err(i) => i,
        };

        ordered[lo..hi].iter().map(|s| (*s).clone()).collect()
    }

    /// Compute energy delta via trapezoidal integration of power samples.
    /// Returns (gpu_energy_j, cpu_energy_j).
    pub fn compute_energy_delta(&self, start_ns: u64, end_ns: u64) -> (f64, f64) {
        let samples = self.window(start_ns, end_ns);
        if samples.len() < 2 {
            return (0.0, 0.0);
        }

        let mut gpu_j = 0.0;
        let mut cpu_j = 0.0;
        for pair in samples.windows(2) {
            let dt_s = (pair[1].timestamp_ns - pair[0].timestamp_ns) as f64 / 1e9;
            // Trapezoidal rule: area = (a + b) / 2 * dt
            gpu_j += (pair[0].gpu_power_w + pair[1].gpu_power_w) / 2.0 * dt_s;
            cpu_j += (pair[0].cpu_power_w + pair[1].cpu_power_w) / 2.0 * dt_s;
        }

        (gpu_j, cpu_j)
    }

    /// Average power (gpu_w, cpu_w) in the given time window.
    pub fn compute_avg_power(&self, start_ns: u64, end_ns: u64) -> (f64, f64) {
        let samples = self.window(start_ns, end_ns);
        if samples.is_empty() {
            return (0.0, 0.0);
        }
        let n = samples.len() as f64;
        let gpu_sum: f64 = samples.iter().map(|s| s.gpu_power_w).sum();
        let cpu_sum: f64 = samples.iter().map(|s| s.cpu_power_w).sum();
        (gpu_sum / n, cpu_sum / n)
    }

    pub fn len(&self) -> usize {
        self.buffer.read().len()
    }

    pub fn is_empty(&self) -> bool {
        self.buffer.read().is_empty()
    }

    pub fn clear(&self) {
        self.buffer.write().clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ---- RingBuffer tests ----

    #[test]
    fn ring_buffer_basic_push_and_len() {
        let mut rb: RingBuffer<i32> = RingBuffer::new(4);
        assert!(rb.is_empty());
        assert_eq!(rb.len(), 0);

        rb.push(1);
        rb.push(2);
        rb.push(3);
        assert_eq!(rb.len(), 3);
        assert!(!rb.is_empty());
    }

    #[test]
    fn ring_buffer_ordered_no_wrap() {
        let mut rb: RingBuffer<i32> = RingBuffer::new(5);
        for i in 0..3 {
            rb.push(i);
        }
        let ordered: Vec<i32> = rb.as_ordered().into_iter().cloned().collect();
        assert_eq!(ordered, vec![0, 1, 2]);
    }

    #[test]
    fn ring_buffer_wrap_around() {
        let mut rb: RingBuffer<i32> = RingBuffer::new(3);
        rb.push(1);
        rb.push(2);
        rb.push(3);
        rb.push(4); // overwrites 1
        rb.push(5); // overwrites 2

        assert_eq!(rb.len(), 3);
        let ordered: Vec<i32> = rb.as_ordered().into_iter().cloned().collect();
        assert_eq!(ordered, vec![3, 4, 5]);
    }

    #[test]
    fn ring_buffer_clear() {
        let mut rb: RingBuffer<i32> = RingBuffer::new(3);
        rb.push(10);
        rb.push(20);
        rb.clear();
        assert!(rb.is_empty());
        assert_eq!(rb.len(), 0);
        assert!(rb.as_ordered().is_empty());
    }

    #[test]
    fn ring_buffer_single_capacity() {
        let mut rb: RingBuffer<i32> = RingBuffer::new(1);
        rb.push(42);
        assert_eq!(rb.len(), 1);
        rb.push(99);
        assert_eq!(rb.len(), 1);
        let ordered: Vec<i32> = rb.as_ordered().into_iter().cloned().collect();
        assert_eq!(ordered, vec![99]);
    }

    #[test]
    #[should_panic(expected = "capacity must be > 0")]
    fn ring_buffer_zero_capacity_panics() {
        let _rb: RingBuffer<i32> = RingBuffer::new(0);
    }

    #[test]
    fn ring_buffer_exact_fill() {
        let mut rb: RingBuffer<i32> = RingBuffer::new(4);
        for i in 0..4 {
            rb.push(i);
        }
        assert_eq!(rb.len(), 4);
        let ordered: Vec<i32> = rb.as_ordered().into_iter().cloned().collect();
        assert_eq!(ordered, vec![0, 1, 2, 3]);
    }

    // ---- TelemetrySessionCore tests ----

    fn make_sample(ts_ns: u64, gpu_w: f64, cpu_w: f64) -> TelemetrySample {
        TelemetrySample {
            timestamp_ns: ts_ns,
            gpu_power_w: gpu_w,
            cpu_power_w: cpu_w,
            ..Default::default()
        }
    }

    #[test]
    fn session_add_and_len() {
        let session = TelemetrySessionCore::new(100, 10);
        assert_eq!(session.len(), 0);
        assert!(session.is_empty());

        session.add_sample(make_sample(1_000_000, 100.0, 50.0));
        session.add_sample(make_sample(2_000_000, 110.0, 55.0));
        assert_eq!(session.len(), 2);
        assert!(!session.is_empty());
    }

    #[test]
    fn session_window_returns_correct_range() {
        let session = TelemetrySessionCore::new(100, 10);
        for i in 0..10 {
            session.add_sample(make_sample(i * 1_000_000, 100.0, 50.0));
        }

        let win = session.window(3_000_000, 6_000_000);
        assert_eq!(win.len(), 4); // timestamps 3, 4, 5, 6 (inclusive)
        assert_eq!(win[0].timestamp_ns, 3_000_000);
        assert_eq!(win[3].timestamp_ns, 6_000_000);
    }

    #[test]
    fn session_window_empty() {
        let session = TelemetrySessionCore::new(100, 10);
        let win = session.window(0, 1_000_000);
        assert!(win.is_empty());
    }

    #[test]
    fn session_window_no_match() {
        let session = TelemetrySessionCore::new(100, 10);
        session.add_sample(make_sample(1_000_000, 100.0, 50.0));
        session.add_sample(make_sample(2_000_000, 100.0, 50.0));

        let win = session.window(5_000_000, 10_000_000);
        assert!(win.is_empty());
    }

    #[test]
    fn session_energy_delta_trapezoidal() {
        let session = TelemetrySessionCore::new(100, 10);
        // 100W GPU, 50W CPU constant for 1 second (two samples 1s apart)
        session.add_sample(make_sample(0, 100.0, 50.0));
        session.add_sample(make_sample(1_000_000_000, 100.0, 50.0)); // 1s later

        let (gpu_j, cpu_j) = session.compute_energy_delta(0, 1_000_000_000);
        assert!((gpu_j - 100.0).abs() < 1e-9, "gpu_j = {gpu_j}");
        assert!((cpu_j - 50.0).abs() < 1e-9, "cpu_j = {cpu_j}");
    }

    #[test]
    fn session_energy_delta_linear_ramp() {
        let session = TelemetrySessionCore::new(100, 10);
        // GPU ramps from 0W to 200W over 1 second -> trapezoidal area = 100 J
        session.add_sample(make_sample(0, 0.0, 0.0));
        session.add_sample(make_sample(1_000_000_000, 200.0, 100.0));

        let (gpu_j, cpu_j) = session.compute_energy_delta(0, 1_000_000_000);
        assert!((gpu_j - 100.0).abs() < 1e-9, "gpu_j = {gpu_j}");
        assert!((cpu_j - 50.0).abs() < 1e-9, "cpu_j = {cpu_j}");
    }

    #[test]
    fn session_energy_delta_single_sample() {
        let session = TelemetrySessionCore::new(100, 10);
        session.add_sample(make_sample(0, 100.0, 50.0));

        let (gpu_j, cpu_j) = session.compute_energy_delta(0, 0);
        assert_eq!(gpu_j, 0.0);
        assert_eq!(cpu_j, 0.0);
    }

    #[test]
    fn session_avg_power() {
        let session = TelemetrySessionCore::new(100, 10);
        session.add_sample(make_sample(0, 100.0, 50.0));
        session.add_sample(make_sample(1_000_000, 200.0, 100.0));
        session.add_sample(make_sample(2_000_000, 150.0, 75.0));

        let (gpu_avg, cpu_avg) = session.compute_avg_power(0, 2_000_000);
        assert!((gpu_avg - 150.0).abs() < 1e-9);
        assert!((cpu_avg - 75.0).abs() < 1e-9);
    }

    #[test]
    fn session_avg_power_empty() {
        let session = TelemetrySessionCore::new(100, 10);
        let (gpu_avg, cpu_avg) = session.compute_avg_power(0, 1_000_000);
        assert_eq!(gpu_avg, 0.0);
        assert_eq!(cpu_avg, 0.0);
    }

    #[test]
    fn session_clear() {
        let session = TelemetrySessionCore::new(100, 10);
        session.add_sample(make_sample(0, 100.0, 50.0));
        session.clear();
        assert!(session.is_empty());
        assert_eq!(session.len(), 0);
    }

    #[test]
    fn session_ring_buffer_overflow() {
        let session = TelemetrySessionCore::new(3, 10);
        for i in 0..5 {
            session.add_sample(make_sample(i * 1_000_000, 100.0, 50.0));
        }
        assert_eq!(session.len(), 3);
        // Only the last 3 samples should remain (ts: 2, 3, 4 million)
        let win = session.window(0, 10_000_000);
        assert_eq!(win.len(), 3);
        assert_eq!(win[0].timestamp_ns, 2_000_000);
        assert_eq!(win[2].timestamp_ns, 4_000_000);
    }

    #[test]
    fn session_sampling_interval() {
        let session = TelemetrySessionCore::new(100, 42);
        assert_eq!(session.sampling_interval_ms(), 42);
    }
}
