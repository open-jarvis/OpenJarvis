//! OptimizationEngine -- orchestrates the optimize loop.
//!
//! Rust translation of `src/friday_ai/learning/optimize/optimizer.py`.
//!
//! Ties together the LLM optimizer, trial runner, and persistence store
//! into a single propose -> evaluate -> analyze -> repeat loop.

use tracing::{info, warn};

use super::llm_optimizer::LLMOptimizer;
use super::store::OptimizationStore;
use super::types::{
    Direction, ObjectiveSpec, OptimizationRun, RunStatus, SearchSpace, TrialConfig, TrialResult,
};

// ---------------------------------------------------------------------------
// Trial runner trait (Python's TrialRunner is a class -- here it's a trait)
// ---------------------------------------------------------------------------

/// Abstraction for evaluating a trial configuration.
///
/// Implementations run benchmarks and return [`TrialResult`]s.
/// The actual evaluation logic stays in Python (or is plugged in via FFI).
pub trait TrialRunner: Send + Sync {
    /// Execute a single trial and return the result.
    fn run_trial(&self, config: &TrialConfig) -> TrialResult;

    /// Name of the primary benchmark being evaluated.
    fn benchmark(&self) -> &str {
        ""
    }

    /// Names of all benchmarks (for multi-benchmark mode).
    fn benchmark_names(&self) -> Vec<String> {
        vec![]
    }
}

// ---------------------------------------------------------------------------
// Pareto frontier computation
// ---------------------------------------------------------------------------

/// Read a metric value from a [`TrialResult`] for a given objective.
fn get_objective_value(trial: &TrialResult, obj: &ObjectiveSpec) -> f64 {
    match obj.metric.as_str() {
        "accuracy" => trial.accuracy,
        "mean_latency_seconds" => trial.mean_latency_seconds,
        "total_cost_usd" => trial.total_cost_usd,
        "total_energy_joules" => trial.total_energy_joules,
        _ => 0.0,
    }
}

/// Compute the Pareto frontier: trials not dominated by any other.
///
/// A trial A dominates trial B if A is >= B on all objectives and > B
/// on at least one (direction-aware: `Minimize` negates so higher is better).
pub fn compute_pareto_frontier(
    trials: &[TrialResult],
    objectives: &[ObjectiveSpec],
) -> Vec<TrialResult> {
    if trials.is_empty() || objectives.is_empty() {
        return trials.to_vec();
    }

    let values: Vec<Vec<f64>> = trials
        .iter()
        .map(|t| {
            objectives
                .iter()
                .map(|obj| {
                    let v = get_objective_value(t, obj);
                    // Normalize: for "minimize", negate so higher is always better
                    if obj.direction == Direction::Minimize {
                        -v
                    } else {
                        v
                    }
                })
                .collect()
        })
        .collect();

    let mut frontier = Vec::new();

    for (i, _trial) in trials.iter().enumerate() {
        let mut dominated = false;
        for (j, _other) in trials.iter().enumerate() {
            if i == j {
                continue;
            }
            // Check if other dominates trial
            let all_ge = (0..objectives.len()).all(|k| values[j][k] >= values[i][k]);
            let any_gt = (0..objectives.len()).any(|k| values[j][k] > values[i][k]);
            if all_ge && any_gt {
                dominated = true;
                break;
            }
        }
        if !dominated {
            frontier.push(trials[i].clone());
        }
    }

    frontier
}

// ---------------------------------------------------------------------------
// OptimizationEngine
// ---------------------------------------------------------------------------

/// Orchestrates the optimize loop: propose -> evaluate -> analyze -> repeat.
pub struct OptimizationEngine<R: TrialRunner> {
    pub search_space: SearchSpace,
    pub llm_optimizer: LLMOptimizer,
    pub trial_runner: R,
    pub store: Option<OptimizationStore>,
    pub max_trials: usize,
    pub early_stop_patience: usize,
}

impl<R: TrialRunner> OptimizationEngine<R> {
    /// Create a new optimization engine.
    pub fn new(
        search_space: SearchSpace,
        llm_optimizer: LLMOptimizer,
        trial_runner: R,
        store: Option<OptimizationStore>,
        max_trials: usize,
        early_stop_patience: usize,
    ) -> Self {
        Self {
            search_space,
            llm_optimizer,
            trial_runner,
            store,
            max_trials,
            early_stop_patience,
        }
    }

