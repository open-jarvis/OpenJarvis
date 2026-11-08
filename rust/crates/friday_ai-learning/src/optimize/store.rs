//! SQLite-backed storage for optimization runs and trials.
//!
//! Rust translation of `src/friday_ai/learning/optimize/store.py`.

use std::collections::HashMap;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{params, Connection, Result as SqlResult};

use super::types::{
    BenchmarkScore, OptimizationRun, RunStatus, SampleScore, SearchSpace,
    TrialConfig, TrialFeedback, TrialResult,
};

// ---------------------------------------------------------------------------
// SQL constants
// ---------------------------------------------------------------------------

const CREATE_RUNS: &str = "\
CREATE TABLE IF NOT EXISTS optimization_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    search_space TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'running',
    optimizer_model TEXT NOT NULL DEFAULT '',
    benchmark TEXT NOT NULL DEFAULT '',
    best_trial_id TEXT,
    best_recipe_path TEXT,
    created_at REAL NOT NULL DEFAULT 0.0,
    updated_at REAL NOT NULL DEFAULT 0.0,
    pareto_frontier_ids TEXT NOT NULL DEFAULT '[]',
    benchmarks TEXT NOT NULL DEFAULT '[]'
);";

const CREATE_TRIALS: &str = "\
CREATE TABLE IF NOT EXISTS trial_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trial_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    reasoning TEXT NOT NULL DEFAULT '',
    accuracy REAL NOT NULL DEFAULT 0.0,
    mean_latency_seconds REAL NOT NULL DEFAULT 0.0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    total_energy_joules REAL NOT NULL DEFAULT 0.0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    samples_evaluated INTEGER NOT NULL DEFAULT 0,
    analysis TEXT NOT NULL DEFAULT '',
    failure_modes TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL DEFAULT 0.0,
    sample_scores TEXT NOT NULL DEFAULT '[]',
    structured_feedback TEXT NOT NULL DEFAULT '{}',
    per_benchmark TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (run_id) REFERENCES optimization_runs(run_id)
);";

const INSERT_RUN: &str = "\
INSERT OR REPLACE INTO optimization_runs (
    run_id, search_space, status, optimizer_model, benchmark,
    best_trial_id, best_recipe_path, created_at, updated_at,
    pareto_frontier_ids, benchmarks
) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)";

const INSERT_TRIAL: &str = "\
INSERT OR REPLACE INTO trial_results (
    trial_id, run_id, config, reasoning, accuracy,
    mean_latency_seconds, total_cost_usd, total_energy_joules,
    total_tokens, samples_evaluated, analysis, failure_modes,
    created_at, sample_scores, structured_feedback, per_benchmark
) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16)";

// ---------------------------------------------------------------------------
// OptimizationStore
// ---------------------------------------------------------------------------

/// SQLite-backed storage for optimization runs and trials.
pub struct OptimizationStore {
    conn: Connection,
}

impl OptimizationStore {
    /// Open or create a store at the given database path.
    pub fn open(db_path: impl AsRef<Path>) -> Result<Self, OptimizeStoreError> {
        let conn = Connection::open(db_path.as_ref())
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;
        conn.execute_batch("PRAGMA journal_mode=WAL;")
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;
        conn.execute_batch(CREATE_RUNS)
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;
        conn.execute_batch(CREATE_TRIALS)
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;
        Ok(Self { conn })
    }

    /// Create an in-memory store (useful for testing).
    pub fn in_memory() -> Result<Self, OptimizeStoreError> {
        let conn = Connection::open_in_memory()
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;
        conn.execute_batch("PRAGMA journal_mode=WAL;")
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;
        conn.execute_batch(CREATE_RUNS)
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;
        conn.execute_batch(CREATE_TRIALS)
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;
        Ok(Self { conn })
    }

    // ------------------------------------------------------------------
    // Runs
    // ------------------------------------------------------------------

