//! PyO3 bindings for A2A (Agent-to-Agent) protocol types and task store.

use pyo3::prelude::*;

#[pyclass(name = "AgentCard")]
pub struct PyAgentCard {
    inner: openjarvis_a2a::AgentCard,
}

#[pymethods]
impl PyAgentCard {
    #[new]
    #[pyo3(signature = (name, description, version, url))]
    fn new(name: &str, description: &str, version: &str, url: &str) -> Self {
        Self {
            inner: openjarvis_a2a::AgentCard::new(name, description, version, url),
        }
    }

    fn with_skills(&mut self, skills: Vec<String>) {
        let refs: Vec<&str> = skills.iter().map(|s| s.as_str()).collect();
        self.inner = self.inner.clone().with_skills(&refs);
    }

    fn with_modes(&mut self, modes: Vec<String>) {
        let refs: Vec<&str> = modes.iter().map(|s| s.as_str()).collect();
        self.inner = self.inner.clone().with_modes(&refs);
    }

    fn to_json(&self) -> String {
        serde_json::to_string(&self.inner).unwrap_or_default()
    }

    #[getter]
    fn name(&self) -> &str {
        &self.inner.name
    }

    #[getter]
    fn description(&self) -> &str {
        &self.inner.description
    }

    #[getter]
    fn version(&self) -> &str {
        &self.inner.version
    }

    #[getter]
    fn url(&self) -> &str {
        &self.inner.url
    }

    #[getter]
    fn skills(&self) -> Vec<String> {
        self.inner.skills.clone()
    }
}

#[pyclass(name = "A2ATaskStore")]
pub struct PyA2ATaskStore {
    inner: openjarvis_a2a::A2ATaskStore,
}

#[pymethods]
impl PyA2ATaskStore {
    #[new]
    fn new() -> Self {
        Self {
            inner: openjarvis_a2a::A2ATaskStore::new(),
        }
    }

    fn create_task(&mut self, input: &str) -> String {
        let task = self.inner.create_task(input);
        serde_json::to_string(&task).unwrap_or_default()
    }

    fn get_task(&self, id: &str) -> Option<String> {
        self.inner
            .get_task(id)
            .map(|t| serde_json::to_string(t).unwrap_or_default())
    }

    fn update_state(&mut self, id: &str, state: &str) -> bool {
        let s = match state {
            "pending" => openjarvis_a2a::TaskState::Pending,
            "active" => openjarvis_a2a::TaskState::Active,
            "completed" => openjarvis_a2a::TaskState::Completed,
            "cancelled" => openjarvis_a2a::TaskState::Cancelled,
            "failed" => openjarvis_a2a::TaskState::Failed,
            _ => return false,
        };
        self.inner.update_state(id, s)
    }

    fn set_output(&mut self, id: &str, output: &str) -> bool {
        self.inner.set_output(id, output)
    }

    fn list_tasks(&self) -> String {
        serde_json::to_string(self.inner.list_tasks()).unwrap_or_default()
    }
}

#[pyfunction]
pub fn parse_a2a_request(json_str: &str) -> PyResult<String> {
    let req = openjarvis_a2a::parse_request(json_str)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))?;
    Ok(serde_json::to_string(&req).unwrap_or_default())
}
