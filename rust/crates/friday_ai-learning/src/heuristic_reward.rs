//! Heuristic reward function — weighted score from latency, cost, efficiency.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HeuristicRewardFunction {
    pub weight_latency: f64,
    pub weight_cost: f64,
    pub weight_efficiency: f64,
    pub max_latency: f64,
    pub max_cost: f64,
}

impl Default for HeuristicRewardFunction {
    fn default() -> Self {
        Self::new(0.4, 0.3, 0.3, 30.0, 0.01)
    }
}

impl HeuristicRewardFunction {
    pub fn new(
        weight_latency: f64,
        weight_cost: f64,
        weight_efficiency: f64,
        max_latency: f64,
        max_cost: f64,
    ) -> Self {
        Self {
            weight_latency,
            weight_cost,
            weight_efficiency,
            max_latency,
            max_cost,
        }
    }

    /// Compute a scalar reward in `[0, 1]` from performance metrics.
    pub fn compute(
        &self,
        latency_seconds: f64,
        cost_usd: f64,
        prompt_tokens: u64,
        completion_tokens: u64,
    ) -> f64 {
        let total = prompt_tokens + completion_tokens;
        let lat_score = (1.0 - latency_seconds / self.max_latency).max(0.0);
        let cost_score = (1.0 - cost_usd / self.max_cost).max(0.0);
        let eff_score = if total > 0 {
            completion_tokens as f64 / total as f64
        } else {
            0.5
        };
        let reward =
            self.weight_latency * lat_score + self.weight_cost * cost_score + self.weight_efficiency * eff_score;
        reward.clamp(0.0, 1.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_weights() {
        let rf = HeuristicRewardFunction::default();
        assert!((rf.weight_latency - 0.4).abs() < f64::EPSILON);
        assert!((rf.weight_cost - 0.3).abs() < f64::EPSILON);
        assert!((rf.weight_efficiency - 0.3).abs() < f64::EPSILON);
    }

    #[test]
    fn test_perfect_score() {
        let rf = HeuristicRewardFunction::default();
        let reward = rf.compute(0.0, 0.0, 100, 100);
        // lat=1.0, cost=1.0, eff=0.5 → 0.4*1 + 0.3*1 + 0.3*0.5 = 0.85
        assert!((reward - 0.85).abs() < 1e-9);
    }

    #[test]
    fn test_high_latency_penalises() {
        let rf = HeuristicRewardFunction::default();
        let fast = rf.compute(1.0, 0.0, 50, 50);
        let slow = rf.compute(25.0, 0.0, 50, 50);
        assert!(fast > slow, "faster should score higher");
    }

    #[test]
    fn test_clamp_bounds() {
        let rf = HeuristicRewardFunction::default();
        let r = rf.compute(100.0, 1.0, 0, 0);
        assert!((0.0..=1.0).contains(&r));
    }
}
