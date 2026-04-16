//! PyO3 bindings for storage/memory backends.

use openjarvis_tools::storage::MemoryBackend;
use pyo3::prelude::*;
use serde_json::Value;

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

#[pyclass(name = "FAISSMemory")]
pub struct PyFAISSMemory {
    inner: openjarvis_tools::storage::FAISSMemory,
}

#[pymethods]
impl PyFAISSMemory {
    #[new]
    #[pyo3(signature = (path=":memory:", dim=128))]
    fn new(path: &str, dim: usize) -> PyResult<Self> {
        let inner = openjarvis_tools::storage::FAISSMemory::new(std::path::Path::new(path), dim)
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

#[pyclass(name = "ColBERTMemory")]
pub struct PyColBERTMemory {
    inner: openjarvis_tools::storage::ColBERTMemory,
}

#[pymethods]
impl PyColBERTMemory {
    #[new]
    #[pyo3(signature = (path=":memory:", token_dim=64))]
    fn new(path: &str, token_dim: usize) -> PyResult<Self> {
        let inner =
            openjarvis_tools::storage::ColBERTMemory::new(std::path::Path::new(path), token_dim)
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

#[pyclass(name = "HybridMemory")]
pub struct PyHybridMemory {
    inner: openjarvis_tools::storage::HybridMemory,
}

#[pymethods]
impl PyHybridMemory {
    /// Create a HybridMemory combining named backends.
    ///
    /// `backend_keys` is a list of strings like `["sqlite", "bm25"]`.
    /// Supported keys: "sqlite", "bm25", "faiss", "colbert".
    #[new]
    #[pyo3(signature = (backend_keys))]
    fn new(backend_keys: Vec<String>) -> PyResult<Self> {
        let mut backends: Vec<Box<dyn MemoryBackend>> = Vec::new();
        for key in &backend_keys {
            let backend: Box<dyn MemoryBackend> = match key.as_str() {
                "sqlite" => {
                    let m = openjarvis_tools::storage::SQLiteMemory::new(
                        std::path::Path::new(":memory:"),
                    )
                    .map_err(|e| {
                        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string())
                    })?;
                    Box::new(m)
                }
                "bm25" => Box::new(openjarvis_tools::storage::BM25Memory::default()),
                "faiss" => {
                    let m = openjarvis_tools::storage::FAISSMemory::in_memory().map_err(|e| {
                        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string())
                    })?;
                    Box::new(m)
                }
                "colbert" => {
                    let m =
                        openjarvis_tools::storage::ColBERTMemory::in_memory().map_err(|e| {
                            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string())
                        })?;
                    Box::new(m)
                }
                other => {
                    return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                        "Unknown backend key: {}. Supported: sqlite, bm25, faiss, colbert",
                        other
                    )));
                }
            };
            backends.push(backend);
        }
        Ok(Self {
            inner: openjarvis_tools::storage::HybridMemory::new(backends),
        })
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

// ---------------------------------------------------------------------------
// Synapse memory backend (MemoryBackend adapter + raw emit/query)
// ---------------------------------------------------------------------------

#[pyclass(name = "SynapseMemory")]
pub struct PySynapseMemory {
    inner: openjarvis_tools::storage::SynapseMemory,
}

#[pymethods]
impl PySynapseMemory {
    #[new]
    #[pyo3(signature = (url="http://localhost:8080", store_event="store", retrieve_query="Retrieve", delete_event="delete"))]
    fn new(
        url: &str,
        store_event: &str,
        retrieve_query: &str,
        delete_event: &str,
    ) -> PyResult<Self> {
        let inner =
            openjarvis_tools::storage::SynapseMemory::new(url, store_event, retrieve_query, delete_event)
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

    fn emit(&self, event: &str, payload_json: &str) -> PyResult<String> {
        let payload: Value = serde_json::from_str(payload_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let result = self
            .inner
            .emit(event, &payload)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn query_raw(&self, name: &str, params_json: &str) -> PyResult<String> {
        let params: Value = serde_json::from_str(params_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let result = self
            .inner
            .query_raw(name, &params)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn health(&self) -> PyResult<String> {
        let result = self
            .inner
            .health()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn status(&self) -> PyResult<String> {
        let result = self
            .inner
            .status()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn inspect_raw(&self) -> PyResult<String> {
        let result = self
            .inner
            .inspect_raw()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn ping(&self) -> bool {
        self.inner.ping()
    }
}

// ---------------------------------------------------------------------------
// Standalone Synapse client (raw emit/query without MemoryBackend adapter)
// ---------------------------------------------------------------------------

#[pyclass(name = "SynapseClient")]
pub struct PySynapseClient {
    client: synapse_client::Client,
    rt: tokio::runtime::Runtime,
}

#[pymethods]
impl PySynapseClient {
    #[new]
    #[pyo3(signature = (url="http://localhost:8080"))]
    fn new(url: &str) -> PyResult<Self> {
        let rt = tokio::runtime::Runtime::new()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(Self {
            client: synapse_client::Client::new(url),
            rt,
        })
    }

    fn emit(&self, event: &str, payload_json: &str) -> PyResult<String> {
        let payload: Value = serde_json::from_str(payload_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let result = self
            .rt
            .block_on(self.client.emit(event, payload))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn query(&self, name: &str, params_json: &str) -> PyResult<String> {
        let params: Value = serde_json::from_str(params_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let result = self
            .rt
            .block_on(self.client.query(name, params))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn health(&self) -> PyResult<String> {
        let result = self
            .rt
            .block_on(self.client.health())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn status(&self) -> PyResult<String> {
        let result = self
            .rt
            .block_on(self.client.status())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn inspect(&self) -> PyResult<String> {
        let result = self
            .rt
            .block_on(self.client.inspect())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn reload(&self) -> PyResult<String> {
        let result = self
            .rt
            .block_on(self.client.reload())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn clear(&self) -> PyResult<String> {
        let result = self
            .rt
            .block_on(self.client.clear())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }

    fn ping(&self) -> bool {
        self.rt.block_on(self.client.ping())
    }
}