    /// Persist an optimization run (insert or update).
    pub fn save_run(&self, run: &OptimizationRun) -> Result<(), OptimizeStoreError> {
        let now = now_epoch();
        let search_space_json = search_space_to_json(&run.search_space);
        let best_trial_id = run.best_trial.as_ref().map(|t| t.trial_id.clone());
        let pareto_ids: Vec<String> = run
            .pareto_frontier
            .iter()
            .map(|t| t.trial_id.clone())
            .collect();
        let pareto_json = serde_json::to_string(&pareto_ids).unwrap_or_else(|_| "[]".into());
        let benchmarks_json =
            serde_json::to_string(&run.benchmarks).unwrap_or_else(|_| "[]".into());

        self.conn
            .execute(
                INSERT_RUN,
                params![
                    run.run_id,
                    search_space_json,
                    run.status.to_string(),
                    run.optimizer_model,
                    run.benchmark,
                    best_trial_id,
                    run.best_recipe_path,
                    now,
                    now,
                    pareto_json,
                    benchmarks_json,
                ],
            )
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;
        Ok(())
    }

    /// Retrieve an optimization run by id, or `None`.
    pub fn get_run(&self, run_id: &str) -> Result<Option<OptimizationRun>, OptimizeStoreError> {
        // First, extract the raw row data to release the statement borrow
        let row_data: Option<RunRowData> = {
            let mut stmt = self
                .conn
                .prepare(
                    "SELECT id, run_id, search_space, status, optimizer_model, \
                     benchmark, best_trial_id, best_recipe_path, created_at, \
                     updated_at, pareto_frontier_ids, benchmarks \
                     FROM optimization_runs WHERE run_id = ?1",
                )
                .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;

            let mut rows = stmt
                .query_map(params![run_id], |row| {
                    Ok(RunRowData {
                        run_id: row.get(1)?,
                        search_space_raw: row.get(2)?,
                        status_str: row.get(3)?,
                        optimizer_model: row.get(4)?,
                        benchmark: row.get(5)?,
                        best_trial_id: row.get(6)?,
                        best_recipe_path: row.get(7)?,
                        pareto_ids_raw: row.get(10)?,
                        benchmarks_raw: row.get(11)?,
                    })
                })
                .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;

            match rows.next() {
                Some(Ok(data)) => Some(data),
                Some(Err(e)) => return Err(OptimizeStoreError::Sqlite(e.to_string())),
                None => None,
            }
        };

        // Now the statement is dropped, we can safely call get_trials
        match row_data {
            Some(data) => Ok(Some(self.build_run_from_row_data(data)?)),
            None => Ok(None),
        }
    }

