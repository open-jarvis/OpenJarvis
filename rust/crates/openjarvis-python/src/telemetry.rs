//! PyO3 bindings for telemetry types.

use pyo3::prelude::*;
use std::sync::Arc;

#[pyclass(name = "TelemetryStore")]
pub struct PyTelemetryStore {
    pub inner: Arc<openjarvis_telemetry::TelemetryStore>,
}

#[pymethods]
impl PyTelemetryStore {
    #[new]
    #[pyo3(signature = (path=None))]
    fn new(path: Option<&str>) -> PyResult<Self> {
        let inner = match path {
            Some(p) => openjarvis_telemetry::TelemetryStore::new(std::path::Path::new(p)),
            None => openjarvis_telemetry::TelemetryStore::in_memory(),
        }
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    fn count(&self) -> PyResult<usize> {
        self.inner
            .count()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    fn clear(&self) -> PyResult<()> {
        self.inner
            .clear()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }
}

/// TelemetryAggregator computes aggregate stats from a TelemetryStore.
/// The Rust type is a unit struct with a static method.
#[pyclass(name = "TelemetryAggregator")]
pub struct PyTelemetryAggregator {
    store: Arc<openjarvis_telemetry::TelemetryStore>,
}

#[pymethods]
impl PyTelemetryAggregator {
    #[new]
    fn new(store: &PyTelemetryStore) -> Self {
        Self {
            store: Arc::clone(&store.inner),
        }
    }

    fn stats(&self) -> PyResult<String> {
        let stats = openjarvis_telemetry::TelemetryAggregator::stats(&self.store)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&stats).unwrap_or_default())
    }
}

#[pyclass(name = "InstrumentedEngine")]
pub struct PyInstrumentedEngine {
    inner: openjarvis_telemetry::InstrumentedEngine<openjarvis_engine::Engine>,
}

#[pymethods]
impl PyInstrumentedEngine {
    #[new]
    #[pyo3(signature = (engine_key="ollama", host="http://localhost:11434", store_path=None, agent_name="default"))]
    fn new(engine_key: &str, host: &str, store_path: Option<&str>, agent_name: &str) -> PyResult<Self> {
        let config = openjarvis_core::JarvisConfig::default();
        let engine = openjarvis_engine::get_engine_static(&config, Some(engine_key))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let store = Arc::new(match store_path {
            Some(p) => openjarvis_telemetry::TelemetryStore::new(std::path::Path::new(p)),
            None => openjarvis_telemetry::TelemetryStore::in_memory(),
        }
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?);
        Ok(Self {
            inner: openjarvis_telemetry::InstrumentedEngine::new(
                engine,
                store,
                agent_name.to_string(),
            ),
        })
    }

    fn engine_id(&self) -> &str {
        use openjarvis_engine::InferenceEngine;
        self.inner.engine_id()
    }
}
