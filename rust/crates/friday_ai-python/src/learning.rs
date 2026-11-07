//! PyO3 bindings for learning/router policy types and optimization.

use friday_ai_learning::RouterPolicy;
use pyo3::prelude::*;

#[pyclass(name = "HeuristicRouter")]
pub struct PyHeuristicRouter {
    inner: friday_ai_learning::HeuristicRouter,
}

#[pymethods]
impl PyHeuristicRouter {
    #[new]
    #[pyo3(signature = (default_model="qwen3:8b", code_model=None, math_model=None, fast_model=None))]
    fn new(
        default_model: &str,
        code_model: Option<String>,
        math_model: Option<String>,
        fast_model: Option<String>,
    ) -> Self {
        Self {
            inner: friday_ai_learning::HeuristicRouter::new(
                default_model.to_string(),
                code_model,
                math_model,
                fast_model,
            ),
        }
    }

    fn select_model(&self, query: &str, has_code: bool, has_math: bool) -> String {
        let ctx = friday_ai_core::RoutingContext {
            query: query.to_string(),
            query_length: query.len(),
            has_code,
            has_math,
            ..Default::default()
        };
        self.inner.select_model(&ctx)
    }
}

#[pyclass(name = "BanditRouterPolicy")]
pub struct PyBanditRouterPolicy {
    inner: friday_ai_learning::BanditRouterPolicy,
}

#[pymethods]
impl PyBanditRouterPolicy {
    #[new]
    #[pyo3(signature = (models, strategy="thompson"))]
    fn new(models: Vec<String>, strategy: &str) -> Self {
        let strat = match strategy {
            "ucb1" | "UCB1" => friday_ai_learning::bandit::BanditStrategy::UCB1,
            _ => friday_ai_learning::bandit::BanditStrategy::ThompsonSampling,
        };
        Self {
            inner: friday_ai_learning::BanditRouterPolicy::new(models, strat),
        }
    }

    fn select_model(&self) -> String {
        let ctx = friday_ai_core::RoutingContext::default();
        self.inner.select_model(&ctx)
    }

    fn update(&self, model: &str, reward: f64) {
        self.inner.update(model, reward);
    }
}

#[pyclass(name = "GRPORouterPolicy")]
pub struct PyGRPORouterPolicy {
    inner: friday_ai_learning::GRPORouterPolicy,
}

#[pymethods]
impl PyGRPORouterPolicy {
    #[new]
    #[pyo3(signature = (models, temperature=1.0))]
    fn new(models: Vec<String>, temperature: f64) -> Self {
        Self {
            inner: friday_ai_learning::GRPORouterPolicy::new(models, temperature),
        }
    }

    fn select_model(&self) -> String {
        let ctx = friday_ai_core::RoutingContext::default();
        self.inner.select_model(&ctx)
    }

