//! GRPORouterPolicy — softmax sampling with group relative advantage.

use crate::traits::RouterPolicy;
use openjarvis_core::RoutingContext;
use parking_lot::Mutex;
use rand::prelude::*;
use std::collections::HashMap;

pub struct GRPORouterPolicy {
    models: Vec<String>,
    weights: Mutex<HashMap<String, f64>>,
    temperature: f64,
}

impl GRPORouterPolicy {
    pub fn new(models: Vec<String>, temperature: f64) -> Self {
        let weights = models
            .iter()
            .map(|m| (m.clone(), 0.0))
            .collect();
        Self {
            models,
            weights: Mutex::new(weights),
            temperature,
        }
    }

    pub fn update_weights(&self, rewards: &[(String, f64)]) {
        if rewards.is_empty() {
            return;
        }

        let mean_reward: f64 =
            rewards.iter().map(|(_, r)| r).sum::<f64>() / rewards.len() as f64;
        let std_reward: f64 = {
            let var = rewards
                .iter()
                .map(|(_, r)| (r - mean_reward).powi(2))
                .sum::<f64>()
                / rewards.len() as f64;
            var.sqrt().max(1e-8)
        };

        let mut weights = self.weights.lock();
        for (model, reward) in rewards {
            let advantage = (reward - mean_reward) / std_reward;
            let w = weights.entry(model.clone()).or_insert(0.0);
            *w += 0.1 * advantage;
        }
    }

    fn softmax_sample(&self) -> String {
        let weights = self.weights.lock();
        let mut rng = rand::rng();

        let logits: Vec<f64> = self
            .models
            .iter()
            .map(|m| weights.get(m).copied().unwrap_or(0.0) / self.temperature)
            .collect();

        let max_logit = logits.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let exp_sum: f64 = logits.iter().map(|l| (l - max_logit).exp()).sum();
        let probs: Vec<f64> = logits
            .iter()
            .map(|l| (l - max_logit).exp() / exp_sum)
            .collect();

        let u: f64 = rng.random();
        let mut cumulative = 0.0;
        for (i, p) in probs.iter().enumerate() {
            cumulative += p;
            if u < cumulative {
                return self.models[i].clone();
            }
        }
        self.models.last().unwrap().clone()
    }
}

impl RouterPolicy for GRPORouterPolicy {
    fn select_model(&self, _context: &RoutingContext) -> String {
        if self.models.is_empty() {
            return String::new();
        }
        self.softmax_sample()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_grpo_selection() {
        let policy = GRPORouterPolicy::new(
            vec!["m1".into(), "m2".into()],
            1.0,
        );
        let ctx = RoutingContext::default();
        let selected = policy.select_model(&ctx);
        assert!(!selected.is_empty());
    }

    #[test]
    fn test_grpo_update_biases() {
        let policy = GRPORouterPolicy::new(
            vec!["good".into(), "bad".into()],
            0.5,
        );

        let rewards = vec![
            ("good".into(), 0.9),
            ("good".into(), 0.85),
            ("bad".into(), 0.1),
            ("bad".into(), 0.15),
        ];
        policy.update_weights(&rewards);

        let mut good_count = 0;
        let ctx = RoutingContext::default();
        for _ in 0..100 {
            if policy.select_model(&ctx) == "good" {
                good_count += 1;
            }
        }
        assert!(good_count > 30, "good model should be favored");
    }
}
