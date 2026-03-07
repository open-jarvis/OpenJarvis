//! PyO3 bindings for skill manifests and verification.

use pyo3::prelude::*;

#[pyclass(name = "SkillManifest")]
pub struct PySkillManifest {
    inner: openjarvis_skills::SkillManifest,
}

#[pymethods]
impl PySkillManifest {
    #[getter]
    fn name(&self) -> &str {
        &self.inner.name
    }

    #[getter]
    fn version(&self) -> &str {
        &self.inner.version
    }

    #[getter]
    fn description(&self) -> &str {
        &self.inner.description
    }

    #[getter]
    fn author(&self) -> &str {
        &self.inner.author
    }

    #[getter]
    fn steps_count(&self) -> usize {
        self.inner.steps.len()
    }

    #[getter]
    fn required_capabilities(&self) -> Vec<String> {
        self.inner.required_capabilities.clone()
    }

    fn to_json(&self) -> String {
        serde_json::to_string(&self.inner).unwrap_or_default()
    }

    fn manifest_bytes(&self) -> Vec<u8> {
        self.inner.manifest_bytes()
    }

    fn verify_signature(&self, public_key_hex: &str) -> bool {
        let key_bytes: Vec<u8> = (0..public_key_hex.len())
            .step_by(2)
            .filter_map(|i| u8::from_str_radix(&public_key_hex[i..i + 2], 16).ok())
            .collect();
        openjarvis_skills::verify_signature(&self.inner, &key_bytes)
    }
}

#[pyfunction]
pub fn load_skill(toml_str: &str) -> PyResult<PySkillManifest> {
    let manifest = openjarvis_skills::load_skill(toml_str)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))?;
    Ok(PySkillManifest { inner: manifest })
}
