//! PyO3 bindings for agent types.
//!
//! At the Python boundary, agents use `Box<dyn OjAgent>` for type erasure
//! since Python can't handle Rust generics. The shared tokio Runtime
//! bridges async→sync.

use crate::core::PyAgentResult;
use crate::RUNTIME;
use openjarvis_agents::OjAgent;
use pyo3::prelude::*;
use std::sync::Arc;

/// Python wrapper for SimpleAgent (type-erased via Box<dyn OjAgent>).
#[pyclass(name = "SimpleAgent")]
pub struct PySimpleAgent {
    inner: Box<dyn OjAgent>,
}

#[pymethods]
impl PySimpleAgent {
    /// Create a SimpleAgent backed by an Engine enum.
    #[new]
    #[pyo3(signature = (engine_key="ollama", host="http://localhost:11434", model="qwen3:8b", system_prompt="You are a helpful assistant.", temperature=0.7))]
    fn new(
        engine_key: &str,
        host: &str,
        model: &str,
        system_prompt: &str,
        temperature: f64,
    ) -> PyResult<Self> {
        let config = openjarvis_core::JarvisConfig::default();
        let engine = openjarvis_engine::get_engine_static(&config, Some(engine_key))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let adapter = openjarvis_engine::rig_adapter::RigModelAdapter::new(
            Arc::new(engine),
            model.to_string(),
        );
        let agent = openjarvis_agents::SimpleAgent::new(adapter, system_prompt, temperature);
        Ok(Self {
            inner: Box::new(agent),
        })
    }

    fn agent_id(&self) -> &str {
        self.inner.agent_id()
    }

    fn accepts_tools(&self) -> bool {
        self.inner.accepts_tools()
    }

    fn run(&self, input: &str) -> PyResult<PyAgentResult> {
        let result = RUNTIME
            .block_on(self.inner.run(input, None))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(PyAgentResult {
            content: result.content,
            turns: result.turns,
        })
    }
}

/// Python wrapper for OrchestratorAgent.
#[pyclass(name = "OrchestratorAgent")]
pub struct PyOrchestratorAgent {
    inner: Box<dyn OjAgent>,
}

#[pymethods]
impl PyOrchestratorAgent {
    #[new]
    #[pyo3(signature = (engine_key="ollama", host="http://localhost:11434", model="qwen3:8b", system_prompt="You are a helpful orchestrator agent.", max_turns=10, temperature=0.7))]
    fn new(
        engine_key: &str,
        host: &str,
        model: &str,
        system_prompt: &str,
        max_turns: usize,
        temperature: f64,
    ) -> PyResult<Self> {
        let config = openjarvis_core::JarvisConfig::default();
        let engine = openjarvis_engine::get_engine_static(&config, Some(engine_key))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let adapter = openjarvis_engine::rig_adapter::RigModelAdapter::new(
            Arc::new(engine),
            model.to_string(),
        );
        let executor = Arc::new(openjarvis_tools::ToolExecutor::new(None, None));
        let agent = openjarvis_agents::OrchestratorAgent::new(
            adapter,
            system_prompt,
            executor,
            max_turns,
            temperature,
        );
        Ok(Self {
            inner: Box::new(agent),
        })
    }

    fn agent_id(&self) -> &str {
        self.inner.agent_id()
    }

    fn accepts_tools(&self) -> bool {
        self.inner.accepts_tools()
    }

    fn run(&self, input: &str) -> PyResult<PyAgentResult> {
        let result = RUNTIME
            .block_on(self.inner.run(input, None))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(PyAgentResult {
            content: result.content,
            turns: result.turns,
        })
    }
}

/// Python wrapper for NativeReActAgent.
#[pyclass(name = "NativeReActAgent")]
pub struct PyNativeReActAgent {
    inner: Box<dyn OjAgent>,
}

#[pymethods]
impl PyNativeReActAgent {
    #[new]
    #[pyo3(signature = (engine_key="ollama", host="http://localhost:11434", model="qwen3:8b", max_turns=10, temperature=0.7))]
    fn new(
        engine_key: &str,
        host: &str,
        model: &str,
        max_turns: usize,
        temperature: f64,
    ) -> PyResult<Self> {
        let config = openjarvis_core::JarvisConfig::default();
        let engine = openjarvis_engine::get_engine_static(&config, Some(engine_key))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let adapter = openjarvis_engine::rig_adapter::RigModelAdapter::new(
            Arc::new(engine),
            model.to_string(),
        );
        let executor = Arc::new(openjarvis_tools::ToolExecutor::new(None, None));
        let agent = openjarvis_agents::NativeReActAgent::new(
            adapter,
            executor,
            max_turns,
            temperature,
        );
        Ok(Self {
            inner: Box::new(agent),
        })
    }

    fn agent_id(&self) -> &str {
        self.inner.agent_id()
    }

    fn accepts_tools(&self) -> bool {
        self.inner.accepts_tools()
    }

    fn run(&self, input: &str) -> PyResult<PyAgentResult> {
        let result = RUNTIME
            .block_on(self.inner.run(input, None))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(PyAgentResult {
            content: result.content,
            turns: result.turns,
        })
    }
}

/// Python wrapper for LoopGuard.
#[pyclass(name = "LoopGuard")]
pub struct PyLoopGuard {
    inner: openjarvis_agents::LoopGuard,
}

#[pymethods]
impl PyLoopGuard {
    #[new]
    #[pyo3(signature = (max_identical=50, max_ping_pong=4, poll_budget=100))]
    fn new(max_identical: usize, max_ping_pong: usize, poll_budget: usize) -> Self {
        Self {
            inner: openjarvis_agents::LoopGuard::new(max_identical, max_ping_pong, poll_budget),
        }
    }

    fn check(&mut self, tool_name: &str, arguments: &str) -> Option<String> {
        self.inner.check(tool_name, arguments)
    }

    fn reset(&mut self) {
        self.inner.reset()
    }
}
