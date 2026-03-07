//! PyO3 bindings for composable recipes.

use pyo3::prelude::*;

#[pyclass(name = "Recipe")]
pub struct PyRecipe {
    inner: openjarvis_recipes::Recipe,
}

#[pymethods]
impl PyRecipe {
    #[getter]
    fn name(&self) -> &str {
        &self.inner.name
    }

    #[getter]
    fn description(&self) -> Option<&str> {
        self.inner.description.as_deref()
    }

    #[getter]
    fn model(&self) -> Option<&str> {
        self.inner.model.as_deref()
    }

    #[getter]
    fn engine_key(&self) -> Option<&str> {
        self.inner.engine_key.as_deref()
    }

    #[getter]
    fn agent_type(&self) -> Option<&str> {
        self.inner.agent_type.as_deref()
    }

    #[getter]
    fn max_turns(&self) -> Option<usize> {
        self.inner.max_turns
    }

    #[getter]
    fn temperature(&self) -> Option<f64> {
        self.inner.temperature
    }

    #[getter]
    fn tools(&self) -> Option<Vec<String>> {
        self.inner.tools.clone()
    }

    fn to_builder_kwargs(&self) -> String {
        let kwargs = self.inner.to_builder_kwargs();
        serde_json::to_string(&kwargs).unwrap_or_default()
    }

    fn to_json(&self) -> String {
        serde_json::to_string(&self.inner).unwrap_or_default()
    }
}

#[pyfunction]
pub fn load_recipe(toml_str: &str) -> PyResult<PyRecipe> {
    let recipe = openjarvis_recipes::load_recipe(toml_str)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))?;
    Ok(PyRecipe { inner: recipe })
}