    /// Execute the full optimization loop.
    ///
    /// 1. Generate a run_id.
    /// 2. `llm_optimizer.propose_initial()` -> first config.
    /// 3. Loop up to `max_trials`:
    ///    a. `trial_runner.run_trial(config)` -> TrialResult
    ///    b. Update history, track best, compute Pareto frontier
    ///    c. Persist to store if available
    ///    d. Check early stopping
    ///    e. Propose next config
    /// 4. Return the completed `OptimizationRun`.
    pub fn run(
        &mut self,
        progress_callback: Option<&dyn Fn(usize, usize)>,
    ) -> OptimizationRun {
        let run_id = uuid::Uuid::new_v4().simple().to_string()[..16].to_string();

        let benchmark_name = self.trial_runner.benchmark().to_string();
        let benchmark_names = self.trial_runner.benchmark_names();

        let mut optimization_run = OptimizationRun {
            run_id: run_id.clone(),
            search_space: self.search_space.clone(),
            status: RunStatus::Running,
            optimizer_model: self.llm_optimizer.optimizer_model.clone(),
            benchmark: if benchmark_names.is_empty() {
                benchmark_name
            } else {
                benchmark_names.join("+")
            },
            benchmarks: benchmark_names,
            trials: vec![],
            best_trial: None,
            best_recipe_path: None,
            pareto_frontier: vec![],
            objectives: super::types::default_objectives(),
        };

        let mut history: Vec<TrialResult> = Vec::new();
        let mut best_accuracy: f64 = -1.0;
        let mut trials_without_improvement: usize = 0;

        // First config
        let mut config = self.llm_optimizer.propose_initial();

        for trial_num in 1..=self.max_trials {
            info!(
                "Trial {}/{} (id={})",
                trial_num, self.max_trials, config.trial_id
            );

            // Evaluate
            let mut result = self.trial_runner.run_trial(&config);

            // Placeholder analysis (the real LLM analysis stays in Python)
            if result.analysis.is_empty() {
                result.analysis = format!(
                    "Trial {} completed: accuracy={:.4}, latency={:.4}s",
                    result.trial_id, result.accuracy, result.mean_latency_seconds
                );
            }

            // Record
            history.push(result.clone());
            optimization_run.trials.push(result.clone());

            // Recompute Pareto frontier
            optimization_run.pareto_frontier =
                compute_pareto_frontier(&history, &optimization_run.objectives);

            // Persist trial
            if let Some(ref store) = self.store {
                if let Err(e) = store.save_trial(&run_id, &result) {
                    warn!("Failed to save trial: {e}");
                }
            }

            // Track best
            if result.accuracy > best_accuracy {
                best_accuracy = result.accuracy;
                optimization_run.best_trial = Some(result.clone());
                trials_without_improvement = 0;
            } else {
                trials_without_improvement += 1;
            }

            // Progress callback
            if let Some(cb) = progress_callback {
                cb(trial_num, self.max_trials);
            }

            // Early stopping
            if trials_without_improvement >= self.early_stop_patience {
                info!(
                    "Early stopping after {} trials without improvement.",
                    self.early_stop_patience
                );
                break;
            }

            // Propose next (unless this was the last trial)
            if trial_num < self.max_trials {
                config = self.llm_optimizer.propose_next(&history);
            }
        }

        optimization_run.status = RunStatus::Completed;

        if let Some(ref store) = self.store {
            if let Err(e) = store.save_run(&optimization_run) {
                warn!("Failed to save optimization run: {e}");
            }
        }

        optimization_run
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::optimize::types::*;
    use std::collections::HashMap;

    // A simple mock trial runner for testing
    struct MockTrialRunner {
        results: Vec<f64>,
        call_count: std::sync::atomic::AtomicUsize,
    }

    impl MockTrialRunner {
        fn new(results: Vec<f64>) -> Self {
            Self {
                results,
                call_count: std::sync::atomic::AtomicUsize::new(0),
            }
        }
    }

    impl TrialRunner for MockTrialRunner {
        fn run_trial(&self, config: &TrialConfig) -> TrialResult {
            let idx = self.call_count.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            let accuracy = if idx < self.results.len() {
                self.results[idx]
            } else {
                0.5
            };

            TrialResult {
                trial_id: config.trial_id.clone(),
                config: config.clone(),
                accuracy,
                mean_latency_seconds: 1.0,
                total_cost_usd: 0.01,
                total_energy_joules: 10.0,
                total_tokens: 100,
                samples_evaluated: 10,
                analysis: String::new(),
                failure_modes: vec![],
                sample_scores: vec![],
                structured_feedback: None,
                per_benchmark: vec![],
            }
        }

        fn benchmark(&self) -> &str {
            "mock_bench"
        }
    }

    #[test]
    fn test_compute_pareto_frontier_single() {
        let trial = TrialResult {
            trial_id: "t1".into(),
            config: TrialConfig {
                trial_id: "t1".into(),
                params: HashMap::new(),
                reasoning: String::new(),
            },
            accuracy: 0.9,
            mean_latency_seconds: 1.0,
            total_cost_usd: 0.1,
            total_energy_joules: 10.0,
            total_tokens: 100,
            samples_evaluated: 10,
            analysis: String::new(),
            failure_modes: vec![],
            sample_scores: vec![],
            structured_feedback: None,
            per_benchmark: vec![],
        };

        let frontier = compute_pareto_frontier(std::slice::from_ref(&trial), &default_objectives());
        assert_eq!(frontier.len(), 1);
        assert_eq!(frontier[0].trial_id, "t1");
    }

    #[test]
    fn test_compute_pareto_frontier_dominated() {
        let make = |id: &str, acc: f64, lat: f64, cost: f64| TrialResult {
            trial_id: id.into(),
            config: TrialConfig {
                trial_id: id.into(),
                params: HashMap::new(),
                reasoning: String::new(),
            },
            accuracy: acc,
            mean_latency_seconds: lat,
            total_cost_usd: cost,
            total_energy_joules: 0.0,
            total_tokens: 0,
            samples_evaluated: 0,
            analysis: String::new(),
            failure_modes: vec![],
            sample_scores: vec![],
            structured_feedback: None,
            per_benchmark: vec![],
        };

        let trials = vec![
            make("t1", 0.9, 1.0, 0.1),   // best accuracy, worst latency/cost
            make("t2", 0.7, 0.5, 0.05),   // lower accuracy, better latency/cost
            make("t3", 0.6, 0.8, 0.08),   // dominated by t2 (worse on all)
        ];

        let objs = default_objectives();
        let frontier = compute_pareto_frontier(&trials, &objs);
        // t1 and t2 should be on frontier; t3 is dominated by t2
        assert_eq!(frontier.len(), 2);
        let ids: Vec<&str> = frontier.iter().map(|t| t.trial_id.as_str()).collect();
        assert!(ids.contains(&"t1"));
        assert!(ids.contains(&"t2"));
    }

    #[test]
    fn test_compute_pareto_frontier_empty() {
        let frontier = compute_pareto_frontier(&[], &default_objectives());
        assert!(frontier.is_empty());
    }

    #[test]
    fn test_optimization_engine_run() {
        let search_space = SearchSpace::default();
        let llm_opt = LLMOptimizer::new(search_space.clone(), "test-model".into());
        let runner = MockTrialRunner::new(vec![0.5, 0.6, 0.7, 0.8, 0.75]);

        let mut engine = OptimizationEngine::new(
            search_space,
            llm_opt,
            runner,
            None, // no store
            5,
            10, // high patience so we run all trials
        );

        let run = engine.run(None);
        assert_eq!(run.status, RunStatus::Completed);
        assert_eq!(run.trials.len(), 5);
        assert!(run.best_trial.is_some());
        assert!((run.best_trial.unwrap().accuracy - 0.8).abs() < 1e-9);
    }

    #[test]
    fn test_optimization_engine_early_stop() {
        let search_space = SearchSpace::default();
        let llm_opt = LLMOptimizer::new(search_space.clone(), "test-model".into());
        // accuracy goes down after first trial, triggers early stop at patience=2
        let runner = MockTrialRunner::new(vec![0.8, 0.7, 0.6, 0.5]);

        let mut engine = OptimizationEngine::new(
            search_space,
            llm_opt,
            runner,
            None,
            10,
            2, // early stop after 2 trials without improvement
        );

        let run = engine.run(None);
        assert_eq!(run.status, RunStatus::Completed);
        // Should stop after 3 trials (1 good + 2 without improvement)
        assert_eq!(run.trials.len(), 3);
    }

    #[test]
    fn test_optimization_engine_with_store() {
        let search_space = SearchSpace::default();
        let llm_opt = LLMOptimizer::new(search_space.clone(), "test-model".into());
        let runner = MockTrialRunner::new(vec![0.5, 0.7]);
        let store = OptimizationStore::in_memory().unwrap();

        let mut engine = OptimizationEngine::new(
            search_space,
            llm_opt,
            runner,
            Some(store),
            2,
            10,
        );

        let run = engine.run(None);
        assert_eq!(run.status, RunStatus::Completed);
        assert_eq!(run.trials.len(), 2);

        // Verify the store has the data
        let stored_run = engine
            .store
            .as_ref()
            .unwrap()
            .get_run(&run.run_id)
            .unwrap();
        assert!(stored_run.is_some());
    }

    #[test]
    fn test_optimization_engine_progress_callback() {
        let search_space = SearchSpace::default();
        let llm_opt = LLMOptimizer::new(search_space.clone(), "test-model".into());
        let runner = MockTrialRunner::new(vec![0.5, 0.6]);

        let mut engine = OptimizationEngine::new(
            search_space,
            llm_opt,
            runner,
            None,
            2,
            10,
        );

        let progress = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let progress_clone = progress.clone();

        let run = engine.run(Some(&move |trial_num, max_trials| {
            progress_clone.lock().unwrap().push((trial_num, max_trials));
        }));

        assert_eq!(run.trials.len(), 2);
        let recorded = progress.lock().unwrap();
        assert_eq!(recorded.len(), 2);
        assert_eq!(recorded[0], (1, 2));
        assert_eq!(recorded[1], (2, 2));
    }
}
