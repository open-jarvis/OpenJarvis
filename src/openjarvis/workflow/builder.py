"""WorkflowBuilder — fluent API for constructing workflows."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from openjarvis.workflow.graph import WorkflowGraph
from openjarvis.workflow.types import NodeType, WorkflowEdge, WorkflowNode


class WorkflowBuilder:
    """Fluent API for building workflow graphs.

    Example:
        wf = (WorkflowBuilder("research_pipeline")
              .add_agent("researcher", agent="orchestrator", tools=["web_search"])
              .add_agent("summarizer", agent="simple")
              .connect("researcher", "summarizer")
              .build())
    """

    def __init__(self, name: str = "") -> None:
        self._name = name
        self._nodes: List[WorkflowNode] = []
        self._edges: List[WorkflowEdge] = []

    def add_agent(
        self,
        node_id: str,
        *,
        agent: str = "simple",
        tools: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> WorkflowBuilder:
        self._nodes.append(
            WorkflowNode(
                id=node_id,
                node_type=NodeType.AGENT,
                agent=agent,
                tools=tools or [],
                config=config or {},
            )
        )
        return self

    def add_tool(
        self,
        node_id: str,
        *,
        tool_name: str,
        tool_args: str = "{}",
    ) -> WorkflowBuilder:
        self._nodes.append(
            WorkflowNode(
                id=node_id,
                node_type=NodeType.TOOL,
                config={"tool_name": tool_name, "tool_args": tool_args},
            )
        )
        return self

    def add_condition(
        self,
        node_id: str,
        *,
        expr: str,
    ) -> WorkflowBuilder:
        self._nodes.append(
            WorkflowNode(
                id=node_id,
                node_type=NodeType.CONDITION,
                condition_expr=expr,
            )
        )
        return self

    def add_loop(
        self,
        node_id: str,
        *,
        agent: str = "simple",
        max_iterations: int = 10,
        exit_condition: str = "",
    ) -> WorkflowBuilder:
        self._nodes.append(
            WorkflowNode(
                id=node_id,
                node_type=NodeType.LOOP,
                agent=agent,
                max_iterations=max_iterations,
                condition_expr=exit_condition,
            )
        )
        return self

    def add_transform(
        self,
        node_id: str,
        *,
        transform: str = "concatenate",
    ) -> WorkflowBuilder:
        self._nodes.append(
            WorkflowNode(
                id=node_id,
                node_type=NodeType.TRANSFORM,
                transform_expr=transform,
            )
        )
        return self

    def connect(
        self,
        source: str,
        target: str,
        *,
        condition: str = "",
    ) -> WorkflowBuilder:
        self._edges.append(
            WorkflowEdge(
                source=source,
                target=target,
                condition=condition,
            )
        )
        return self

    def sequential(self, *node_ids: str) -> WorkflowBuilder:
        """Connect nodes in sequential order."""
        for i in range(len(node_ids) - 1):
            self._edges.append(
                WorkflowEdge(
                    source=node_ids[i],
                    target=node_ids[i + 1],
                )
            )
        return self

    def build(self) -> WorkflowGraph:
        graph = WorkflowGraph(name=self._name)
        for node in self._nodes:
            graph.add_node(node)
        for edge in self._edges:
            graph.add_edge(edge)
        valid, msg = graph.validate()
        if not valid:
            raise ValueError(f"Invalid workflow graph: {msg}")
        return graph


__all__ = ["WorkflowBuilder"]
