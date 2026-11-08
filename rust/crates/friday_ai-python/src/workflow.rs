//! PyO3 bindings for workflow engine.

use pyo3::prelude::*;
use std::collections::HashMap;

#[pyclass(name = "WorkflowGraph")]
pub struct PyWorkflowGraph {
    inner: friday_ai_workflow::WorkflowGraph,
}

#[pymethods]
impl PyWorkflowGraph {
    #[new]
    #[pyo3(signature = (name=""))]
    fn new(name: &str) -> Self {
        Self {
            inner: friday_ai_workflow::WorkflowGraph::new(name),
        }
    }

    fn add_node(
        &mut self,
        id: &str,
        node_type: &str,
        agent: &str,
        tools: Vec<String>,
    ) -> PyResult<()> {
        let nt = match node_type {
            "tool" => friday_ai_workflow::NodeType::Tool,
            "condition" => friday_ai_workflow::NodeType::Condition,
            "parallel" => friday_ai_workflow::NodeType::Parallel,
            "loop" => friday_ai_workflow::NodeType::Loop,
            "transform" => friday_ai_workflow::NodeType::Transform,
            _ => friday_ai_workflow::NodeType::Agent,
        };
        let node = friday_ai_workflow::WorkflowNode {
            id: id.to_string(),
            node_type: nt,
            agent: agent.to_string(),
            tools,
            config: HashMap::new(),
            condition_expr: String::new(),
            max_iterations: 10,
            transform_expr: String::new(),
        };
        self.inner
            .add_node(node)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))
    }

    fn add_edge(&mut self, source: &str, target: &str) -> PyResult<()> {
        let edge = friday_ai_workflow::WorkflowEdge {
            source: source.to_string(),
            target: target.to_string(),
            condition: String::new(),
        };
        self.inner
            .add_edge(edge)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))
    }

    fn validate(&self) -> (bool, String) {
        self.inner.validate()
    }

    fn topological_sort(&self) -> PyResult<Vec<String>> {
        self.inner
            .topological_sort()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))
    }

    fn execution_stages(&self) -> Vec<Vec<String>> {
        self.inner.execution_stages()
    }

    fn predecessors(&self, node_id: &str) -> Vec<String> {
        self.inner.predecessors(node_id)
    }

    fn successors(&self, node_id: &str) -> Vec<String> {
        self.inner.successors(node_id)
    }
}

#[pyclass(name = "WorkflowBuilder")]
pub struct PyWorkflowBuilder {
    inner: Option<friday_ai_workflow::WorkflowBuilder>,
}

#[pymethods]
impl PyWorkflowBuilder {
    #[new]
    #[pyo3(signature = (name=""))]
    fn new(name: &str) -> Self {
        Self {
            inner: Some(friday_ai_workflow::WorkflowBuilder::new(name)),
        }
    }

    fn add_agent_node(&mut self, id: &str, agent: &str) {
        if let Some(ref mut b) = self.inner {
            b.add_agent_node(id, agent);
        }
    }

    fn add_tool_node(&mut self, id: &str, tools: Vec<String>) {
        if let Some(ref mut b) = self.inner {
            b.add_tool_node(id, tools);
        }
    }

    fn connect(&mut self, source: &str, target: &str) {
        if let Some(ref mut b) = self.inner {
            b.connect(source, target);
        }
    }

    fn build(&mut self) -> PyResult<PyWorkflowGraph> {
        let builder = self.inner.take().ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("builder already consumed")
        })?;
        let graph = builder
            .build()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))?;
        Ok(PyWorkflowGraph { inner: graph })
    }
}
