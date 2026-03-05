//! PyO3 bindings for learning/router policy types.

use openjarvis_learning::RouterPolicy;
use pyo3::prelude::*;

#[pyclass(name = "HeuristicRouter")]
pub struct PyHeuristicRouter {
    inner: openjarvis_learning::HeuristicRouter,
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
            inner: openjarvis_learning::HeuristicRouter::new(
                default_model.to_string(),
                code_model,
                math_model,
                fast_model,
            ),
        }
    }

    fn select_model(&self, query: &str, has_code: bool, has_math: bool) -> String {
        let ctx = openjarvis_core::RoutingContext {
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
    inner: openjarvis_learning::BanditRouterPolicy,
}

#[pymethods]
impl PyBanditRouterPolicy {
    #[new]
    #[pyo3(signature = (models, strategy="thompson"))]
    fn new(models: Vec<String>, strategy: &str) -> Self {
        let strat = match strategy {
            "ucb1" | "UCB1" => openjarvis_learning::bandit::BanditStrategy::UCB1,
            _ => openjarvis_learning::bandit::BanditStrategy::ThompsonSampling,
        };
        Self {
            inner: openjarvis_learning::BanditRouterPolicy::new(models, strat),
        }
    }

    fn select_model(&self) -> String {
        let ctx = openjarvis_core::RoutingContext::default();
        self.inner.select_model(&ctx)
    }

    fn update(&self, model: &str, reward: f64) {
        self.inner.update(model, reward);
    }
}

#[pyclass(name = "GRPORouterPolicy")]
pub struct PyGRPORouterPolicy {
    inner: openjarvis_learning::GRPORouterPolicy,
}

#[pymethods]
impl PyGRPORouterPolicy {
    #[new]
    #[pyo3(signature = (models, temperature=1.0))]
    fn new(models: Vec<String>, temperature: f64) -> Self {
        Self {
            inner: openjarvis_learning::GRPORouterPolicy::new(models, temperature),
        }
    }

    fn select_model(&self) -> String {
        let ctx = openjarvis_core::RoutingContext::default();
        self.inner.select_model(&ctx)
    }

    fn update_weights(&self, rewards_json: &str) -> PyResult<()> {
        let rewards: Vec<(String, f64)> = serde_json::from_str(rewards_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        self.inner.update_weights(&rewards);
        Ok(())
    }
}
