//! PyO3 bindings for tool types.

use openjarvis_tools::traits::BaseTool;
use pyo3::prelude::*;
use std::sync::Arc;

#[pyclass(name = "ToolExecutor")]
pub struct PyToolExecutor {
    pub inner: Arc<openjarvis_tools::ToolExecutor>,
}

#[pymethods]
impl PyToolExecutor {
    #[new]
    fn new() -> Self {
        Self {
            inner: Arc::new(openjarvis_tools::ToolExecutor::new(None, None)),
        }
    }

    fn list_tools(&self) -> Vec<String> {
        self.inner.list_tools()
    }

    fn execute(&self, tool_name: &str, params_json: &str) -> PyResult<String> {
        let params: serde_json::Value = serde_json::from_str(params_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let result = self
            .inner
            .execute(tool_name, &params, None, None)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&result).unwrap_or_default())
    }
}

#[pyclass(name = "CalculatorTool")]
pub struct PyCalculatorTool;

#[pymethods]
impl PyCalculatorTool {
    #[new]
    fn new() -> Self {
        Self
    }

    fn execute(&self, expression: &str) -> PyResult<String> {
        let tool = openjarvis_tools::builtin::calculator::CalculatorTool;
        let params = serde_json::json!({"expression": expression});
        let result = tool
            .execute(&params)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(result.content)
    }
}

#[pyclass(name = "ThinkTool")]
pub struct PyThinkTool;

#[pymethods]
impl PyThinkTool {
    #[new]
    fn new() -> Self {
        Self
    }

    fn execute(&self, thought: &str) -> PyResult<String> {
        let tool = openjarvis_tools::builtin::think::ThinkTool;
        let params = serde_json::json!({"thought": thought});
        let result = tool
            .execute(&params)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(result.content)
    }
}

#[pyclass(name = "FileReadTool")]
pub struct PyFileReadTool;

#[pymethods]
impl PyFileReadTool {
    #[new]
    fn new() -> Self {
        Self
    }

    fn execute(&self, path: &str) -> PyResult<String> {
        let tool = openjarvis_tools::builtin::file_tools::FileReadTool;
        let params = serde_json::json!({"path": path});
        let result = tool
            .execute(&params)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(result.content)
    }
}

#[pyclass(name = "FileWriteTool")]
pub struct PyFileWriteTool;

#[pymethods]
impl PyFileWriteTool {
    #[new]
    fn new() -> Self {
        Self
    }

    fn execute(&self, path: &str, content: &str) -> PyResult<String> {
        let tool = openjarvis_tools::builtin::file_tools::FileWriteTool;
        let params = serde_json::json!({"path": path, "content": content});
        let result = tool
            .execute(&params)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(result.content)
    }
}

#[pyclass(name = "ShellExecTool")]
pub struct PyShellExecTool;

#[pymethods]
impl PyShellExecTool {
    #[new]
    fn new() -> Self {
        Self
    }

    #[pyo3(signature = (command, cwd=None))]
    fn execute(&self, command: &str, cwd: Option<&str>) -> PyResult<String> {
        let tool = openjarvis_tools::builtin::shell::ShellExecTool;
        let mut params = serde_json::json!({"command": command});
        if let Some(cwd) = cwd {
            params["cwd"] = serde_json::Value::String(cwd.to_string());
        }
        let result = tool
            .execute(&params)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(result.content)
    }
}

#[pyclass(name = "HttpRequestTool")]
pub struct PyHttpRequestTool;

#[pymethods]
impl PyHttpRequestTool {
    #[new]
    fn new() -> Self {
        Self
    }

    #[pyo3(signature = (url, method="GET", body=None))]
    fn execute(&self, url: &str, method: &str, body: Option<&str>) -> PyResult<String> {
        let tool = openjarvis_tools::builtin::http_tools::HttpRequestTool;
        let mut params = serde_json::json!({"url": url, "method": method});
        if let Some(body) = body {
            params["body"] = serde_json::Value::String(body.to_string());
        }
        let result = tool
            .execute(&params)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(result.content)
    }
}

#[pyclass(name = "GitStatusTool")]
pub struct PyGitStatusTool;

#[pymethods]
impl PyGitStatusTool {
    #[new]
    fn new() -> Self {
        Self
    }

    #[pyo3(signature = (cwd=None))]
    fn execute(&self, cwd: Option<&str>) -> PyResult<String> {
        let tool = openjarvis_tools::builtin::git_tools::GitStatusTool;
        let mut params = serde_json::json!({});
        if let Some(cwd) = cwd {
            params["cwd"] = serde_json::Value::String(cwd.to_string());
        }
        let result = tool
            .execute(&params)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(result.content)
    }
}

#[pyclass(name = "GitDiffTool")]
pub struct PyGitDiffTool;

#[pymethods]
impl PyGitDiffTool {
    #[new]
    fn new() -> Self {
        Self
    }

    #[pyo3(signature = (cwd=None))]
    fn execute(&self, cwd: Option<&str>) -> PyResult<String> {
        let tool = openjarvis_tools::builtin::git_tools::GitDiffTool;
        let mut params = serde_json::json!({});
        if let Some(cwd) = cwd {
            params["cwd"] = serde_json::Value::String(cwd.to_string());
        }
        let result = tool
            .execute(&params)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(result.content)
    }
}

#[pyclass(name = "GitLogTool")]
pub struct PyGitLogTool;

#[pymethods]
impl PyGitLogTool {
    #[new]
    fn new() -> Self {
        Self
    }

    #[pyo3(signature = (cwd=None, count=None))]
    fn execute(&self, cwd: Option<&str>, count: Option<u32>) -> PyResult<String> {
        let tool = openjarvis_tools::builtin::git_tools::GitLogTool;
        let mut params = serde_json::json!({});
        if let Some(cwd) = cwd {
            params["cwd"] = serde_json::Value::String(cwd.to_string());
        }
        if let Some(count) = count {
            params["count"] = serde_json::Value::Number(count.into());
        }
        let result = tool
            .execute(&params)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(result.content)
    }
}