    fn update_weights(&self, rewards_json: &str) -> PyResult<()> {
        let rewards: Vec<(String, f64)> = serde_json::from_str(rewards_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        self.inner.update_weights(&rewards);
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Optimization store
// ---------------------------------------------------------------------------

#[pyclass(name = "OptimizationStore")]
pub struct PyOptimizationStore {
    inner: parking_lot::Mutex<friday_ai_learning::optimize::OptimizationStore>,
}

#[pymethods]
impl PyOptimizationStore {
    /// Open or create a store at the given database path.
    /// Use `":memory:"` for an in-memory store.
    #[new]
    #[pyo3(signature = (path=":memory:"))]
    fn new(path: &str) -> PyResult<Self> {
        let store = if path == ":memory:" {
            friday_ai_learning::optimize::OptimizationStore::in_memory()
        } else {
            friday_ai_learning::optimize::OptimizationStore::open(path)
        };
        let store =
            store.map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(Self {
            inner: parking_lot::Mutex::new(store),
        })
    }

    /// Save a trial result (JSON string) for a given run_id.
    fn save_trial(&self, run_id: &str, trial_json: &str) -> PyResult<()> {
        let trial: friday_ai_learning::optimize::TrialResult =
            serde_json::from_str(trial_json)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        self.inner
            .lock()
            .save_trial(run_id, &trial)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Retrieve an optimization run by id. Returns JSON string or None.
    fn get_run(&self, run_id: &str) -> PyResult<Option<String>> {
        let run = self
            .inner
            .lock()
            .get_run(run_id)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        match run {
            Some(r) => Ok(Some(
                serde_json::to_string(&r).unwrap_or_else(|_| "{}".into()),
            )),
            None => Ok(None),
        }
    }

    /// List recent optimization runs. Returns JSON string.
    #[pyo3(signature = (limit=50))]
    fn list_runs(&self, limit: usize) -> PyResult<String> {
        let summaries = self
            .inner
            .lock()
            .list_runs(limit)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        // RunSummary doesn't derive Serialize, so manually build JSON.
        let items: Vec<serde_json::Value> = summaries
            .iter()
            .map(|s| {
                serde_json::json!({
                    "run_id": s.run_id,
                    "status": s.status,
                    "optimizer_model": s.optimizer_model,
                    "benchmark": s.benchmark,
                    "best_trial_id": s.best_trial_id,
                    "best_recipe_path": s.best_recipe_path,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                })
            })
            .collect();
        Ok(serde_json::to_string(&items).unwrap_or_else(|_| "[]".into()))
    }
}

// ---------------------------------------------------------------------------
// LLM Optimizer
// ---------------------------------------------------------------------------

#[pyclass(name = "LLMOptimizer")]
pub struct PyLLMOptimizer {
    inner: friday_ai_learning::optimize::LLMOptimizer,
}

#[pymethods]
impl PyLLMOptimizer {
    /// Create a new LLM optimizer.
    ///
    /// `search_space_json` is a JSON string representing the SearchSpace.
    /// `optimizer_model` is the model name to use for optimization proposals.
    #[new]
    #[pyo3(signature = (search_space_json, optimizer_model="gpt-4o"))]
    fn new(search_space_json: &str, optimizer_model: &str) -> PyResult<Self> {
        let search_space: friday_ai_learning::optimize::SearchSpace =
            serde_json::from_str(search_space_json)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let inner = friday_ai_learning::optimize::LLMOptimizer::new(
            search_space,
            optimizer_model.to_string(),
        );
        Ok(Self { inner })
    }

    /// Propose an initial configuration. Returns JSON string.
    fn propose_initial(&self) -> String {
        let config = self.inner.propose_initial();
        serde_json::to_string(&config).unwrap_or_else(|_| "{}".into())
    }

    /// Propose the next configuration based on trial history (JSON string).
    /// Returns JSON string.
    fn propose_next(&self, history_json: &str) -> PyResult<String> {
        let history: Vec<friday_ai_learning::optimize::TrialResult> =
            serde_json::from_str(history_json)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let config = self.inner.propose_next(&history);
        Ok(serde_json::to_string(&config).unwrap_or_else(|_| "{}".into()))
    }
}

// --- SFT Router Policy ---

#[pyclass(name = "SFTRouterPolicy")]
pub struct PySFTRouterPolicy {
    inner: friday_ai_learning::SFTRouterPolicy,
}

#[pymethods]
impl PySFTRouterPolicy {
    #[new]
    #[pyo3(signature = (min_samples=5))]
    fn new(min_samples: usize) -> Self {
        Self {
            inner: friday_ai_learning::SFTRouterPolicy::new(min_samples),
        }
    }

    fn policy_map(&self) -> std::collections::HashMap<String, String> {
        self.inner.policy_map()
    }

    #[staticmethod]
    fn classify_query(query: &str) -> &'static str {
        friday_ai_learning::SFTRouterPolicy::classify_query(query)
    }

    fn update_from_data(&self, traces_json: &str) -> PyResult<String> {
        let traces: Vec<(String, String, String, Option<f64>)> =
            serde_json::from_str(traces_json)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let result = self.inner.update_from_data(&traces);
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }
}

// --- HeuristicRewardFunction ---

#[pyclass(name = "HeuristicRewardFunction")]
pub struct PyHeuristicRewardFunction {
    inner: friday_ai_learning::HeuristicRewardFunction,
}

#[pymethods]
impl PyHeuristicRewardFunction {
    #[new]
    #[pyo3(signature = (weight_latency=0.4, weight_cost=0.3, weight_efficiency=0.3, max_latency=30.0, max_cost=0.01))]
    fn new(
        weight_latency: f64,
        weight_cost: f64,
        weight_efficiency: f64,
        max_latency: f64,
        max_cost: f64,
    ) -> Self {
        Self {
            inner: friday_ai_learning::HeuristicRewardFunction::new(
                weight_latency,
                weight_cost,
                weight_efficiency,
                max_latency,
                max_cost,
            ),
        }
    }

    fn compute(
        &self,
        latency_seconds: f64,
        cost_usd: f64,
        prompt_tokens: u64,
        completion_tokens: u64,
    ) -> f64 {
        self.inner
            .compute(latency_seconds, cost_usd, prompt_tokens, completion_tokens)
    }
}

// --- SkillDiscovery ---

#[pyclass(name = "SkillDiscovery")]
pub struct PySkillDiscovery {
    inner: friday_ai_learning::SkillDiscovery,
}

#[pymethods]
impl PySkillDiscovery {
    #[new]
    #[pyo3(signature = (min_frequency=3, min_sequence_length=2, max_sequence_length=4, min_outcome=0.5))]
    fn new(
        min_frequency: usize,
        min_sequence_length: usize,
        max_sequence_length: usize,
        min_outcome: f64,
    ) -> Self {
        Self {
            inner: friday_ai_learning::SkillDiscovery::new(
                min_frequency,
                min_sequence_length,
                max_sequence_length,
                min_outcome,
            ),
        }
    }

    fn analyze(&mut self, traces_json: &str) -> PyResult<String> {
        let traces: Vec<(Vec<String>, f64, String)> = serde_json::from_str(traces_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        self.inner.analyze(&traces);
        Ok(serde_json::to_string(&self.inner.to_manifests()).unwrap_or_default())
    }
}

// --- TraceDrivenPolicy ---

#[pyclass(name = "TraceDrivenPolicy")]
pub struct PyTraceDrivenPolicy {
    inner: friday_ai_learning::TraceDrivenPolicy,
}

#[pymethods]
impl PyTraceDrivenPolicy {
    #[new]
    #[pyo3(signature = (available_models=vec![], default_model="", fallback_model=""))]
    fn new(available_models: Vec<String>, default_model: &str, fallback_model: &str) -> Self {
        Self {
            inner: friday_ai_learning::TraceDrivenPolicy::new(
                available_models,
                default_model.to_string(),
                fallback_model.to_string(),
            ),
        }
    }

    fn select_model(&self, query: &str) -> String {
        self.inner.select_model(query)
    }

    fn policy_map(&self) -> std::collections::HashMap<String, String> {
        self.inner.policy_map()
    }

    #[pyo3(signature = (query, model, outcome=None, feedback=None))]
    fn observe(&self, query: &str, model: &str, outcome: Option<String>, feedback: Option<f64>) {
        self.inner
            .observe(query, model, outcome.as_deref(), feedback);
    }
}

// --- AgentAdvisorPolicy ---

#[pyclass(name = "AgentAdvisorPolicy")]
pub struct PyAgentAdvisorPolicy {
    inner: friday_ai_learning::AgentAdvisorPolicy,
}

#[pymethods]
impl PyAgentAdvisorPolicy {
    #[new]
    #[pyo3(signature = (max_traces=50))]
    fn new(max_traces: usize) -> Self {
        Self {
            inner: friday_ai_learning::AgentAdvisorPolicy::new(max_traces),
        }
    }

    fn analyze_patterns(&self, traces_json: &str) -> PyResult<String> {
        let traces: Vec<friday_ai_learning::TraceInfo> = serde_json::from_str(traces_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let recs = self.inner.analyze_patterns(&traces);
        Ok(serde_json::to_string(&recs).unwrap_or_default())
    }

    #[staticmethod]
    fn classify(query: &str) -> &'static str {
        friday_ai_learning::AgentAdvisorPolicy::classify(query)
    }
}

// --- ICLUpdaterPolicy ---

#[pyclass(name = "ICLUpdaterPolicy")]
pub struct PyICLUpdaterPolicy {
    inner: friday_ai_learning::ICLUpdaterPolicy,
}

#[pymethods]
impl PyICLUpdaterPolicy {
    #[new]
    #[pyo3(signature = (min_score=0.7, max_examples=20, min_skill_occurrences=3))]
    fn new(min_score: f64, max_examples: usize, min_skill_occurrences: usize) -> Self {
        Self {
            inner: friday_ai_learning::ICLUpdaterPolicy::new(
                min_score,
                max_examples,
                min_skill_occurrences,
            ),
        }
    }

    fn add_example(&mut self, query: &str, response: &str, outcome: f64) -> bool {
        self.inner.add_example(
            query.to_string(),
            response.to_string(),
            outcome,
            std::collections::HashMap::new(),
        )
    }

    fn rollback(&mut self, version: u32) {
        self.inner.rollback(version);
    }

    fn get_examples(&self, query_class: &str, top_k: usize) -> String {
        serde_json::to_string(&self.inner.get_examples(query_class, top_k)).unwrap_or_default()
    }

    #[getter]
    fn version(&self) -> u32 {
        self.inner.version()
    }
}

// --- TrainingDataMiner ---

#[pyclass(name = "TrainingDataMiner")]
pub struct PyTrainingDataMiner {
    inner: friday_ai_learning::TrainingDataMiner,
}

#[pymethods]
impl PyTrainingDataMiner {
    #[new]
    #[pyo3(signature = (min_quality=0.7, min_samples_per_class=1))]
    fn new(min_quality: f64, min_samples_per_class: usize) -> Self {
        Self {
            inner: friday_ai_learning::TrainingDataMiner::new(min_quality, min_samples_per_class),
        }
    }

    fn extract_sft_pairs(&self, traces_json: &str) -> PyResult<String> {
        let traces: Vec<friday_ai_learning::MinerTraceData> = serde_json::from_str(traces_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let pairs = self.inner.extract_sft_pairs(&traces);
        Ok(serde_json::to_string(&pairs).unwrap_or_default())
    }

    fn extract_routing_pairs(&self, traces_json: &str) -> PyResult<String> {
        let traces: Vec<friday_ai_learning::MinerTraceData> = serde_json::from_str(traces_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let pairs = self.inner.extract_routing_pairs(&traces);
        Ok(serde_json::to_string(&pairs).unwrap_or_default())
    }
}

// --- AgentConfigEvolver ---

#[pyclass(name = "AgentConfigEvolver")]
pub struct PyAgentConfigEvolver {
    inner: friday_ai_learning::AgentConfigEvolver,
}

#[pymethods]
impl PyAgentConfigEvolver {
    #[new]
    #[pyo3(signature = (min_quality=0.5))]
    fn new(min_quality: f64) -> Self {
        Self {
            inner: friday_ai_learning::AgentConfigEvolver::new(min_quality),
        }
    }

    fn analyze(&self, traces_json: &str) -> PyResult<String> {
        let traces: Vec<friday_ai_learning::EvolutionTraceData> =
            serde_json::from_str(traces_json)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let recs = self.inner.analyze(&traces);
        Ok(serde_json::to_string(&recs).unwrap_or_default())
    }
}

// --- MultiObjectiveReward ---

#[pyclass(name = "MultiObjectiveReward")]
pub struct PyMultiObjectiveReward {
    inner: friday_ai_learning::MultiObjectiveReward,
}

#[pymethods]
impl PyMultiObjectiveReward {
    #[new]
    fn new() -> Self {
        Self {
            inner: friday_ai_learning::MultiObjectiveReward::new(
                friday_ai_learning::RewardWeights::default(),
                friday_ai_learning::Normalizers::default(),
            ),
        }
    }

    fn compute(&self, episode_json: &str) -> PyResult<f64> {
        let ep: friday_ai_learning::Episode = serde_json::from_str(episode_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        Ok(self.inner.compute(&ep))
    }
}

// --- LearningOrchestrator ---

#[pyclass(name = "LearningOrchestrator")]
pub struct PyLearningOrchestrator {
    inner: friday_ai_learning::LearningOrchestrator,
}

#[pymethods]
impl PyLearningOrchestrator {
    #[new]
    #[pyo3(signature = (min_improvement=0.02, min_sft_pairs=10, min_quality=0.7))]
    fn new(min_improvement: f64, min_sft_pairs: usize, min_quality: f64) -> Self {
        Self {
            inner: friday_ai_learning::LearningOrchestrator::new(
                min_improvement,
                min_sft_pairs,
                min_quality,
            ),
        }
    }

    #[pyo3(signature = (sft_pairs, routing_count, agent_count, recs_count, baseline=None, post=None))]
    fn evaluate_cycle(
        &self,
        sft_pairs: usize,
        routing_count: usize,
        agent_count: usize,
        recs_count: usize,
        baseline: Option<f64>,
        post: Option<f64>,
    ) -> String {
        let result = self.inner.evaluate_cycle(
            sft_pairs,
            routing_count,
            agent_count,
            recs_count,
            baseline,
            post,
        );
        serde_json::to_string(&result).unwrap_or_default()
    }
}
