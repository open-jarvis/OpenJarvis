//! PyO3 bindings for the MCP server.

use crate::tools::PyToolExecutor;
use pyo3::prelude::*;
use std::sync::Arc;

#[pyclass(name = "McpServer")]
pub struct PyMcpServer {
    inner: openjarvis_mcp::McpServer,
}

#[pymethods]
impl PyMcpServer {
    #[new]
    fn new(executor: &PyToolExecutor) -> Self {
        Self {
            inner: openjarvis_mcp::McpServer::new(Arc::clone(&executor.inner)),
        }
    }

    /// Process a JSON-RPC request string and return a JSON-RPC response string.
    fn handle_json(&self, json_str: &str) -> String {
        self.inner.handle_json(json_str)
    }
}