    /// Return summary dicts of recent optimization runs.
    pub fn list_runs(
        &self,
        limit: usize,
    ) -> Result<Vec<RunSummary>, OptimizeStoreError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT run_id, status, optimizer_model, benchmark, \
                 best_trial_id, best_recipe_path, created_at, updated_at \
                 FROM optimization_runs ORDER BY created_at DESC LIMIT ?1",
            )
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;

        let rows = stmt
            .query_map(params![limit as i64], |row| {
                Ok(RunSummary {
                    run_id: row.get(0)?,
                    status: row.get(1)?,
                    optimizer_model: row.get(2)?,
                    benchmark: row.get(3)?,
                    best_trial_id: row.get(4)?,
                    best_recipe_path: row.get(5)?,
                    created_at: row.get(6)?,
                    updated_at: row.get(7)?,
                })
            })
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;

        let mut result = Vec::new();
        for row in rows {
            result.push(row.map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?);
        }
        Ok(result)
    }

    // ------------------------------------------------------------------
    // Trials
    // ------------------------------------------------------------------

    /// Persist a single trial result.
    pub fn save_trial(
        &self,
        run_id: &str,
        trial: &TrialResult,
    ) -> Result<(), OptimizeStoreError> {
        let now = now_epoch();

        let config_json = serde_json::to_string(&trial.config.params)
            .unwrap_or_else(|_| "{}".into());
        let failure_modes_json = serde_json::to_string(&trial.failure_modes)
            .unwrap_or_else(|_| "[]".into());
        let sample_scores_json = serde_json::to_string(&trial.sample_scores)
            .unwrap_or_else(|_| "[]".into());
        let feedback_json = match &trial.structured_feedback {
            Some(fb) => serde_json::to_string(fb).unwrap_or_else(|_| "{}".into()),
            None => "{}".into(),
        };
        let per_benchmark_json = serde_json::to_string(&trial.per_benchmark)
            .unwrap_or_else(|_| "[]".into());

        self.conn
            .execute(
                INSERT_TRIAL,
                params![
                    trial.trial_id,
                    run_id,
                    config_json,
                    trial.config.reasoning,
                    trial.accuracy,
                    trial.mean_latency_seconds,
                    trial.total_cost_usd,
                    trial.total_energy_joules,
                    trial.total_tokens,
                    trial.samples_evaluated,
                    trial.analysis,
                    failure_modes_json,
                    now,
                    sample_scores_json,
                    feedback_json,
                    per_benchmark_json,
                ],
            )
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;
        Ok(())
    }

    /// Retrieve all trial results for a given run.
    pub fn get_trials(&self, run_id: &str) -> Result<Vec<TrialResult>, OptimizeStoreError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT trial_id, run_id, config, reasoning, accuracy, \
                 mean_latency_seconds, total_cost_usd, total_energy_joules, \
                 total_tokens, samples_evaluated, analysis, failure_modes, \
                 created_at, sample_scores, structured_feedback, per_benchmark \
                 FROM trial_results WHERE run_id = ?1 ORDER BY id",
            )
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;

        let rows = stmt
            .query_map(params![run_id], row_to_trial)
            .map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?;

        let mut result = Vec::new();
        for row in rows {
            result.push(row.map_err(|e| OptimizeStoreError::Sqlite(e.to_string()))?);
        }
        Ok(result)
    }

    // ------------------------------------------------------------------
    // Internal
    // ------------------------------------------------------------------

    fn build_run_from_row_data(
        &self,
        data: RunRowData,
    ) -> Result<OptimizationRun, OptimizeStoreError> {
        let search_space = json_to_search_space(&data.search_space_raw);
        let status = data
            .status_str
            .parse::<RunStatus>()
            .unwrap_or(RunStatus::Running);

        // Load trials (safe now -- no active statement borrow)
        let trials = self.get_trials(&data.run_id)?;

        // Find best trial
        let best_trial = data.best_trial_id.and_then(|btid| {
            trials.iter().find(|t| t.trial_id == btid).cloned()
        });

        // Parse benchmarks
        let benchmarks: Vec<String> =
            serde_json::from_str(&data.benchmarks_raw).unwrap_or_default();

        // Parse pareto frontier IDs
        let frontier_ids: Vec<String> =
            serde_json::from_str(&data.pareto_ids_raw).unwrap_or_default();
        let trial_map: HashMap<String, &TrialResult> =
            trials.iter().map(|t| (t.trial_id.clone(), t)).collect();
        let pareto_frontier: Vec<TrialResult> = frontier_ids
            .iter()
            .filter_map(|id| trial_map.get(id).map(|t| (*t).clone()))
            .collect();

        Ok(OptimizationRun {
            run_id: data.run_id,
            search_space,
            trials,
            best_trial,
            best_recipe_path: data.best_recipe_path,
            status,
            optimizer_model: data.optimizer_model,
            benchmark: data.benchmark,
            benchmarks,
            pareto_frontier,
            objectives: super::types::default_objectives(),
        })
    }
}

/// Intermediate struct to hold raw row data from the optimization_runs table.
/// This avoids holding a borrow on the SQLite statement while calling get_trials.
struct RunRowData {
    run_id: String,
    search_space_raw: String,
    status_str: String,
    optimizer_model: String,
    benchmark: String,
    best_trial_id: Option<String>,
    best_recipe_path: Option<String>,
    pareto_ids_raw: String,
    benchmarks_raw: String,
}

// ---------------------------------------------------------------------------
// Row conversion helper (outside impl to avoid lifetime issues)
// ---------------------------------------------------------------------------

