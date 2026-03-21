"""Tests for workflow engine (Phase 15.1)."""

from __future__ import annotations

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.workflow.builder import WorkflowBuilder
from openjarvis.workflow.engine import WorkflowEngine
from openjarvis.workflow.graph import WorkflowGraph
from openjarvis.workflow.types import NodeType, WorkflowEdge, WorkflowNode


class TestWorkflowGraph:
    def test_add_node(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        assert g.get_node("a") is not None
        assert len(g.nodes) == 1

    def test_add_duplicate_node_raises(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        with pytest.raises(ValueError, match="Duplicate"):
            g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))

    def test_add_edge(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        assert len(g.edges) == 1

    def test_add_edge_missing_source_raises(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        with pytest.raises(ValueError, match="Source"):
            g.add_edge(WorkflowEdge(source="a", target="b"))

    def test_validate_acyclic(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        valid, msg = g.validate()
        assert valid

    def test_validate_cyclic(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        g.add_edge(WorkflowEdge(source="b", target="a"))
        valid, msg = g.validate()
        assert not valid
        assert "Cycle" in msg

    def test_topological_sort(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="c", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        g.add_edge(WorkflowEdge(source="b", target="c"))
        order = g.topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_execution_stages(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="c", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="c"))
        g.add_edge(WorkflowEdge(source="b", target="c"))
        stages = g.execution_stages()
        # a and b can run in parallel (stage 1), c after (stage 2)
        assert len(stages) == 2
        assert set(stages[0]) == {"a", "b"}
        assert stages[1] == ["c"]

    def test_predecessors_successors(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        assert g.predecessors("b") == ["a"]
        assert g.successors("a") == ["b"]


class TestWorkflowBuilder:
    def test_build_simple(self):
        wf = (
            WorkflowBuilder("test")
            .add_agent("a", agent="simple")
            .add_agent("b", agent="simple")
            .connect("a", "b")
            .build()
        )
        assert wf.name == "test"
        assert len(wf.nodes) == 2
        assert len(wf.edges) == 1

    def test_sequential(self):
        wf = (
            WorkflowBuilder("seq")
            .add_agent("a", agent="simple")
            .add_agent("b", agent="simple")
            .add_agent("c", agent="simple")
            .sequential("a", "b", "c")
            .build()
        )
        assert len(wf.edges) == 2

    def test_build_cyclic_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            (
                WorkflowBuilder("bad")
                .add_agent("a", agent="simple")
                .add_agent("b", agent="simple")
                .connect("a", "b")
                .connect("b", "a")
                .build()
            )


class TestWorkflowEngine:
    def test_run_invalid_graph(self):
        engine = WorkflowEngine()
        g = WorkflowGraph("bad")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        g.add_edge(WorkflowEdge(source="b", target="a"))
        result = engine.run(g)
        assert not result.success

    def test_run_transform_node(self):
        bus = EventBus(record_history=True)
        engine = WorkflowEngine(bus=bus)
        wf = WorkflowBuilder("test").add_transform("t", transform="concatenate").build()
        result = engine.run(wf, initial_input="hello")
        assert result.success

    def test_events_emitted(self):
        bus = EventBus(record_history=True)
        engine = WorkflowEngine(bus=bus)
        wf = WorkflowBuilder("test").add_transform("t", transform="concatenate").build()
        engine.run(wf, initial_input="hello")
        event_types = {e.event_type for e in bus.history}
        assert EventType.WORKFLOW_START in event_types
        assert EventType.WORKFLOW_END in event_types
