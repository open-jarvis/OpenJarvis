//! PyO3 bindings for trace types.

use pyo3::prelude::*;
use std::sync::Arc;

#[pyclass(name = "TraceStore")]
pub struct PyTraceStore {
    pub inner: Arc<openjarvis_traces::TraceStore>,
}

#[pymethods]
impl PyTraceStore {
    #[new]
    #[pyo3(signature = (path=None))]
    fn new(path: Option<&str>) -> PyResult<Self> {
        let inner = match path {
            Some(p) => openjarvis_traces::TraceStore::new(std::path::Path::new(p)),
            None => openjarvis_traces::TraceStore::in_memory(),
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
}

#[pyclass(name = "TraceCollector")]
pub struct PyTraceCollector {
    inner: openjarvis_traces::TraceCollector,
}

#[pymethods]
impl PyTraceCollector {
    #[new]
    fn new(store: &PyTraceStore) -> Self {
        Self {
            inner: openjarvis_traces::TraceCollector::new(Arc::clone(&store.inner)),
        }
    }

    fn active_count(&self) -> usize {
        self.inner.active_count()
    }
}

/// TraceAnalyzer wraps stats computation over a TraceStore.
/// Since the Rust TraceAnalyzer has a lifetime parameter, we own the store
/// and create the analyzer on each call.
#[pyclass(name = "TraceAnalyzer")]
pub struct PyTraceAnalyzer {
    store: Arc<openjarvis_traces::TraceStore>,
}

#[pymethods]
impl PyTraceAnalyzer {
    #[new]
    fn new(store: &PyTraceStore) -> Self {
        Self {
            store: Arc::clone(&store.inner),
        }
    }

    fn stats(&self) -> PyResult<String> {
        let analyzer = openjarvis_traces::TraceAnalyzer::new(&self.store);
        let stats = analyzer
            .overall_stats()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&stats).unwrap_or_default())
    }

    fn stats_by_agent(&self) -> PyResult<String> {
        let analyzer = openjarvis_traces::TraceAnalyzer::new(&self.store);
        let stats = analyzer
            .stats_by_agent()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&stats).unwrap_or_default())
    }

    fn stats_by_model(&self) -> PyResult<String> {
        let analyzer = openjarvis_traces::TraceAnalyzer::new(&self.store);
        let stats = analyzer
            .stats_by_model()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&stats).unwrap_or_default())
    }
}
