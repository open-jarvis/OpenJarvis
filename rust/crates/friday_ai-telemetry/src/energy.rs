//! Energy monitoring — EnergyMonitor trait and vendor implementations.

/// Energy measurement from a monitoring period.
#[derive(Debug, Clone, Default)]
pub struct EnergyReading {
    pub energy_joules: f64,
    pub power_watts: f64,
    pub gpu_utilization_pct: f64,
    pub gpu_temperature_c: f64,
    pub gpu_memory_used_gb: f64,
}

/// ABC for energy monitoring implementations.
pub trait EnergyMonitor: Send + Sync {
    fn monitor_id(&self) -> &str;
    fn start(&mut self);
    fn stop(&mut self) -> EnergyReading;
    fn is_available(&self) -> bool;
}

/// Stub NVIDIA energy monitor (feature-gated in production).
pub struct NvidiaEnergyMonitor;

impl EnergyMonitor for NvidiaEnergyMonitor {
    fn monitor_id(&self) -> &str {
        "nvidia"
    }
    fn start(&mut self) {}
    fn stop(&mut self) -> EnergyReading {
        EnergyReading::default()
    }
    fn is_available(&self) -> bool {
        false
    }
}

/// Steady-state detector (CV-based thermal equilibrium).
pub struct SteadyStateDetector {
    readings: Vec<f64>,
    window_size: usize,
    cv_threshold: f64,
}

impl SteadyStateDetector {
    pub fn new(window_size: usize, cv_threshold: f64) -> Self {
        Self {
            readings: Vec::new(),
            window_size,
            cv_threshold,
        }
    }

    pub fn add_reading(&mut self, value: f64) {
        self.readings.push(value);
        if self.readings.len() > self.window_size {
            self.readings.remove(0);
        }
    }

    pub fn is_steady(&self) -> bool {
        if self.readings.len() < self.window_size {
            return false;
        }
        let mean = self.readings.iter().sum::<f64>() / self.readings.len() as f64;
        if mean.abs() < 1e-9 {
            return true;
        }
        let variance = self
            .readings
            .iter()
            .map(|x| (x - mean).powi(2))
            .sum::<f64>()
            / self.readings.len() as f64;
        let cv = variance.sqrt() / mean.abs();
        cv < self.cv_threshold
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_steady_state_detector() {
        let mut detector = SteadyStateDetector::new(5, 0.05);
        for _ in 0..5 {
            detector.add_reading(100.0);
        }
        assert!(detector.is_steady());
    }

    #[test]
    fn test_non_steady_state() {
        let mut detector = SteadyStateDetector::new(5, 0.05);
        for i in 0..5 {
            detector.add_reading(i as f64 * 50.0);
        }
        assert!(!detector.is_steady());
    }
}
