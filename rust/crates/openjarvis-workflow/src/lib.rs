//! OpenJarvis Workflow — DAG-based workflow graph, builder, and execution planner.
//!
//! Port of `src/openjarvis/workflow/` from Python.
//! Provides cycle detection (DFS), topological sort (Kahn's algorithm),
//! parallel stage grouping, and a fluent builder API.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Node / Edge types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum NodeType {
    Agent,
    Tool,
    Condition,
    Parallel,
    Loop,
    Transform,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowNode {
    pub id: String,
    pub node_type: NodeType,
    pub agent: String,
    pub tools: Vec<String>,
    pub config: HashMap<String, serde_json::Value>,
    pub condition_expr: String,
    pub max_iterations: usize,
    pub transform_expr: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowEdge {
    pub source: String,
    pub target: String,
    pub condition: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowStepResult {
    pub node_id: String,
    pub output: serde_json::Value,
    pub success: bool,
    pub duration_ms: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowResult {
    pub workflow_name: String,
    pub steps: Vec<WorkflowStepResult>,
    pub success: bool,
    pub total_duration_ms: f64,
}

// ---------------------------------------------------------------------------
// WorkflowGraph
// ---------------------------------------------------------------------------

pub struct WorkflowGraph {
    pub name: String,
    nodes: Vec<WorkflowNode>,
    node_index: HashMap<String, usize>,
    edges: Vec<WorkflowEdge>,
}

impl WorkflowGraph {
    pub fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
            nodes: Vec::new(),
            node_index: HashMap::new(),
            edges: Vec::new(),
        }
    }

    pub fn add_node(&mut self, node: WorkflowNode) -> Result<(), String> {
        if self.node_index.contains_key(&node.id) {
            return Err(format!("duplicate node id '{}'", node.id));
        }
        let idx = self.nodes.len();
        self.node_index.insert(node.id.clone(), idx);
        self.nodes.push(node);
        Ok(())
    }

    pub fn add_edge(&mut self, edge: WorkflowEdge) -> Result<(), String> {
        if !self.node_index.contains_key(&edge.source) {
            return Err(format!("source node '{}' not found", edge.source));
        }
        if !self.node_index.contains_key(&edge.target) {
            return Err(format!("target node '{}' not found", edge.target));
        }
        self.edges.push(edge);
        Ok(())
    }

    pub fn get_node(&self, node_id: &str) -> Option<&WorkflowNode> {
        self.node_index.get(node_id).map(|&i| &self.nodes[i])
    }

    pub fn nodes(&self) -> &[WorkflowNode] {
        &self.nodes
    }

    pub fn edges(&self) -> &[WorkflowEdge] {
        &self.edges
    }

    /// DFS-based cycle detection. Returns `(is_valid, message)`.
    pub fn validate(&self) -> (bool, String) {
        let n = self.nodes.len();
        if n == 0 {
            return (true, "empty graph".to_string());
        }

        // 0 = white (unvisited), 1 = grey (in stack), 2 = black (done)
        let mut color = vec![0u8; n];

        for start in 0..n {
            if color[start] == 0 && self.dfs_has_cycle(start, &mut color) {
                return (false, "cycle detected".to_string());
            }
        }
        (true, "valid DAG".to_string())
    }

    fn dfs_has_cycle(&self, u: usize, color: &mut [u8]) -> bool {
        color[u] = 1;
        let uid = &self.nodes[u].id;
        for edge in &self.edges {
            if edge.source != *uid {
                continue;
            }
            if let Some(&vi) = self.node_index.get(&edge.target) {
                let c = color[vi];
                match c {
                    1 => return true,
                    0 if self.dfs_has_cycle(vi, color) => return true,
                    _ => {}
                }
            }
        }
        color[u] = 2;
        false
    }

    /// Kahn's algorithm for topological ordering.
    pub fn topological_sort(&self) -> Result<Vec<String>, String> {
        let n = self.nodes.len();
        let mut in_degree = vec![0usize; n];

        for edge in &self.edges {
            if let Some(&ti) = self.node_index.get(&edge.target) {
                in_degree[ti] += 1;
            }
        }

        let mut queue: Vec<usize> = (0..n).filter(|&i| in_degree[i] == 0).collect();
        let mut order: Vec<String> = Vec::with_capacity(n);

        while let Some(u) = queue.pop() {
            order.push(self.nodes[u].id.clone());
            let uid = &self.nodes[u].id;
            for edge in &self.edges {
                if edge.source != *uid {
                    continue;
                }
                if let Some(&vi) = self.node_index.get(&edge.target) {
                    in_degree[vi] -= 1;
                    if in_degree[vi] == 0 {
                        queue.push(vi);
                    }
                }
            }
        }

        if order.len() != n {
            return Err("cycle detected — topological sort impossible".to_string());
        }
        Ok(order)
    }

    /// Group nodes into parallel execution stages based on the
    /// topological ordering and dependency depth.
    pub fn execution_stages(&self) -> Vec<Vec<String>> {
        let n = self.nodes.len();
        if n == 0 {
            return Vec::new();
        }

        let mut depth = vec![0usize; n];

        let order = match self.topological_sort() {
            Ok(o) => o,
            Err(_) => return Vec::new(),
        };

        for nid in &order {
            let ui = self.node_index[nid];
            for edge in &self.edges {
                if edge.source != *nid {
                    continue;
                }
                if let Some(&vi) = self.node_index.get(&edge.target) {
                    let new_depth = depth[ui] + 1;
                    if new_depth > depth[vi] {
                        depth[vi] = new_depth;
                    }
                }
            }
        }

        let max_depth = depth.iter().copied().max().unwrap_or(0);
        let mut stages: Vec<Vec<String>> = vec![Vec::new(); max_depth + 1];
        for (i, d) in depth.iter().enumerate() {
            stages[*d].push(self.nodes[i].id.clone());
        }
        stages
    }

    pub fn predecessors(&self, node_id: &str) -> Vec<String> {
        self.edges
            .iter()
            .filter(|e| e.target == node_id)
            .map(|e| e.source.clone())
            .collect()
    }

    pub fn successors(&self, node_id: &str) -> Vec<String> {
        self.edges
            .iter()
            .filter(|e| e.source == node_id)
            .map(|e| e.target.clone())
            .collect()
    }
}

// ---------------------------------------------------------------------------
// WorkflowBuilder — fluent API
// ---------------------------------------------------------------------------

pub struct WorkflowBuilder {
    name: String,
    nodes: Vec<WorkflowNode>,
    edges: Vec<WorkflowEdge>,
}

impl WorkflowBuilder {
    pub fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
            nodes: Vec::new(),
            edges: Vec::new(),
        }
    }

    pub fn add_agent_node(&mut self, id: &str, agent: &str) -> &mut Self {
        self.nodes.push(WorkflowNode {
            id: id.to_string(),
            node_type: NodeType::Agent,
            agent: agent.to_string(),
            tools: Vec::new(),
            config: HashMap::new(),
            condition_expr: String::new(),
            max_iterations: 0,
            transform_expr: String::new(),
        });
        self
    }

    pub fn add_tool_node(&mut self, id: &str, tools: Vec<String>) -> &mut Self {
        self.nodes.push(WorkflowNode {
            id: id.to_string(),
            node_type: NodeType::Tool,
            agent: String::new(),
            tools,
            config: HashMap::new(),
            condition_expr: String::new(),
            max_iterations: 0,
            transform_expr: String::new(),
        });
        self
    }

    pub fn connect(&mut self, source: &str, target: &str) -> &mut Self {
        self.edges.push(WorkflowEdge {
            source: source.to_string(),
            target: target.to_string(),
            condition: String::new(),
        });
        self
    }

    pub fn build(self) -> Result<WorkflowGraph, String> {
        let mut graph = WorkflowGraph::new(&self.name);
        for node in self.nodes {
            graph.add_node(node)?;
        }
        for edge in self.edges {
            graph.add_edge(edge)?;
        }
        let (valid, msg) = graph.validate();
        if !valid {
            return Err(msg);
        }
        Ok(graph)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn simple_node(id: &str, nt: NodeType) -> WorkflowNode {
        WorkflowNode {
            id: id.to_string(),
            node_type: nt,
            agent: String::new(),
            tools: Vec::new(),
            config: HashMap::new(),
            condition_expr: String::new(),
            max_iterations: 0,
            transform_expr: String::new(),
        }
    }

    #[test]
    fn test_add_node_and_edge() {
        let mut g = WorkflowGraph::new("g1");
        g.add_node(simple_node("a", NodeType::Agent)).unwrap();
        g.add_node(simple_node("b", NodeType::Tool)).unwrap();
        g.add_edge(WorkflowEdge {
            source: "a".into(),
            target: "b".into(),
            condition: String::new(),
        })
        .unwrap();

        assert_eq!(g.nodes().len(), 2);
        assert_eq!(g.edges().len(), 1);
        assert!(g.get_node("a").is_some());
    }

    #[test]
    fn test_duplicate_node_rejected() {
        let mut g = WorkflowGraph::new("g2");
        g.add_node(simple_node("x", NodeType::Agent)).unwrap();
        assert!(g.add_node(simple_node("x", NodeType::Tool)).is_err());
    }

    #[test]
    fn test_cycle_detection() {
        let mut g = WorkflowGraph::new("cyclic");
        g.add_node(simple_node("a", NodeType::Agent)).unwrap();
        g.add_node(simple_node("b", NodeType::Agent)).unwrap();
        g.add_node(simple_node("c", NodeType::Agent)).unwrap();

        g.add_edge(WorkflowEdge {
            source: "a".into(),
            target: "b".into(),
            condition: String::new(),
        })
        .unwrap();
        g.add_edge(WorkflowEdge {
            source: "b".into(),
            target: "c".into(),
            condition: String::new(),
        })
        .unwrap();
        g.add_edge(WorkflowEdge {
            source: "c".into(),
            target: "a".into(),
            condition: String::new(),
        })
        .unwrap();

        let (valid, _) = g.validate();
        assert!(!valid);
        assert!(g.topological_sort().is_err());
    }

    #[test]
    fn test_topological_sort_linear() {
        let mut g = WorkflowGraph::new("linear");
        g.add_node(simple_node("a", NodeType::Agent)).unwrap();
        g.add_node(simple_node("b", NodeType::Tool)).unwrap();
        g.add_node(simple_node("c", NodeType::Transform)).unwrap();

        g.add_edge(WorkflowEdge {
            source: "a".into(),
            target: "b".into(),
            condition: String::new(),
        })
        .unwrap();
        g.add_edge(WorkflowEdge {
            source: "b".into(),
            target: "c".into(),
            condition: String::new(),
        })
        .unwrap();

        let order = g.topological_sort().unwrap();
        let pos_a = order.iter().position(|x| x == "a").unwrap();
        let pos_b = order.iter().position(|x| x == "b").unwrap();
        let pos_c = order.iter().position(|x| x == "c").unwrap();
        assert!(pos_a < pos_b);
        assert!(pos_b < pos_c);
    }

    #[test]
    fn test_execution_stages_diamond() {
        //   a
        //  / \
        // b   c
        //  \ /
        //   d
        let mut g = WorkflowGraph::new("diamond");
        g.add_node(simple_node("a", NodeType::Agent)).unwrap();
        g.add_node(simple_node("b", NodeType::Tool)).unwrap();
        g.add_node(simple_node("c", NodeType::Tool)).unwrap();
        g.add_node(simple_node("d", NodeType::Transform)).unwrap();

        g.add_edge(WorkflowEdge { source: "a".into(), target: "b".into(), condition: String::new() }).unwrap();
        g.add_edge(WorkflowEdge { source: "a".into(), target: "c".into(), condition: String::new() }).unwrap();
        g.add_edge(WorkflowEdge { source: "b".into(), target: "d".into(), condition: String::new() }).unwrap();
        g.add_edge(WorkflowEdge { source: "c".into(), target: "d".into(), condition: String::new() }).unwrap();

        let stages = g.execution_stages();
        assert_eq!(stages.len(), 3);
        assert_eq!(stages[0], vec!["a"]);
        assert_eq!(stages[2], vec!["d"]);

        let mut mid = stages[1].clone();
        mid.sort();
        assert_eq!(mid, vec!["b", "c"]);
    }

    #[test]
    fn test_predecessors_and_successors() {
        let mut g = WorkflowGraph::new("ps");
        g.add_node(simple_node("a", NodeType::Agent)).unwrap();
        g.add_node(simple_node("b", NodeType::Tool)).unwrap();
        g.add_node(simple_node("c", NodeType::Tool)).unwrap();

        g.add_edge(WorkflowEdge { source: "a".into(), target: "b".into(), condition: String::new() }).unwrap();
        g.add_edge(WorkflowEdge { source: "a".into(), target: "c".into(), condition: String::new() }).unwrap();

        assert_eq!(g.successors("a").len(), 2);
        assert_eq!(g.predecessors("b"), vec!["a"]);
        assert!(g.predecessors("a").is_empty());
    }

    #[test]
    fn test_builder_happy_path() {
        let mut b = WorkflowBuilder::new("built");
        b.add_agent_node("step1", "simple");
        b.add_tool_node("step2", vec!["calculator".into()]);
        b.connect("step1", "step2");
        let graph = b.build().unwrap();

        assert_eq!(graph.nodes().len(), 2);
        assert_eq!(graph.edges().len(), 1);
        assert_eq!(graph.name, "built");
    }

    #[test]
    fn test_builder_rejects_cycle() {
        let mut b = WorkflowBuilder::new("bad");
        b.add_agent_node("x", "a1");
        b.add_agent_node("y", "a2");
        b.connect("x", "y");
        b.connect("y", "x");
        let result = b.build();

        assert!(result.is_err());
    }

    #[test]
    fn test_edge_unknown_node_rejected() {
        let mut g = WorkflowGraph::new("g");
        g.add_node(simple_node("a", NodeType::Agent)).unwrap();
        assert!(g
            .add_edge(WorkflowEdge {
                source: "a".into(),
                target: "z".into(),
                condition: String::new(),
            })
            .is_err());
    }
}
