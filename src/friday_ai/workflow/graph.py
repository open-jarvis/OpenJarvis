"""WorkflowGraph — DAG with validation and topological sort."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Optional, Set, Tuple

from friday_ai.workflow.types import WorkflowEdge, WorkflowNode


class WorkflowGraph:
    """Directed acyclic graph of workflow nodes.

    Supports DAG validation (cycle detection), topological sort,
    and execution_stages() for parallel-ready ordering.
    """

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._nodes: Dict[str, WorkflowNode] = {}
        self._edges: List[WorkflowEdge] = []
        self._adjacency: Dict[str, List[str]] = defaultdict(list)
        self._reverse: Dict[str, List[str]] = defaultdict(list)

    def add_node(self, node: WorkflowNode) -> None:
        if node.id in self._nodes:
            raise ValueError(f"Duplicate node id: {node.id}")
        self._nodes[node.id] = node

    def add_edge(self, edge: WorkflowEdge) -> None:
        if edge.source not in self._nodes:
            raise ValueError(f"Source node '{edge.source}' not found")
        if edge.target not in self._nodes:
            raise ValueError(f"Target node '{edge.target}' not found")
        self._edges.append(edge)
        self._adjacency[edge.source].append(edge.target)
        self._reverse[edge.target].append(edge.source)

    def get_node(self, node_id: str) -> Optional[WorkflowNode]:
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> List[WorkflowNode]:
        return list(self._nodes.values())

    @property
    def edges(self) -> List[WorkflowEdge]:
        return list(self._edges)

    def validate(self) -> Tuple[bool, str]:
        """Validate the graph: check for cycles and orphan nodes."""
        # Check for cycles using DFS
        visited: Set[str] = set()
        in_stack: Set[str] = set()

        def _dfs(node_id: str) -> bool:
            visited.add(node_id)
            in_stack.add(node_id)
            for neighbor in self._adjacency.get(node_id, []):
                if neighbor in in_stack:
                    return True  # cycle detected
                if neighbor not in visited and _dfs(neighbor):
                    return True
            in_stack.discard(node_id)
            return False

        for node_id in self._nodes:
            if node_id not in visited:
                if _dfs(node_id):
                    return False, f"Cycle detected involving node '{node_id}'"

        return True, ""

    def topological_sort(self) -> List[str]:
        """Return node IDs in topological order (Kahn's algorithm)."""
        in_degree: Dict[str, int] = {nid: 0 for nid in self._nodes}
        for edge in self._edges:
            in_degree[edge.target] = in_degree.get(edge.target, 0) + 1

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        order: List[str] = []

        while queue:
            node_id = queue.popleft()
            order.append(node_id)
            for neighbor in self._adjacency.get(node_id, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self._nodes):
            raise ValueError("Graph contains a cycle; topological sort is impossible")
        return order

    def execution_stages(self) -> List[List[str]]:
        """Group nodes into parallel execution stages.

        Nodes in the same stage have no dependencies on each other and
        can be executed concurrently.
        """
        in_degree: Dict[str, int] = {nid: 0 for nid in self._nodes}
        for edge in self._edges:
            in_degree[edge.target] = in_degree.get(edge.target, 0) + 1

        stages: List[List[str]] = []
        ready = [nid for nid, deg in in_degree.items() if deg == 0]

        while ready:
            stages.append(sorted(ready))
            next_ready: List[str] = []
            for node_id in ready:
                for neighbor in self._adjacency.get(node_id, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_ready.append(neighbor)
            ready = next_ready

        return stages

    def predecessors(self, node_id: str) -> List[str]:
        return self._reverse.get(node_id, [])

    def successors(self, node_id: str) -> List[str]:
        return self._adjacency.get(node_id, [])


__all__ = ["WorkflowGraph"]