fn row_to_trial(row: &rusqlite::Row<'_>) -> SqlResult<TrialResult> {
    let trial_id: String = row.get(0)?;
    // row index 1 = run_id (not stored on TrialResult)
    let config_raw: String = row.get(2)?;
    let reasoning: String = row.get(3)?;
    let accuracy: f64 = row.get(4)?;
    let mean_latency: f64 = row.get(5)?;
    let cost: f64 = row.get(6)?;
    let energy: f64 = row.get(7)?;
    let tokens: i64 = row.get(8)?;
    let samples: i64 = row.get(9)?;
    let analysis: String = row.get(10)?;
    let failure_modes_raw: String = row.get(11)?;
    // row index 12 = created_at
    let sample_scores_raw: String = row.get(13)?;
    let feedback_raw: String = row.get(14)?;
    let per_benchmark_raw: String = row.get(15)?;

    let params: HashMap<String, serde_json::Value> =
        serde_json::from_str(&config_raw).unwrap_or_default();
    let failure_modes: Vec<String> =
        serde_json::from_str(&failure_modes_raw).unwrap_or_default();
    let sample_scores: Vec<SampleScore> =
        serde_json::from_str(&sample_scores_raw).unwrap_or_default();
    let per_benchmark: Vec<BenchmarkScore> =
        serde_json::from_str(&per_benchmark_raw).unwrap_or_default();

    let structured_feedback: Option<TrialFeedback> = {
        let fb: Option<TrialFeedback> = serde_json::from_str(&feedback_raw).ok();
        fb.filter(|f| !f.summary_text.is_empty())
    };

    let config = TrialConfig {
        trial_id: trial_id.clone(),
        params,
        reasoning,
    };

    Ok(TrialResult {
        trial_id,
        config,
        accuracy,
        mean_latency_seconds: mean_latency,
        total_cost_usd: cost,
        total_energy_joules: energy,
        total_tokens: tokens,
        samples_evaluated: samples,
        analysis,
        failure_modes,
        sample_scores,
        structured_feedback,
        per_benchmark,
    })
}

// ---------------------------------------------------------------------------
// Serialization helpers
// ---------------------------------------------------------------------------

fn search_space_to_json(space: &SearchSpace) -> String {
    serde_json::to_string(space).unwrap_or_else(|_| "{}".into())
}

fn json_to_search_space(raw: &str) -> SearchSpace {
    serde_json::from_str(raw).unwrap_or_default()
}

fn now_epoch() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

// ---------------------------------------------------------------------------
// Summary type for list_runs
// ---------------------------------------------------------------------------

/// Lightweight summary returned by `list_runs`.
#[derive(Debug, Clone)]
pub struct RunSummary {
    pub run_id: String,
    pub status: String,
    pub optimizer_model: String,
    pub benchmark: String,
    pub best_trial_id: Option<String>,
    pub best_recipe_path: Option<String>,
    pub created_at: f64,
    pub updated_at: f64,
}

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Errors from the optimization store.
#[derive(Debug, thiserror::Error)]
pub enum OptimizeStoreError {
    #[error("SQLite error: {0}")]
    Sqlite(String),
    #[error("Serialization error: {0}")]
    Serialization(String),
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::optimize::types::*;

    fn make_trial(id: &str, accuracy: f64) -> TrialResult {
        TrialResult {
            trial_id: id.into(),
            config: TrialConfig {
                trial_id: id.into(),
                params: {
                    let mut m = HashMap::new();
                    m.insert("intelligence.model".into(), serde_json::json!("qwen3:8b"));
                    m
                },
                reasoning: "test".into(),
            },
            accuracy,
            mean_latency_seconds: 1.0,
            total_cost_usd: 0.01,
            total_energy_joules: 10.0,
            total_tokens: 100,
            samples_evaluated: 10,
            analysis: "ok".into(),
            failure_modes: vec![],
            sample_scores: vec![],
            structured_feedback: None,
            per_benchmark: vec![],
        }
    }

    #[test]
    fn test_store_save_and_get_trial() {
        let store = OptimizationStore::in_memory().unwrap();

        // Save a run first
        let run = OptimizationRun {
            run_id: "run1".into(),
            search_space: SearchSpace::default(),
            trials: vec![],
            best_trial: None,
            best_recipe_path: None,
            status: RunStatus::Running,
            optimizer_model: "test-model".into(),
            benchmark: "test-bench".into(),
            benchmarks: vec![],
            pareto_frontier: vec![],
            objectives: default_objectives(),
        };
        store.save_run(&run).unwrap();

        // Save trial
        let trial = make_trial("t1", 0.85);
        store.save_trial("run1", &trial).unwrap();

        // Retrieve trials
        let trials = store.get_trials("run1").unwrap();
        assert_eq!(trials.len(), 1);
        assert_eq!(trials[0].trial_id, "t1");
        assert!((trials[0].accuracy - 0.85).abs() < 1e-9);
    }

