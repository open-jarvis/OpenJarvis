//! BanditRouterPolicy — Thompson Sampling / UCB1 for model selection.

use crate::traits::RouterPolicy;
use openjarvis_core::RoutingContext;
use parking_lot::Mutex;
use rand::prelude::*;
use std::collections::HashMap;

#[derive(Debug, Clone)]
struct ArmStats {
    successes: f64,
    failures: f64,
    total_reward: f64,
    count: usize,
}

impl Default for ArmStats {
    fn default() -> Self {
        Self {
            successes: 1.0,
            failures: 1.0,
            total_reward: 0.0,
            count: 0,
        }
    }
}

pub struct BanditRouterPolicy {
    models: Vec<String>,
    stats: Mutex<HashMap<String, ArmStats>>,
    strategy: BanditStrategy,
}

#[derive(Debug, Clone, Copy)]
pub enum BanditStrategy {
    ThompsonSampling,
    UCB1,
}

impl BanditRouterPolicy {
    pub fn new(models: Vec<String>, strategy: BanditStrategy) -> Self {
        Self {
            models,
            stats: Mutex::new(HashMap::new()),
            strategy,
        }
    }

    pub fn update(&self, model: &str, reward: f64) {
        let mut stats = self.stats.lock();
        let arm = stats.entry(model.to_string()).or_default();
        arm.count += 1;
        arm.total_reward += reward;
        if reward > 0.5 {
            arm.successes += 1.0;
        } else {
            arm.failures += 1.0;
        }
    }

    fn thompson_sample(&self) -> String {
        let stats = self.stats.lock();
        let mut rng = rand::rng();
        let mut best_model = self.models[0].clone();
        let mut best_sample = f64::NEG_INFINITY;

        for model in &self.models {
            let arm = stats.get(model).cloned().unwrap_or_default();
            let sample = beta_sample(&mut rng, arm.successes, arm.failures);
            if sample > best_sample {
                best_sample = sample;
                best_model = model.clone();
            }
        }
        best_model
    }

    fn ucb1_select(&self) -> String {
        let stats = self.stats.lock();
        let total_count: usize = stats.values().map(|a| a.count).sum();
        if total_count == 0 {
            return self.models[0].clone();
        }

        let mut best_model = self.models[0].clone();
        let mut best_score = f64::NEG_INFINITY;

        for model in &self.models {
            let arm = stats.get(model).cloned().unwrap_or_default();
            if arm.count == 0 {
                return model.clone();
            }
            let avg_reward = arm.total_reward / arm.count as f64;
            let exploration = (2.0 * (total_count as f64).ln() / arm.count as f64).sqrt();
            let score = avg_reward + exploration;
            if score > best_score {
                best_score = score;
                best_model = model.clone();
            }
        }
        best_model
    }
}

impl RouterPolicy for BanditRouterPolicy {
    fn select_model(&self, _context: &RoutingContext) -> String {
        if self.models.is_empty() {
            return String::new();
        }
        match self.strategy {
            BanditStrategy::ThompsonSampling => self.thompson_sample(),
            BanditStrategy::UCB1 => self.ucb1_select(),
        }
    }
}

fn beta_sample(rng: &mut ThreadRng, alpha: f64, beta: f64) -> f64 {
    let x: f64 = gamma_sample(rng, alpha);
    let y: f64 = gamma_sample(rng, beta);
    if x + y == 0.0 {
        return 0.5;
    }
    x / (x + y)
}

fn gamma_sample(rng: &mut ThreadRng, shape: f64) -> f64 {
    if shape <= 0.0 {
        return 0.0;
    }
    if shape < 1.0 {
        let u: f64 = rng.random();
        return gamma_sample(rng, shape + 1.0) * u.powf(1.0 / shape);
    }
    let d = shape - 1.0 / 3.0;
    let c = 1.0 / (9.0 * d).sqrt();
    loop {
        let x: f64 = rng.random::<f64>() * 2.0 - 1.0;
        let v = (1.0 + c * x).powi(3);
        if v <= 0.0 {
            continue;
        }
        let u: f64 = rng.random();
        if u < 1.0 - 0.0331 * x.powi(4) {
            return d * v;
        }
        if u.ln() < 0.5 * x * x + d * (1.0 - v + v.ln()) {
            return d * v;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bandit_thompson_sampling() {
        let policy = BanditRouterPolicy::new(
            vec!["model_a".into(), "model_b".into()],
            BanditStrategy::ThompsonSampling,
        );
        for _ in 0..10 {
            policy.update("model_a", 0.8);
        }
        for _ in 0..10 {
            policy.update("model_b", 0.2);
        }
        let mut a_count = 0;
        let ctx = RoutingContext::default();
        for _ in 0..100 {
            if policy.select_model(&ctx) == "model_a" {
                a_count += 1;
            }
        }
        assert!(a_count > 50, "model_a should be selected more often");
    }

    #[test]
    fn test_bandit_ucb1() {
        let policy = BanditRouterPolicy::new(
            vec!["m1".into(), "m2".into()],
            BanditStrategy::UCB1,
        );
        let ctx = RoutingContext::default();
        let selected = policy.select_model(&ctx);
        assert!(!selected.is_empty());
    }
}
