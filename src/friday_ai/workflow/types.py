"""Workflow type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class NodeType(str, Enum):
    AGENT = "agent"
    TOOL = "tool"
    CONDITION = "condition"
    PARALLEL = "parallel"
    LOOP = "loop"
    TRANSFORM = "transform"


@dataclass(slots=True)
class WorkflowNode:
    id: str
    node_type: NodeType
    agent: str = ""
    tools: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    # For condition nodes
    condition_expr: str = ""
    # For loop nodes
    max_iterations: int = 10
    # For transform nodes
    transform_expr: str = ""


@dataclass(slots=True)
class WorkflowEdge:
    source: str
    target: str
    condition: str = ""  # optional condition for conditional routing


@dataclass(slots=True)
class WorkflowStepResult:
    node_id: str
    success: bool = True
    output: str = ""
    duration_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowResult:
    workflow_name: str = ""
    success: bool = True
    steps: List[WorkflowStepResult] = field(default_factory=list)
    final_output: str = ""
    total_duration_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "NodeType",
    "WorkflowEdge",
    "WorkflowNode",
    "WorkflowResult",
    "WorkflowStepResult",
]
