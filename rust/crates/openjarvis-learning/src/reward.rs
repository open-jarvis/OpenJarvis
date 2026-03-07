//! Multi-objective reward function for orchestrator training.
//!
//! Ported from Python `openjarvis.learning.orchestrator.reward`.

use crate::orchestrator_types::Episode;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RewardWeights {
    pub alpha: f64,
    pub beta_cost: f64,
    pub beta_energy: f64,
    pub gamma_latency: f64,
    pub gamma_power: f64,
}

impl RewardWeights {
    pub fn new(
        alpha: f64,
        beta_cost: f64,
        beta_energy: f64,
        gamma_latency: f64,
        gamma_power: f64,
    ) -> Result<Self, String> {
        let total = alpha + beta_cost + beta_energy + gamma_latency + gamma_power;
        if (total - 1.0).abs() > 0.01 {
            return Err(format!("Weights should sum to 1.0, got {total}"));
        }
        Ok(Self {
            alpha,
            beta_cost,
            beta_energy,
            gamma_latency,
            gamma_power,
        })
    }

    pub fn total(&self) -> f64 {
        self.alpha + self.beta_cost + self.beta_energy + self.gamma_latency + self.gamma_power
    }
}

impl Default for RewardWeights {
    fn default() -> Self {
        Self {
            alpha: 0.4,
            beta_cost: 0.15,
            beta_energy: 0.15,
            gamma_latency: 0.15,
            gamma_power: 0.15,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Normalizers {
    pub energy_scale: f64,
    pub cost_scale: f64,
    pub latency_scale: f64,
    pub power_scale: f64,
}

impl Default for Normalizers {
    fn default() -> Self {
        Self {
            energy_scale: 100.0,
            cost_scale: 0.10,
            latency_scale: 30.0,
            power_scale: 200.0,
        }
    }
}

#[derive(Debug, Clone)]
pub struct MultiObjectiveReward {
    weights: RewardWeights,
    normalizers: Normalizers,
}

impl MultiObjectiveReward {
    pub fn new(weights: RewardWeights, normalizers: Normalizers) -> Self {
        Self {
            weights,
            normalizers,
        }
    }

    pub fn compute(&self, episode: &Episode) -> f64 {
        let accuracy_reward = if episode.correct { 1.0 } else { 0.0 };

        let cost_penalty = episode.total_cost_usd / self.normalizers.cost_scale;
        let energy_penalty = episode.total_energy_joules / self.normalizers.energy_scale;
        let latency_penalty = episode.total_latency_seconds / self.normalizers.latency_scale;
        let power_penalty = episode.max_power_watts / self.normalizers.power_scale;

        self.weights.alpha * accuracy_reward
            - self.weights.beta_cost * cost_penalty
            - self.weights.beta_energy * energy_penalty
            - self.weights.gamma_latency * latency_penalty
            - self.weights.gamma_power * power_penalty
    }

    pub fn compute_with_breakdown(&self, episode: &Episode) -> HashMap<String, f64> {
        let accuracy_reward = if episode.correct { 1.0 } else { 0.0 };

        let cost_penalty = episode.total_cost_usd / self.normalizers.cost_scale;
        let energy_penalty = episode.total_energy_joules / self.normalizers.energy_scale;
        let latency_penalty = episode.total_latency_seconds / self.normalizers.latency_scale;
        let power_penalty = episode.max_power_watts / self.normalizers.power_scale;

        let accuracy_component = self.weights.alpha * accuracy_reward;
        let cost_component = -self.weights.beta_cost * cost_penalty;
        let energy_component = -self.weights.beta_energy * energy_penalty;
        let latency_component = -self.weights.gamma_latency * latency_penalty;
        let power_component = -self.weights.gamma_power * power_penalty;

        let total_reward =
            accuracy_component + cost_component + energy_component + latency_component + power_component;
        let ipj = episode.compute_ipj();

        let mut breakdown = HashMap::new();
        breakdown.insert("total_reward".into(), total_reward);
        breakdown.insert("accuracy_reward".into(), accuracy_reward);
        breakdown.insert("accuracy_component".into(), accuracy_component);
        breakdown.insert("cost_penalty".into(), cost_penalty);
        breakdown.insert("cost_component".into(), cost_component);
        breakdown.insert("energy_penalty".into(), energy_penalty);
        breakdown.insert("energy_component".into(), energy_component);
        breakdown.insert("latency_penalty".into(), latency_penalty);
        breakdown.insert("latency_component".into(), latency_component);
        breakdown.insert("power_penalty".into(), power_penalty);
        breakdown.insert("power_component".into(), power_component);
        breakdown.insert("ipj".into(), ipj);
        breakdown.insert("total_energy_joules".into(), episode.total_energy_joules);
        breakdown.insert("total_cost_usd".into(), episode.total_cost_usd);
        breakdown.insert("total_latency_seconds".into(), episode.total_latency_seconds);
        breakdown
    }

    pub fn compute_batch(&self, episodes: &[Episode]) -> Vec<f64> {
        episodes.iter().map(|ep| self.compute(ep)).collect()
    }
}

// ---------------------------------------------------------------------------
// Adaptive reward weights — shift emphasis during training
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct AdaptiveRewardWeights {
    initial_alpha: f64,
    final_alpha: f64,
    initial_beta_cost: f64,
    final_beta_cost: f64,
    initial_beta_energy: f64,
    final_beta_energy: f64,
    initial_gamma_latency: f64,
    final_gamma_latency: f64,
    initial_gamma_power: f64,
    final_gamma_power: f64,
    total_steps: usize,
}

impl AdaptiveRewardWeights {
    pub fn new(
        initial_alpha: f64,
        final_alpha: f64,
        initial_beta_cost: f64,
        final_beta_cost: f64,
        initial_beta_energy: f64,
        final_beta_energy: f64,
        initial_gamma_latency: f64,
        final_gamma_latency: f64,
        initial_gamma_power: f64,
        final_gamma_power: f64,
        total_steps: usize,
    ) -> Self {
        Self {
            initial_alpha,
            final_alpha,
            initial_beta_cost,
            final_beta_cost,
            initial_beta_energy,
            final_beta_energy,
            initial_gamma_latency,
            final_gamma_latency,
            initial_gamma_power,
            final_gamma_power,
            total_steps,
        }
    }

    /// Get weights for `current_step` via linear interpolation, normalized to sum to 1.
    pub fn get_weights(&self, current_step: usize) -> RewardWeights {
        let progress = if self.total_steps == 0 {
            1.0
        } else {
            (current_step as f64 / self.total_steps as f64).min(1.0)
        };

        let lerp = |initial: f64, final_: f64| initial + (final_ - initial) * progress;

        let alpha = lerp(self.initial_alpha, self.final_alpha);
        let beta_cost = lerp(self.initial_beta_cost, self.final_beta_cost);
        let beta_energy = lerp(self.initial_beta_energy, self.final_beta_energy);
        let gamma_latency = lerp(self.initial_gamma_latency, self.final_gamma_latency);
        let gamma_power = lerp(self.initial_gamma_power, self.final_gamma_power);

        let total = alpha + beta_cost + beta_energy + gamma_latency + gamma_power;
        RewardWeights {
            alpha: alpha / total,
            beta_cost: beta_cost / total,
            beta_energy: beta_energy / total,
            gamma_latency: gamma_latency / total,
            gamma_power: gamma_power / total,
        }
    }
}

impl Default for AdaptiveRewardWeights {
    fn default() -> Self {
        Self {
            initial_alpha: 0.6,
            final_alpha: 0.3,
            initial_beta_cost: 0.1,
            final_beta_cost: 0.15,
            initial_beta_energy: 0.1,
            final_beta_energy: 0.2,
            initial_gamma_latency: 0.1,
            final_gamma_latency: 0.15,
            initial_gamma_power: 0.1,
            final_gamma_power: 0.2,
            total_steps: 10_000,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::orchestrator_types::{OrchestratorAction, OrchestratorObservation};

    fn make_episode(correct: bool, energy: f64, cost: f64, latency: f64, power: f64) -> Episode {
        let mut ep = Episode::new("test".into(), "prompt".into());
        ep.correct = correct;
        let action = OrchestratorAction {
            thought: "t".into(),
            tool_name: "tool".into(),
            tool_input: "in".into(),
            is_final_answer: false,
        };
        let obs = OrchestratorObservation {
            content: "out".into(),
            latency_seconds: latency,
            cost_usd: cost,
            energy_joules: energy,
            power_watts: power,
            tokens: 100,
        };
        ep.add_step(action, obs);
        ep
    }

    #[test]
    fn test_reward_weights_validation() {
        assert!(RewardWeights::new(0.4, 0.15, 0.15, 0.15, 0.15).is_ok());
        assert!(RewardWeights::new(0.5, 0.5, 0.5, 0.5, 0.5).is_err());
    }

    #[test]
    fn test_compute_correct_episode() {
        let reward = MultiObjectiveReward::new(RewardWeights::default(), Normalizers::default());
        let ep = make_episode(true, 10.0, 0.01, 5.0, 50.0);
        let r = reward.compute(&ep);
        assert!(r > 0.0, "correct episode should yield positive reward");
    }

    #[test]
    fn test_compute_incorrect_episode() {
        let reward = MultiObjectiveReward::new(RewardWeights::default(), Normalizers::default());
        let ep = make_episode(false, 10.0, 0.01, 5.0, 50.0);
        let r = reward.compute(&ep);
        assert!(r < 0.0, "incorrect episode with costs should be negative");
    }

    #[test]
    fn test_breakdown_keys() {
        let reward = MultiObjectiveReward::new(RewardWeights::default(), Normalizers::default());
        let ep = make_episode(true, 10.0, 0.01, 5.0, 50.0);
        let bd = reward.compute_with_breakdown(&ep);
        assert!(bd.contains_key("total_reward"));
        assert!(bd.contains_key("accuracy_component"));
        assert!(bd.contains_key("ipj"));
    }

    #[test]
    fn test_compute_batch() {
        let reward = MultiObjectiveReward::new(RewardWeights::default(), Normalizers::default());
        let episodes = vec![
            make_episode(true, 10.0, 0.01, 5.0, 50.0),
            make_episode(false, 20.0, 0.02, 10.0, 100.0),
        ];
        let results = reward.compute_batch(&episodes);
        assert_eq!(results.len(), 2);
        assert!(results[0] > results[1]);
    }

    #[test]
    fn test_adaptive_weights_start() {
        let adaptive = AdaptiveRewardWeights::default();
        let w = adaptive.get_weights(0);
        assert!((w.total() - 1.0).abs() < 0.01);
        assert!(w.alpha > 0.5, "early training should emphasize accuracy");
    }

    #[test]
    fn test_adaptive_weights_end() {
        let adaptive = AdaptiveRewardWeights::default();
        let w = adaptive.get_weights(10_000);
        assert!((w.total() - 1.0).abs() < 0.01);
        assert!(w.alpha < 0.35, "late training should reduce accuracy emphasis");
    }

    #[test]
    fn test_adaptive_weights_midpoint() {
        let adaptive = AdaptiveRewardWeights::default();
        let w_start = adaptive.get_weights(0);
        let w_mid = adaptive.get_weights(5_000);
        let w_end = adaptive.get_weights(10_000);
        assert!(w_mid.alpha < w_start.alpha);
        assert!(w_mid.alpha > w_end.alpha);
    }
}
