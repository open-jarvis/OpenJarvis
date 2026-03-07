//! LearningOrchestrator — coordinate the trace→learn→eval cycle.
//!
//! Ported from Python `openjarvis.learning.learning_orchestrator`.
//! Actual trace store access, file I/O, and LoRA training stay in Python;
//! this module provides the cycle evaluation and acceptance logic.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LearningCycleResult {
    pub timestamp: f64,
    pub status: String,
    pub reason: String,
    pub sft_pairs: usize,
    pub routing_classes: usize,
    pub agent_classes: usize,
    pub baseline_score: Option<f64>,
    pub post_score: Option<f64>,
    pub improvement: Option<f64>,
    pub accepted: bool,
}

pub struct LearningOrchestrator {
    min_improvement: f64,
    min_sft_pairs: usize,
    min_quality: f64,
}

impl LearningOrchestrator {
    pub fn new(min_improvement: f64, min_sft_pairs: usize, min_quality: f64) -> Self {
        Self {
            min_improvement,
            min_sft_pairs,
            min_quality,
        }
    }

    pub fn min_quality(&self) -> f64 {
        self.min_quality
    }

    pub fn min_sft_pairs(&self) -> usize {
        self.min_sft_pairs
    }

    /// Evaluate a learning cycle given pre-extracted counts and optional eval scores.
    ///
    /// Python calls the miners and evolvers, then passes the summary counts here
    /// to decide whether to accept or reject the cycle.
    pub fn evaluate_cycle(
        &self,
        sft_pairs_count: usize,
        routing_count: usize,
        agent_count: usize,
        _recommendations_count: usize,
        baseline_score: Option<f64>,
        post_score: Option<f64>,
    ) -> LearningCycleResult {
        let timestamp = current_timestamp();

        let total_data = sft_pairs_count + routing_count + agent_count;
        if total_data == 0 {
            return LearningCycleResult {
                timestamp,
                status: "skipped".into(),
                reason: "no training data available".into(),
                sft_pairs: 0,
                routing_classes: 0,
                agent_classes: 0,
                baseline_score: None,
                post_score: None,
                improvement: None,
                accepted: false,
            };
        }

        match (baseline_score, post_score) {
            (Some(baseline), Some(post)) => {
                let improvement = post - baseline;
                let accepted = improvement >= self.min_improvement;
                let (status, reason) = if accepted {
                    ("completed".to_string(), String::new())
                } else {
                    (
                        "rejected".to_string(),
                        format!(
                            "eval improvement {improvement:.4} below threshold {}",
                            self.min_improvement
                        ),
                    )
                };

                LearningCycleResult {
                    timestamp,
                    status,
                    reason,
                    sft_pairs: sft_pairs_count,
                    routing_classes: routing_count,
                    agent_classes: agent_count,
                    baseline_score: Some(baseline),
                    post_score: Some(post),
                    improvement: Some(improvement),
                    accepted,
                }
            }
            _ => {
                LearningCycleResult {
                    timestamp,
                    status: "completed".into(),
                    reason: String::new(),
                    sft_pairs: sft_pairs_count,
                    routing_classes: routing_count,
                    agent_classes: agent_count,
                    baseline_score,
                    post_score,
                    improvement: None,
                    accepted: true,
                }
            }
        }
    }
}

fn current_timestamp() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_no_data_skipped() {
        let orch = LearningOrchestrator::new(0.02, 10, 0.7);
        let result = orch.evaluate_cycle(0, 0, 0, 0, None, None);
        assert_eq!(result.status, "skipped");
        assert!(!result.accepted);
    }

    #[test]
    fn test_no_eval_fn_always_accepts() {
        let orch = LearningOrchestrator::new(0.02, 10, 0.7);
        let result = orch.evaluate_cycle(15, 3, 2, 5, None, None);
        assert_eq!(result.status, "completed");
        assert!(result.accepted);
        assert_eq!(result.sft_pairs, 15);
        assert_eq!(result.routing_classes, 3);
    }

    #[test]
    fn test_improvement_accepted() {
        let orch = LearningOrchestrator::new(0.02, 10, 0.7);
        let result = orch.evaluate_cycle(20, 3, 2, 5, Some(0.70), Some(0.75));
        assert_eq!(result.status, "completed");
        assert!(result.accepted);
        assert!((result.improvement.unwrap() - 0.05).abs() < 1e-9);
    }

    #[test]
    fn test_improvement_rejected() {
        let orch = LearningOrchestrator::new(0.02, 10, 0.7);
        let result = orch.evaluate_cycle(20, 3, 2, 5, Some(0.70), Some(0.71));
        assert_eq!(result.status, "rejected");
        assert!(!result.accepted);
        assert!(result.reason.contains("below threshold"));
    }

    #[test]
    fn test_exact_threshold_accepted() {
        let orch = LearningOrchestrator::new(0.02, 10, 0.7);
        let result = orch.evaluate_cycle(20, 3, 2, 5, Some(0.70), Some(0.72));
        assert!(result.accepted);
    }

    #[test]
    fn test_negative_improvement_rejected() {
        let orch = LearningOrchestrator::new(0.02, 10, 0.7);
        let result = orch.evaluate_cycle(20, 3, 2, 5, Some(0.80), Some(0.75));
        assert!(!result.accepted);
        assert!(result.improvement.unwrap() < 0.0);
    }

    #[test]
    fn test_timestamp_populated() {
        let orch = LearningOrchestrator::new(0.02, 10, 0.7);
        let result = orch.evaluate_cycle(5, 1, 1, 1, None, None);
        assert!(result.timestamp > 0.0);
    }

    #[test]
    fn test_accessors() {
        let orch = LearningOrchestrator::new(0.05, 20, 0.8);
        assert!((orch.min_quality() - 0.8).abs() < f64::EPSILON);
        assert_eq!(orch.min_sft_pairs(), 20);
    }
}
