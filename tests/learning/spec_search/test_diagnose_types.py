"""Tests for openjarvis.learning.spec_search.diagnose.types module."""

from __future__ import annotations

from datetime import datetime, timezone


class TestTraceMeta:
    """Tests for TraceMeta dataclass."""

    def test_constructs_with_required_fields(self) -> None:
        from openjarvis.learning.spec_search.diagnose.types import TraceMeta

        meta = TraceMeta(
            trace_id="trace-001",
            query="What is 2+2?",
            agent="simple",
            model="qwen2.5-coder:7b",
            outcome="success",
            feedback=0.8,
            started_at=1712534400.0,
        )
        assert meta.trace_id == "trace-001"
        assert meta.feedback == 0.8

    def test_feedback_can_be_none(self) -> None:
        from openjarvis.learning.spec_search.diagnose.types import TraceMeta

        meta = TraceMeta(
            trace_id="trace-002",
            query="test",
            agent="simple",
            model="qwen2.5-coder:7b",
            outcome=None,
            feedback=None,
            started_at=1712534400.0,
        )
        assert meta.feedback is None


class TestBenchmarkTask:
    """Tests for BenchmarkTask dataclass."""

    def test_constructs(self) -> None:
        from openjarvis.learning.spec_search.diagnose.types import BenchmarkTask

        task = BenchmarkTask(
            task_id="task-001",
            query="Explain quantum computing",
            reference_answer="Quantum computing uses qubits...",
            category="reasoning",
        )
        assert task.task_id == "task-001"
        assert task.category == "reasoning"


class TestStudentRun:
    """Tests for StudentRun dataclass."""

    def test_constructs(self) -> None:
        from openjarvis.learning.spec_search.diagnose.types import StudentRun

        run = StudentRun(
            task_id="task-001",
            output="The answer is 4.",
            score=0.9,
            trace_id="trace-new-001",
            latency_seconds=2.5,
            tokens_used=150,
        )
        assert run.score == 0.9
        assert run.trace_id == "trace-new-001"


class TestTeacherRun:
    """Tests for TeacherRun dataclass."""

    def test_constructs(self) -> None:
        from openjarvis.learning.spec_search.diagnose.types import TeacherRun

        run = TeacherRun(
            task_id="task-001",
            output="Quantum computing is...",
            reasoning="I approached this by...",
            cost_usd=0.05,
            tokens_used=500,
        )
        assert run.cost_usd == 0.05


class TestComparisonResult:
    """Tests for ComparisonResult dataclass."""

    def test_constructs(self) -> None:
        from openjarvis.learning.spec_search.diagnose.types import ComparisonResult

        result = ComparisonResult(
            task_id="task-001",
            student_score=0.3,
            teacher_score=0.9,
            judge_reasoning="The student missed the key concept...",
        )
        assert result.student_score == 0.3
        assert result.teacher_score == 0.9


class TestToolMeta:
    """Tests for ToolMeta dataclass."""

    def test_constructs(self) -> None:
        from openjarvis.learning.spec_search.diagnose.types import ToolMeta

        meta = ToolMeta(
            name="calculator",
            description="Evaluate math expressions",
            category="math",
            agents=["simple", "react"],
        )
        assert meta.name == "calculator"
        assert len(meta.agents) == 2


class TestDiagnosticTool:
    """Tests for DiagnosticTool dataclass."""

    def test_constructs_with_callable(self) -> None:
        from openjarvis.learning.spec_search.diagnose.types import DiagnosticTool

        def my_func(**kwargs: object) -> str:
            return "result"

        tool = DiagnosticTool(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            fn=my_func,
        )
        assert tool.name == "test_tool"
        assert tool.fn(foo="bar") == "result"


class TestToolCallRecord:
    """Tests for ToolCallRecord dataclass."""

    def test_constructs(self) -> None:
        from openjarvis.learning.spec_search.diagnose.types import ToolCallRecord

        record = ToolCallRecord(
            timestamp=datetime(2026, 4, 9, 3, 0, 0, tzinfo=timezone.utc),
            tool="list_traces",
            args={"limit": 10},
            result="[...]",
            latency_ms=42.5,
            cost_usd=0.0,
        )
        assert record.tool == "list_traces"
        assert record.latency_ms == 42.5

    def test_to_jsonl_dict(self) -> None:
        from openjarvis.learning.spec_search.diagnose.types import ToolCallRecord

        record = ToolCallRecord(
            timestamp=datetime(2026, 4, 9, 3, 0, 0, tzinfo=timezone.utc),
            tool="get_trace",
            args={"trace_id": "t1"},
            result="trace data",
            latency_ms=10.0,
            cost_usd=0.01,
        )
        d = record.to_jsonl_dict()
        assert d["tool"] == "get_trace"
        assert d["timestamp"] == "2026-04-09T03:00:00+00:00"
        assert d["cost_usd"] == 0.01