    #[test]
    fn test_store_save_and_get_run() {
        let store = OptimizationStore::in_memory().unwrap();

        let trial = make_trial("t1", 0.9);

        let run = OptimizationRun {
            run_id: "run1".into(),
            search_space: SearchSpace {
                dimensions: vec![SearchDimension {
                    name: "intelligence.temperature".into(),
                    dim_type: DimensionType::Continuous,
                    values: vec![],
                    low: Some(0.0),
                    high: Some(1.0),
                    description: "temp".into(),
                    primitive: "intelligence".into(),
                }],
                fixed: HashMap::new(),
                constraints: vec![],
            },
            trials: vec![trial.clone()],
            best_trial: Some(trial.clone()),
            best_recipe_path: Some("/tmp/best.toml".into()),
            status: RunStatus::Completed,
            optimizer_model: "test-model".into(),
            benchmark: "supergpqa".into(),
            benchmarks: vec!["supergpqa".into()],
            pareto_frontier: vec![trial.clone()],
            objectives: default_objectives(),
        };

        store.save_run(&run).unwrap();
        store.save_trial("run1", &trial).unwrap();

        let loaded = store.get_run("run1").unwrap().unwrap();
        assert_eq!(loaded.run_id, "run1");
        assert_eq!(loaded.status, RunStatus::Completed);
        assert_eq!(loaded.benchmark, "supergpqa");
        assert!(loaded.best_trial.is_some());
        assert_eq!(loaded.trials.len(), 1);
        assert_eq!(loaded.pareto_frontier.len(), 1);
    }

    #[test]
    fn test_store_list_runs() {
        let store = OptimizationStore::in_memory().unwrap();

        for i in 0..3 {
            let run = OptimizationRun {
                run_id: format!("run{i}"),
                search_space: SearchSpace::default(),
                trials: vec![],
                best_trial: None,
                best_recipe_path: None,
                status: RunStatus::Completed,
                optimizer_model: "model".into(),
                benchmark: "bench".into(),
                benchmarks: vec![],
                pareto_frontier: vec![],
                objectives: default_objectives(),
            };
            store.save_run(&run).unwrap();
        }

        let summaries = store.list_runs(10).unwrap();
        assert_eq!(summaries.len(), 3);
    }

    #[test]
    fn test_store_get_nonexistent_run() {
        let store = OptimizationStore::in_memory().unwrap();
        let result = store.get_run("nonexistent").unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn test_store_trial_with_feedback() {
        let store = OptimizationStore::in_memory().unwrap();

        let run = OptimizationRun {
            run_id: "run_fb".into(),
            search_space: SearchSpace::default(),
            trials: vec![],
            best_trial: None,
            best_recipe_path: None,
            status: RunStatus::Running,
            optimizer_model: "model".into(),
            benchmark: "bench".into(),
            benchmarks: vec![],
            pareto_frontier: vec![],
            objectives: default_objectives(),
        };
        store.save_run(&run).unwrap();

        let mut trial = make_trial("t_fb", 0.7);
        trial.structured_feedback = Some(TrialFeedback {
            summary_text: "The intelligence primitive needs tuning".into(),
            failure_patterns: vec!["timeout on long prompts".into()],
            primitive_ratings: {
                let mut m = HashMap::new();
                m.insert("intelligence".into(), "medium".into());
                m.insert("agent".into(), "high".into());
                m
            },
            suggested_changes: vec!["lower temperature".into()],
            target_primitive: "intelligence".into(),
        });
        trial.per_benchmark = vec![BenchmarkScore {
            benchmark: "supergpqa".into(),
            accuracy: 0.7,
            mean_latency_seconds: 1.5,
            total_cost_usd: 0.02,
            total_energy_joules: 20.0,
            total_tokens: 200,
            samples_evaluated: 20,
            errors: 1,
            weight: 1.0,
            sample_scores: vec![],
        }];

        store.save_trial("run_fb", &trial).unwrap();

        let loaded = store.get_trials("run_fb").unwrap();
        assert_eq!(loaded.len(), 1);
        let lt = &loaded[0];
        assert!(lt.structured_feedback.is_some());
        let fb = lt.structured_feedback.as_ref().unwrap();
        assert_eq!(fb.target_primitive, "intelligence");
        assert_eq!(lt.per_benchmark.len(), 1);
        assert_eq!(lt.per_benchmark[0].benchmark, "supergpqa");
    }
}
