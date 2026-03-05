//! PyO3 bindings for core types.

use pyo3::prelude::*;
use std::collections::HashMap;

#[pyclass(name = "Message")]
#[derive(Clone)]
pub struct PyMessage {
    #[pyo3(get, set)]
    pub role: String,
    #[pyo3(get, set)]
    pub content: String,
    #[pyo3(get, set)]
    pub name: Option<String>,
    #[pyo3(get, set)]
    pub tool_call_id: Option<String>,
}

#[pymethods]
impl PyMessage {
    #[new]
    fn new(role: String, content: String) -> Self {
        Self {
            role,
            content,
            name: None,
            tool_call_id: None,
        }
    }

    fn __repr__(&self) -> String {
        format!("Message(role='{}', content='{}')", self.role, &self.content[..self.content.len().min(50)])
    }
}

impl PyMessage {
    pub fn to_core(&self) -> openjarvis_core::Message {
        let role = match self.role.as_str() {
            "system" => openjarvis_core::Role::System,
            "assistant" => openjarvis_core::Role::Assistant,
            "tool" => openjarvis_core::Role::Tool,
            _ => openjarvis_core::Role::User,
        };
        openjarvis_core::Message {
            role,
            content: self.content.clone(),
            name: self.name.clone(),
            tool_calls: None,
            tool_call_id: self.tool_call_id.clone(),
            metadata: HashMap::new(),
        }
    }
}

#[pyclass(name = "ToolResult")]
#[derive(Clone)]
pub struct PyToolResult {
    #[pyo3(get)]
    pub tool_name: String,
    #[pyo3(get)]
    pub content: String,
    #[pyo3(get)]
    pub success: bool,
}

#[pymethods]
impl PyToolResult {
    #[new]
    fn new(tool_name: String, content: String, success: bool) -> Self {
        Self { tool_name, content, success }
    }

    fn __repr__(&self) -> String {
        format!("ToolResult(tool='{}', success={})", self.tool_name, self.success)
    }
}

#[pyclass(name = "ToolCall")]
#[derive(Clone)]
pub struct PyToolCall {
    #[pyo3(get, set)]
    pub id: String,
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub arguments: String,
}

#[pymethods]
impl PyToolCall {
    #[new]
    fn new(id: String, name: String, arguments: String) -> Self {
        Self { id, name, arguments }
    }
}

#[pyclass(name = "Config")]
pub struct PyConfig {
    pub inner: openjarvis_core::JarvisConfig,
}

#[pymethods]
impl PyConfig {
    #[new]
    fn new() -> Self {
        Self {
            inner: openjarvis_core::JarvisConfig::default(),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Config(engine={}, model={})",
            self.inner.engine.default, self.inner.intelligence.default_model
        )
    }

    #[getter]
    fn engine_default(&self) -> String {
        self.inner.engine.default.clone()
    }

    #[getter]
    fn model_default(&self) -> String {
        self.inner.intelligence.default_model.clone()
    }
}

#[pyclass(name = "EventBus")]
pub struct PyEventBus {
    pub inner: std::sync::Arc<openjarvis_core::EventBus>,
}

#[pymethods]
impl PyEventBus {
    #[new]
    fn new() -> Self {
        Self {
            inner: std::sync::Arc::new(openjarvis_core::EventBus::new(true)),
        }
    }

    fn history_len(&self) -> usize {
        self.inner.history().len()
    }
}

#[pyclass(name = "ModelSpec")]
#[derive(Clone)]
pub struct PyModelSpec {
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub params_b: f64,
    #[pyo3(get, set)]
    pub context_length: usize,
}

#[pymethods]
impl PyModelSpec {
    #[new]
    fn new(name: String, params_b: f64, context_length: usize) -> Self {
        Self { name, params_b, context_length }
    }
}

#[pyclass(name = "RoutingContext")]
#[derive(Clone)]
pub struct PyRoutingContext {
    #[pyo3(get, set)]
    pub query: String,
    #[pyo3(get, set)]
    pub query_class: String,
}

#[pymethods]
impl PyRoutingContext {
    #[new]
    fn new(query: String) -> Self {
        Self { query, query_class: "general".into() }
    }
}

#[pyclass(name = "AgentContext")]
pub struct PyAgentContext {
    #[pyo3(get, set)]
    pub session_id: String,
}

#[pymethods]
impl PyAgentContext {
    #[new]
    fn new(session_id: String) -> Self {
        Self { session_id }
    }
}

#[pyclass(name = "AgentResult")]
#[derive(Clone)]
pub struct PyAgentResult {
    #[pyo3(get)]
    pub content: String,
    #[pyo3(get)]
    pub turns: usize,
}

#[pymethods]
impl PyAgentResult {
    fn __repr__(&self) -> String {
        format!("AgentResult(turns={}, content='{}')", self.turns, &self.content[..self.content.len().min(50)])
    }
}
