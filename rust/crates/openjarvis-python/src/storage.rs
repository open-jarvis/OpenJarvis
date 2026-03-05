//! PyO3 bindings for storage/memory backends.

use openjarvis_tools::storage::MemoryBackend;
use pyo3::prelude::*;

#[pyclass(name = "SQLiteMemory")]
pub struct PySQLiteMemory {
    inner: openjarvis_tools::storage::SQLiteMemory,
}

#[pymethods]
impl PySQLiteMemory {
    #[new]
    #[pyo3(signature = (path=":memory:"))]
    fn new(path: &str) -> PyResult<Self> {
        let inner = openjarvis_tools::storage::SQLiteMemory::new(std::path::Path::new(path))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(Self { inner })
    }

    fn backend_id(&self) -> &str {
        self.inner.backend_id()
    }

    #[pyo3(signature = (content, source, metadata=None))]
    fn store(&self, content: &str, source: &str, metadata: Option<&str>) -> PyResult<String> {
        let meta = metadata
            .map(|m| serde_json::from_str(m))
            .transpose()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        self.inner
            .store(content, source, meta.as_ref())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    #[pyo3(signature = (query, top_k=5))]
    fn retrieve(&self, query: &str, top_k: usize) -> PyResult<String> {
        let results = self
            .inner
            .retrieve(query, top_k)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&results).unwrap_or_default())
    }

    fn count(&self) -> PyResult<usize> {
        self.inner
            .count()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    fn delete(&self, doc_id: &str) -> PyResult<bool> {
        self.inner
            .delete(doc_id)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    fn clear(&self) -> PyResult<()> {
        self.inner
            .clear()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }
}

#[pyclass(name = "BM25Memory")]
pub struct PyBM25Memory {
    inner: openjarvis_tools::storage::BM25Memory,
}

#[pymethods]
impl PyBM25Memory {
    #[new]
    #[pyo3(signature = (k1=1.2, b=0.75))]
    fn new(k1: f64, b: f64) -> Self {
        Self {
            inner: openjarvis_tools::storage::BM25Memory::new(k1, b),
        }
    }

    fn backend_id(&self) -> &str {
        self.inner.backend_id()
    }

    #[pyo3(signature = (content, source, metadata=None))]
    fn store(&self, content: &str, source: &str, metadata: Option<&str>) -> PyResult<String> {
        let meta = metadata
            .map(|m| serde_json::from_str(m))
            .transpose()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        self.inner
            .store(content, source, meta.as_ref())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    #[pyo3(signature = (query, top_k=5))]
    fn retrieve(&self, query: &str, top_k: usize) -> PyResult<String> {
        let results = self
            .inner
            .retrieve(query, top_k)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&results).unwrap_or_default())
    }

    fn count(&self) -> PyResult<usize> {
        self.inner
            .count()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }
}

#[pyclass(name = "KnowledgeGraphMemory")]
pub struct PyKnowledgeGraphMemory {
    inner: openjarvis_tools::storage::KnowledgeGraphMemory,
}

#[pymethods]
impl PyKnowledgeGraphMemory {
    #[new]
    #[pyo3(signature = (path=":memory:"))]
    fn new(path: &str) -> PyResult<Self> {
        let inner = openjarvis_tools::storage::KnowledgeGraphMemory::new(std::path::Path::new(path))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(Self { inner })
    }

    fn backend_id(&self) -> &str {
        self.inner.backend_id()
    }

    #[pyo3(signature = (content, source, metadata=None))]
    fn store(&self, content: &str, source: &str, metadata: Option<&str>) -> PyResult<String> {
        let meta = metadata
            .map(|m| serde_json::from_str(m))
            .transpose()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        self.inner
            .store(content, source, meta.as_ref())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    #[pyo3(signature = (query, top_k=5))]
    fn retrieve(&self, query: &str, top_k: usize) -> PyResult<String> {
        let results = self
            .inner
            .retrieve(query, top_k)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&results).unwrap_or_default())
    }

    fn count(&self) -> PyResult<usize> {
        self.inner
            .count()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }
}
