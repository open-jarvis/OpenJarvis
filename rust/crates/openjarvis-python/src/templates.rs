//! PyO3 bindings for agent templates.

use pyo3::prelude::*;

#[pyclass(name = "AgentTemplate")]
pub struct PyAgentTemplate {
    inner: openjarvis_templates::AgentTemplate,
}

#[pymethods]
impl PyAgentTemplate {
    #[getter]
    fn name(&self) -> &str {
        &self.inner.name
    }

    #[getter]
    fn description(&self) -> &str {
        &self.inner.description
    }

    #[getter]
    fn system_prompt(&self) -> &str {
        &self.inner.system_prompt
    }

    #[getter]
    fn agent_type(&self) -> &str {
        &self.inner.agent_type
    }

    #[getter]
    fn tools(&self) -> Vec<String> {
        self.inner.tools.clone()
    }

    #[getter]
    fn max_turns(&self) -> usize {
        self.inner.max_turns
    }

    #[getter]
    fn temperature(&self) -> f64 {
        self.inner.temperature
    }

    fn to_json(&self) -> String {
        serde_json::to_string(&self.inner).unwrap_or_default()
    }
}

#[pyfunction]
pub fn load_template(toml_str: &str) -> PyResult<PyAgentTemplate> {
    let tpl = openjarvis_templates::load_template(toml_str)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))?;
    Ok(PyAgentTemplate { inner: tpl })
}
