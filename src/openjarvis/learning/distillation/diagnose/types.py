"""Data types for the diagnose phase.

Lightweight dataclasses used as return types by diagnostic tools and
as internal data carriers. These are NOT pydantic models — they don't
need validation or JSON schema generation.

See spec §5.2 for the tool return type rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


@dataclass(slots=True)
class TraceMeta:
    """Lightweight summary of a trace for browsing."""

    trace_id: str
    query: str
    agent: str
    model: str
    outcome: Optional[str]
    feedback: Optional[float]
    started_at: float


@dataclass(slots=True)
class BenchmarkTask:
    """One task from the personal benchmark."""

    task_id: str
    query: str
    reference_answer: str
    category: str = "chat"


@dataclass(slots=True)
class StudentRun:
    """Result of re-executing the local student on a benchmark task."""

    task_id: str
    output: str
    score: float
    trace_id: str
    latency_seconds: float
    tokens_used: int


@dataclass(slots=True)
class TeacherRun:
    """Result of the teacher running itself on a benchmark task."""

    task_id: str
    output: str
    reasoning: str
    cost_usd: float
    tokens_used: int


@dataclass(slots=True)
class ComparisonResult:
    """Structured comparison between student and teacher outputs."""

    task_id: str
    student_score: float
    teacher_score: float
    judge_reasoning: str


@dataclass(slots=True)
class ToolMeta:
    """Metadata about a tool in the ToolRegistry."""

    name: str
    description: str
    category: str
    agents: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DiagnosticTool:
    """A tool exposed to the teacher in the diagnose phase.

    Unlike ``BaseTool``, these are not registered in ``ToolRegistry``.
    They are lightweight wrappers: a name, description, JSON schema
    for parameters, and a callable that implements the tool.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]

    def to_openai_function(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(slots=True)
class ToolCallRecord:
    """One teacher tool call, persisted to the JSONL log."""

    timestamp: datetime
    tool: str
    args: dict[str, Any]
    result: str
    latency_ms: float
    cost_usd: float

    def to_jsonl_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for JSONL output."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
        }
